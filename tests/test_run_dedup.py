"""run_dedup orchestration tests + the preview & BIOS/disc safety invariants.

Covers the two safety invariants best proven end-to-end:
  3. dedup defaults to preview   -> test_invariant3_dry_run_removes_nothing
  5. BIOS/disc never in a group  -> test_invariant5_bios_disc_never_removed
plus the required real end-to-end quarantine run.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import rom_stuffer.review as review
from rom_stuffer.dedup import (
    DEDUP_BACKUP_DIRNAME,
    DedupOptions,
    detect_duplicates,
    run_dedup,
)
from rom_stuffer.planfile import (
    DEDUP_PLAN_FILENAME,
    HASH_INDEX_FILENAME,
    build_plan,
    save_plan,
)

from helpers import RomTree


class FakePrompt:
    def __init__(self, answers):
        self.answers = list(answers)
        self.i = 0

    def ask(self, *args, **kwargs):
        v = self.answers[self.i]
        self.i += 1
        return v


def _accept_all(monkeypatch):
    """Make the review TUI accept the plan as-is."""
    monkeypatch.setattr(review, "Prompt", FakePrompt(["a"] * 50))


def _args(source, dest, **kw):
    ns = argparse.Namespace(
        source=str(source),
        dest=str(dest),
        sdcard=None,
        dry_run=False,
        resume=False,
        fresh=False,
        keeper_order=None,
        protect=[],
        per_system=False,
        min_size=0,
        interactive=False,
        hard_delete=False,
        apply_plan=None,
    )
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def _dupe_bios_disc_tree(tmp_path):
    """A tree with one duplicate pair, a BIOS file, and a disc-image folder."""
    tree = RomTree(tmp_path / "src")
    content = b"ZELDA_ROM" * 512
    tree.cartridge("gba", "Zelda.gba", content=content)
    tree.cartridge("gba/backup", "Zelda.gba", content=content)
    tree.bios()                        # bios/scph1001.bin
    tree.disc_folder("psx", "FF7")     # psx/FF7.bin (17MB sparse) + psx/FF7.cue
    return tree


# --------------------------------------------------------------------------- #
# Required end-to-end: real quarantine run
# --------------------------------------------------------------------------- #

def test_end_to_end_quarantine(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    tree = _dupe_bios_disc_tree(tmp_path)
    src = tree.source
    dest = tmp_path / "dest"

    metrics = run_dedup(_args(src, dest))

    keeper = src / "gba" / "Zelda.gba"
    removal = src / "gba" / "backup" / "Zelda.gba"

    # Keeper preserved with original bytes.
    assert keeper.exists()
    assert keeper.read_bytes() == b"ZELDA_ROM" * 512
    # Removal quarantined, structure preserved.
    assert not removal.exists()
    assert (dest / DEDUP_BACKUP_DIRNAME / "gba" / "backup" / "Zelda.gba").exists()

    # BIOS + disc untouched and never quarantined.
    assert (src / "bios" / "scph1001.bin").exists()
    assert (src / "psx" / "FF7.bin").exists()
    assert (src / "psx" / "FF7.cue").exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME / "bios").exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME / "psx").exists()

    assert metrics.files_removed == 1
    assert metrics.groups_found == 1
    # Plan + hash index + report were written.
    assert (dest / DEDUP_PLAN_FILENAME).exists()
    assert (dest / HASH_INDEX_FILENAME).exists()
    assert (dest / "rom_stuffer_report.txt").exists()


# --------------------------------------------------------------------------- #
# Invariant 5 -- BIOS / disc images are never members of a duplicate group
# --------------------------------------------------------------------------- #

def test_invariant5_bios_disc_never_removed(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    # Make the BIOS and disc .bin share content with a real cartridge dupe, to
    # prove the guard (not mere content difference) keeps them out of a group.
    same = b"IDENTICAL" * 300
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=same)
    tree.cartridge("gba/dupes", "game.gba", content=same)
    tree.bios(name="bios.bin")            # bios/bios.bin
    # a psx disc .bin with the same bytes (guarded by the psx folder name)
    tree.cartridge("psx", "disc.bin", content=same)
    src = tree.source
    dest = tmp_path / "dest"

    # Detection itself must exclude the BIOS + disc bin.
    groups, skipped = detect_duplicates(DedupOptions(source=src, dest=dest))
    all_group_paths = [p for members in groups.values() for p in members]
    assert not any("bios" in p.parts for p in all_group_paths)
    assert not any(p.name == "disc.bin" for p in all_group_paths)

    run_dedup(_args(src, dest))
    # After a real run: BIOS + disc still present, never quarantined.
    assert (src / "bios" / "bios.bin").exists()
    assert (src / "psx" / "disc.bin").exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME / "bios").exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME / "psx").exists()


# --------------------------------------------------------------------------- #
# Invariant 3 -- dry-run (preview) removes nothing
# --------------------------------------------------------------------------- #

def test_invariant3_dry_run_removes_nothing(tmp_path, monkeypatch):
    # No prompt injection: dry-run must never reach the interactive review.
    tree = _dupe_bios_disc_tree(tmp_path)
    src = tree.source
    dest = tmp_path / "dest"

    before = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
    metrics = run_dedup(_args(src, dest, dry_run=True))
    after = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())

    assert before == after                              # nothing moved/deleted
    assert not (dest / DEDUP_BACKUP_DIRNAME).exists()   # no quarantine created
    assert metrics.dry_run is True
    assert metrics.files_removed == 1                   # counted what WOULD go
    # The plan is still produced (preview artifact).
    assert (dest / DEDUP_PLAN_FILENAME).exists()


# --------------------------------------------------------------------------- #
# Invariant 3 -- quitting the review removes nothing
# --------------------------------------------------------------------------- #

def test_invariant3_quit_removes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "Prompt", FakePrompt(["q"]))
    tree = _dupe_bios_disc_tree(tmp_path)
    src = tree.source
    dest = tmp_path / "dest"

    with pytest.raises(SystemExit) as exc:
        run_dedup(_args(src, dest))
    assert exc.value.code == 0

    # Nothing removed.
    assert (src / "gba" / "backup" / "Zelda.gba").exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME).exists()


# --------------------------------------------------------------------------- #
# hard-delete via the orchestrator
# --------------------------------------------------------------------------- #

def test_run_dedup_hard_delete(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    tree = RomTree(tmp_path / "src")
    content = b"ROM" * 400
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/dupes", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    run_dedup(_args(src, dest, hard_delete=True))

    assert (src / "gba" / "game.gba").exists()
    assert not (src / "gba" / "dupes" / "game.gba").exists()
    assert not (dest / DEDUP_BACKUP_DIRNAME).exists()  # deleted, not quarantined


# --------------------------------------------------------------------------- #
# No duplicates -> zero groups, nothing removed
# --------------------------------------------------------------------------- #

def test_run_dedup_no_duplicates(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "a.gba", seed=0x11)
    tree.cartridge("gba", "b.gba", seed=0x22)
    src = tree.source
    dest = tmp_path / "dest"

    metrics = run_dedup(_args(src, dest))
    assert metrics.groups_found == 0
    assert metrics.files_removed == 0


# --------------------------------------------------------------------------- #
# --apply-plan applies a previously saved plan without re-detecting
# --------------------------------------------------------------------------- #

def test_run_dedup_apply_saved_plan(tmp_path, monkeypatch):
    tree = RomTree(tmp_path / "src")
    content = b"SAVED" * 300
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/backup", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"
    dest.mkdir()

    opts = DedupOptions(source=src, dest=dest)
    groups, _ = detect_duplicates(opts)
    plan = build_plan(groups, opts)
    save_plan(plan, dest)

    # Applying a saved plan does not prompt (no review) and does not re-scan.
    def _boom(*a, **k):
        raise AssertionError("detect_duplicates should not run for --apply-plan")

    monkeypatch.setattr("rom_stuffer.dedup.detect_duplicates", _boom)
    metrics = run_dedup(_args(src, dest, apply_plan=str(dest)))

    assert metrics.files_removed == 1
    assert (src / "gba" / "game.gba").exists()
    assert not (src / "gba" / "backup" / "game.gba").exists()
    assert (dest / DEDUP_BACKUP_DIRNAME / "gba" / "backup" / "game.gba").exists()


# --------------------------------------------------------------------------- #
# Missing source is reported, not raised
# --------------------------------------------------------------------------- #

def test_run_dedup_missing_source(tmp_path):
    metrics = run_dedup(_args(tmp_path / "nope", tmp_path / "dest"))
    assert metrics.files_removed == 0
    assert metrics.groups_found == 0


# --------------------------------------------------------------------------- #
# --protect keeps the protected copy (keeper selection wired through)
# --------------------------------------------------------------------------- #

def test_run_dedup_protect_keeps_protected(tmp_path, monkeypatch):
    _accept_all(monkeypatch)
    content = b"PROT" * 300
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("golden", "game.gba", content=content)
    src = tree.source
    dest = tmp_path / "dest"

    run_dedup(_args(src, dest, protect=["golden"]))

    # The protected copy is the keeper; the other is quarantined.
    assert (src / "golden" / "game.gba").exists()
    assert not (src / "gba" / "game.gba").exists()
    assert (dest / DEDUP_BACKUP_DIRNAME / "gba" / "game.gba").exists()
