"""U7 tests: the TUI plan review / edit / apply flow.

Prompt input is injected by replacing ``rom_stuffer.review.Prompt`` with a fake
whose ``.ask`` returns queued answers in order.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import rom_stuffer.review as review
from rom_stuffer.dedup import DedupOptions
from rom_stuffer.planfile import DedupGroup, DedupPlan, load_plan


class FakePrompt:
    """Stand-in for rich's Prompt: ``.ask`` pops queued answers in order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.i = 0

    def ask(self, *args, **kwargs):
        if self.i >= len(self.answers):
            raise AssertionError("FakePrompt ran out of queued answers")
        value = self.answers[self.i]
        self.i += 1
        return value


def _inject(monkeypatch, answers):
    monkeypatch.setattr(review, "Prompt", FakePrompt(answers))


def _build_plan(tmp_path, keeper_rel, removal_rels, sha="a" * 64):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    keeper = src / keeper_rel
    keeper.parent.mkdir(parents=True, exist_ok=True)
    keeper.write_bytes(b"KEEP")
    removals = []
    for rel in removal_rels:
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"DUPE")
        removals.append(p)
    group = DedupGroup(sha256=sha, keeper=keeper, removals=removals, reclaimed_bytes=4)
    plan = DedupPlan(version=1, source=src, created_at="2026-07-17T00:00:00Z",
                     groups=[group])
    opts = DedupOptions(source=src, dest=dest)
    return plan, opts


# --------------------------------------------------------------------------- #
# T7.1 -- accept-all returns the plan unchanged
# --------------------------------------------------------------------------- #

def test_accept_all_unchanged(tmp_path, monkeypatch):
    plan, opts = _build_plan(tmp_path, "gba/game.gba", ["gba/backup/game.gba"])
    keeper_before = plan.groups[0].keeper
    removals_before = list(plan.groups[0].removals)

    _inject(monkeypatch, ["a"])
    result = review.review_plan(plan, opts)

    assert result.groups[0].keeper == keeper_before
    assert result.groups[0].removals == removals_before
    assert result.groups[0].skipped is False


# --------------------------------------------------------------------------- #
# T7.2 -- change keeper updates keeper + removals
# --------------------------------------------------------------------------- #

def test_change_keeper(tmp_path, monkeypatch):
    plan, opts = _build_plan(tmp_path, "gba/game.gba", ["gba/backup/game.gba"])
    path_a = plan.groups[0].keeper
    path_b = plan.groups[0].removals[0]

    # accept -> edit -> group 1 -> set keeper to #2 -> accept the rest
    _inject(monkeypatch, ["e", "1", "2", "a"])
    result = review.review_plan(plan, opts)

    assert result.groups[0].keeper == path_b
    assert result.groups[0].removals == [path_a]


# --------------------------------------------------------------------------- #
# T7.3 -- skip a group marks it skipped
# --------------------------------------------------------------------------- #

def test_skip_group(tmp_path, monkeypatch):
    plan, opts = _build_plan(tmp_path, "gba/game.gba", ["gba/backup/game.gba"])

    _inject(monkeypatch, ["e", "1", "s", "a"])
    result = review.review_plan(plan, opts)

    assert result.groups[0].skipped is True


# --------------------------------------------------------------------------- #
# T7.4 -- Rich markup brackets in a filename do not raise
# --------------------------------------------------------------------------- #

def test_markup_in_filename_escaped(tmp_path, monkeypatch):
    plan, opts = _build_plan(
        tmp_path, "gba/Game [USA].gba", ["gba/backup/Game [USA].gba"]
    )
    _inject(monkeypatch, ["a"])
    # Must not raise rich.errors.MarkupError.
    result = review.review_plan(plan, opts)
    assert result.groups[0].keeper.name == "Game [USA].gba"


# --------------------------------------------------------------------------- #
# T7.5 -- many groups paginate without error
# --------------------------------------------------------------------------- #

def test_pagination_many_groups(tmp_path, monkeypatch):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    groups = []
    for i in range(25):
        keeper = src / f"s{i}" / "game.gba"
        keeper.parent.mkdir(parents=True, exist_ok=True)
        keeper.write_bytes(b"K")
        removal = src / f"s{i}" / "backup" / "game.gba"
        removal.parent.mkdir(parents=True, exist_ok=True)
        removal.write_bytes(b"D")
        groups.append(
            DedupGroup(sha256=f"{i:064d}", keeper=keeper, removals=[removal],
                       reclaimed_bytes=1)
        )
    plan = DedupPlan(version=1, source=src, created_at="2026-07-17T00:00:00Z",
                     groups=groups)
    opts = DedupOptions(source=src, dest=dest)

    _inject(monkeypatch, ["a"])
    result = review.review_plan(plan, opts)
    assert len(result.groups) == 25


# --------------------------------------------------------------------------- #
# T7.6 -- quit exits cleanly with SystemExit(0)
# --------------------------------------------------------------------------- #

def test_quit_exits(tmp_path, monkeypatch):
    plan, opts = _build_plan(tmp_path, "gba/game.gba", ["gba/backup/game.gba"])
    _inject(monkeypatch, ["q"])
    with pytest.raises(SystemExit) as exc:
        review.review_plan(plan, opts)
    assert exc.value.code == 0


# --------------------------------------------------------------------------- #
# The reviewed plan is persisted (save_plan) before returning
# --------------------------------------------------------------------------- #

def test_review_persists_plan(tmp_path, monkeypatch):
    plan, opts = _build_plan(tmp_path, "gba/game.gba", ["gba/backup/game.gba"])
    _inject(monkeypatch, ["e", "1", "2", "a"])
    review.review_plan(plan, opts)

    reloaded = load_plan(opts.dest)
    # The hand-changed keeper survives the save/load round-trip.
    assert reloaded.groups[0].keeper.name == "game.gba"
    assert reloaded.groups[0].keeper.parent.name == "backup"


# --------------------------------------------------------------------------- #
# Interactive per-group mode walks each group
# --------------------------------------------------------------------------- #

def test_interactive_mode_accepts_each(tmp_path, monkeypatch):
    plan, opts = _build_plan(tmp_path, "gba/game.gba", ["gba/backup/game.gba"])
    opts.interactive = True
    _inject(monkeypatch, ["a"])  # one group -> one accept prompt
    result = review.review_plan(plan, opts)
    assert result.groups[0].skipped is False
