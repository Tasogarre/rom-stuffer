"""U8 tests: the dedup executor (quarantine / hard-delete) + safety invariants.

Every one of the six documented safety invariants has at least one named test
here (or in test_run_dedup.py for the end-to-end / preview ones):

  1. keeper never moved/deleted  -> test_invariant1_keeper_never_touched,
                                     test_invariant1_keeper_in_removals_aborts
  2. quarantine reversible       -> test_invariant2_quarantine_reversible
  3. dry-run removes nothing     -> test_invariant3_dry_run_changes_nothing
  4. skipped groups honoured     -> test_invariant4_skipped_group_untouched
  5. BIOS/disc never in a group  -> (test_run_dedup.py end-to-end)
  6. per-file failure + resume   -> test_invariant6_failure_recorded_continues,
                                     test_invariant6_interrupted_apply_resumes
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rom_stuffer.dedup import (
    DEDUP_BACKUP_DIRNAME,
    DEDUP_JOURNAL_FILENAME,
    DedupOptions,
    apply_plan,
)
from rom_stuffer.planfile import DedupGroup, DedupPlan

from helpers import RomTree


def _opts(src: Path, dest: Path, **kw) -> DedupOptions:
    return DedupOptions(source=src, dest=dest, **kw)


def _plan(source: Path, *groups: DedupGroup) -> DedupPlan:
    return DedupPlan(version=1, source=source, created_at="2026-07-17T00:00:00Z",
                     groups=list(groups))


def _group(keeper: Path, removals: list[Path], sha: str = "a" * 64) -> DedupGroup:
    reclaimed = 0
    for r in removals:
        try:
            reclaimed += r.stat().st_size
        except OSError:
            pass
    return DedupGroup(sha256=sha, keeper=keeper, removals=list(removals),
                      reclaimed_bytes=reclaimed)


# --------------------------------------------------------------------------- #
# T8.1 / invariant 1 -- quarantine moves removals, keeper stays with its bytes
# --------------------------------------------------------------------------- #

def test_invariant1_keeper_never_touched(tmp_path):
    content = b"ROM" * 512
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/backup", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    keeper = src / "gba" / "game.gba"
    removal = src / "gba" / "backup" / "game.gba"
    plan = _plan(src, _group(keeper, [removal]))

    metrics = apply_plan(plan, _opts(src, dest))

    # Keeper untouched, original bytes intact.
    assert keeper.exists()
    assert keeper.read_bytes() == content
    # Removal gone from source, present in quarantine with same content.
    assert not removal.exists()
    quarantined = dest / DEDUP_BACKUP_DIRNAME / "gba" / "backup" / "game.gba"
    assert quarantined.exists()
    assert quarantined.read_bytes() == content
    assert metrics.files_removed == 1
    assert metrics.bytes_reclaimed == len(content)
    assert metrics.errors == []


# --------------------------------------------------------------------------- #
# T8.2 -- structure preserved across multiple subdirectories
# --------------------------------------------------------------------------- #

def test_quarantine_preserves_structure(tmp_path):
    content = b"DATA" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "keep.gba", content=content)
    tree.cartridge("gba/dupes", "a.gba", content=content)
    tree.cartridge("snes/backup", "b.gba", content=content)
    tree.cartridge("nes/deep/copies", "c.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    removals = [
        src / "gba" / "dupes" / "a.gba",
        src / "snes" / "backup" / "b.gba",
        src / "nes" / "deep" / "copies" / "c.gba",
    ]
    plan = _plan(src, _group(src / "gba" / "keep.gba", removals))

    apply_plan(plan, _opts(src, dest))

    for rel in ("gba/dupes/a.gba", "snes/backup/b.gba", "nes/deep/copies/c.gba"):
        assert (dest / DEDUP_BACKUP_DIRNAME / rel).exists()
        assert not (src / rel).exists()


# --------------------------------------------------------------------------- #
# T8.3 / invariant 3 -- dry-run changes nothing
# --------------------------------------------------------------------------- #

def test_invariant3_dry_run_changes_nothing(tmp_path):
    content = b"ROM" * 512
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/backup", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    keeper = src / "gba" / "game.gba"
    removal = src / "gba" / "backup" / "game.gba"
    plan = _plan(src, _group(keeper, [removal]))

    before = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
    metrics = apply_plan(plan, _opts(src, dest, dry_run=True))

    # Nothing moved or deleted.
    assert keeper.exists()
    assert removal.exists()
    after = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
    assert before == after
    assert not (dest / DEDUP_BACKUP_DIRNAME).exists()
    # No journal written in dry-run.
    assert not (dest / DEDUP_JOURNAL_FILENAME).exists()
    # Counted what WOULD be removed.
    assert metrics.files_removed == 1
    assert metrics.bytes_reclaimed == len(content)
    assert metrics.dry_run is True


# --------------------------------------------------------------------------- #
# T8.4 -- hard-delete removes files (not quarantined)
# --------------------------------------------------------------------------- #

def test_hard_delete_removes_files(tmp_path):
    content = b"ROM" * 512
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/backup", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    keeper = src / "gba" / "game.gba"
    removal = src / "gba" / "backup" / "game.gba"
    plan = _plan(src, _group(keeper, [removal]))

    metrics = apply_plan(plan, _opts(src, dest, hard_delete=True))

    assert keeper.exists()
    assert not removal.exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME).exists()  # deleted, not quarantined
    assert metrics.files_removed == 1


# --------------------------------------------------------------------------- #
# T8.5 / invariant 1 -- keeper present in removals aborts before touching files
# --------------------------------------------------------------------------- #

def test_invariant1_keeper_in_removals_aborts(tmp_path):
    content = b"ROM" * 512
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/backup", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    keeper = src / "gba" / "game.gba"
    other = src / "gba" / "backup" / "game.gba"
    # Malformed plan: the keeper is also listed as a removal.
    bad = DedupGroup(sha256="b" * 64, keeper=keeper, removals=[keeper, other],
                     reclaimed_bytes=0)
    plan = _plan(src, bad)

    with pytest.raises(AssertionError):
        apply_plan(plan, _opts(src, dest))

    # Nothing was touched -- both files still present, no quarantine dir.
    assert keeper.exists()
    assert other.exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME).exists()


# --------------------------------------------------------------------------- #
# Invariant 2 -- quarantine is reversible: move the file back, tree restored
# --------------------------------------------------------------------------- #

def test_invariant2_quarantine_reversible(tmp_path):
    content = b"REVERSIBLE" * 100
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/backup", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    keeper = src / "gba" / "game.gba"
    removal = src / "gba" / "backup" / "game.gba"
    plan = _plan(src, _group(keeper, [removal]))

    apply_plan(plan, _opts(src, dest))
    quarantined = dest / DEDUP_BACKUP_DIRNAME / "gba" / "backup" / "game.gba"
    assert quarantined.exists()
    assert not removal.exists()

    # Restore: move it back to its original relative location.
    removal.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(quarantined), str(removal))

    assert removal.exists()
    assert removal.read_bytes() == content
    assert keeper.read_bytes() == content


# --------------------------------------------------------------------------- #
# Invariant 4 -- a skipped group is never touched
# --------------------------------------------------------------------------- #

def test_invariant4_skipped_group_untouched(tmp_path):
    content_a = b"AAAA" * 256
    content_b = b"BBBB" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "a.gba", content=content_a)
    tree.cartridge("gba/backup", "a.gba", content=content_a)
    tree.cartridge("snes", "b.gba", content=content_b)
    tree.cartridge("snes/backup", "b.gba", content=content_b)
    src = tree.source
    dest = tmp_path / "dest"

    g_skip = _group(src / "gba" / "a.gba", [src / "gba" / "backup" / "a.gba"], sha="c" * 64)
    g_skip.skipped = True
    g_do = _group(src / "snes" / "b.gba", [src / "snes" / "backup" / "b.gba"], sha="d" * 64)
    plan = _plan(src, g_skip, g_do)

    metrics = apply_plan(plan, _opts(src, dest))

    # Skipped group: both files remain in place, nothing quarantined.
    assert (src / "gba" / "backup" / "a.gba").exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME / "gba" / "backup" / "a.gba").exists()
    # Active group: removal was quarantined.
    assert not (src / "snes" / "backup" / "b.gba").exists()
    assert (dest / DEDUP_BACKUP_DIRNAME / "snes" / "backup" / "b.gba").exists()
    assert metrics.files_removed == 1


# --------------------------------------------------------------------------- #
# T8.6 / invariant 6 -- an interrupted apply resumes without double-processing
# --------------------------------------------------------------------------- #

def test_invariant6_interrupted_apply_resumes(tmp_path):
    content = b"ROM" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "keep.gba", content=content)
    tree.cartridge("gba/d1", "one.gba", content=content)
    tree.cartridge("gba/d2", "two.gba", content=content)
    tree.cartridge("gba/d3", "three.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"
    dest.mkdir()

    removals = [
        src / "gba" / "d1" / "one.gba",
        src / "gba" / "d2" / "two.gba",
        src / "gba" / "d3" / "three.gba",
    ]
    plan = _plan(src, _group(src / "gba" / "keep.gba", removals))

    # Pre-seed the journal as if d1/one.gba was already processed in a prior run.
    (dest / DEDUP_JOURNAL_FILENAME).write_text("gba/d1/one.gba\n", encoding="utf-8")

    metrics = apply_plan(plan, _opts(src, dest))

    # The already-journalled removal is NOT re-processed: it is left on disk and
    # not counted; only the two remaining removals are quarantined.
    assert (src / "gba" / "d1" / "one.gba").exists()  # untouched (skipped as done)
    assert not (src / "gba" / "d2" / "two.gba").exists()
    assert not (src / "gba" / "d3" / "three.gba").exists()
    assert metrics.files_removed == 2


# --------------------------------------------------------------------------- #
# T8.7 / invariant 6 -- a failure on one file is recorded, batch continues
# --------------------------------------------------------------------------- #

def test_invariant6_failure_recorded_continues(tmp_path, monkeypatch):
    content = b"ROM" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "keep.gba", content=content)
    tree.cartridge("gba/d1", "one.gba", content=content)
    tree.cartridge("gba/d2", "two.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    removals = [src / "gba" / "d1" / "one.gba", src / "gba" / "d2" / "two.gba"]
    plan = _plan(src, _group(src / "gba" / "keep.gba", removals))

    real_move = shutil.move
    calls = {"n": 0}

    def flaky_move(s, d):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(13, "Permission denied", str(s))
        return real_move(s, d)

    monkeypatch.setattr(shutil, "move", flaky_move)
    metrics = apply_plan(plan, _opts(src, dest))

    assert len(metrics.errors) == 1
    assert metrics.files_removed == 1  # the second removal still succeeded
    # Keeper always safe.
    assert (src / "gba" / "keep.gba").exists()


# --------------------------------------------------------------------------- #
# Source mismatch guard
# --------------------------------------------------------------------------- #

def test_source_mismatch_raises_value_error(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    plan = _plan(tmp_path / "other", _group(src / "keep.gba", [src / "dupe.gba"]))
    with pytest.raises(ValueError):
        apply_plan(plan, _opts(src, dest))


# --------------------------------------------------------------------------- #
# Idempotent: an already-missing removal is recorded as done, not an error
# --------------------------------------------------------------------------- #

def test_missing_removal_is_idempotent(tmp_path):
    content = b"ROM" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "keep.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    ghost = src / "gba" / "gone.gba"  # never created
    plan = _plan(src, _group(src / "gba" / "keep.gba", [ghost]))

    metrics = apply_plan(plan, _opts(src, dest))
    assert metrics.errors == []
    assert metrics.files_removed == 0
    assert (dest / DEDUP_JOURNAL_FILENAME).read_text().strip() == "gba/gone.gba"
