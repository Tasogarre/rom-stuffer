"""Tests for rom_stuffer/sync.py — the SD-card mirror engine.

All tests call mirror_to_sdcard() directly (no subprocess) and use
pytest's tmp_path for both the fake source library and the fake SD dir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rom_stuffer.sync import SyncOptions, SyncMetrics, mirror_to_sdcard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(path: Path, content: bytes) -> Path:
    """Create a file (including parent dirs) with the given binary content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# Test: copies new files and preserves subdir structure
# ---------------------------------------------------------------------------

def test_copies_new_files_and_preserves_subdir(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"
    sdcard.mkdir()

    _make_file(source / "gb" / "Game.zip", b"X" * 100)

    opts = SyncOptions(source=source, sdcard=sdcard)
    metrics = mirror_to_sdcard(opts)

    dest_file = sdcard / "gb" / "Game.zip"
    assert dest_file.exists(), "copied file should exist on SD"
    assert dest_file.read_bytes() == b"X" * 100, "contents should match"
    assert metrics.files_copied == 1
    assert metrics.bytes_copied == 100
    assert metrics.files_skipped == 0


# ---------------------------------------------------------------------------
# Test: skips a file already identical (same size) on the card
# ---------------------------------------------------------------------------

def test_skips_already_identical_file(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"

    data = b"A" * 256
    _make_file(source / "gba" / "Mario.zip", data)
    # Pre-populate SD with an identical-size copy.
    _make_file(sdcard / "gba" / "Mario.zip", data)

    opts = SyncOptions(source=source, sdcard=sdcard)
    metrics = mirror_to_sdcard(opts)

    assert metrics.files_skipped == 1
    assert metrics.files_copied == 0


# ---------------------------------------------------------------------------
# Test: re-copies when the card file has a different size
# ---------------------------------------------------------------------------

def test_recopies_when_size_differs(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"

    _make_file(source / "snes" / "Zelda.zip", b"NEW" * 100)
    # Stale version with different size.
    _make_file(sdcard / "snes" / "Zelda.zip", b"OLD" * 50)

    opts = SyncOptions(source=source, sdcard=sdcard)
    metrics = mirror_to_sdcard(opts)

    assert metrics.files_copied == 1
    assert metrics.files_skipped == 0
    assert (sdcard / "snes" / "Zelda.zip").read_bytes() == b"NEW" * 100


# ---------------------------------------------------------------------------
# Test: prune=True deletes a card file with no local counterpart
# ---------------------------------------------------------------------------

def test_prune_removes_orphan(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"

    _make_file(source / "gb" / "Tetris.zip", b"T" * 50)
    # Extra file on card that does not exist in source.
    orphan = _make_file(sdcard / "gb" / "OldGame.zip", b"O" * 50)

    opts = SyncOptions(source=source, sdcard=sdcard, prune=True)
    metrics = mirror_to_sdcard(opts)

    assert not orphan.exists(), "orphan should be pruned"
    assert metrics.files_pruned == 1
    assert metrics.bytes_pruned == 50


# ---------------------------------------------------------------------------
# Test: prune=False leaves extra card files in place
# ---------------------------------------------------------------------------

def test_no_prune_leaves_orphan(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"

    _make_file(source / "gb" / "Tetris.zip", b"T" * 50)
    extra = _make_file(sdcard / "gb" / "OldGame.zip", b"O" * 50)

    opts = SyncOptions(source=source, sdcard=sdcard, prune=False)
    metrics = mirror_to_sdcard(opts)

    assert extra.exists(), "extra file should remain when prune=False"
    assert metrics.files_pruned == 0


# ---------------------------------------------------------------------------
# Test: dry_run=True changes nothing on disk but counts are populated
# ---------------------------------------------------------------------------

def test_dry_run_no_disk_changes(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"
    sdcard.mkdir()

    _make_file(source / "nes" / "Mario.zip", b"N" * 200)
    # Orphan on card that would be pruned in a real run.
    orphan = _make_file(sdcard / "nes" / "Orphan.zip", b"X" * 80)

    opts = SyncOptions(source=source, sdcard=sdcard, dry_run=True, prune=True)
    metrics = mirror_to_sdcard(opts)

    # Nothing should have been copied.
    assert not (sdcard / "nes" / "Mario.zip").exists(), "dry_run must not copy files"
    # Orphan must still exist.
    assert orphan.exists(), "dry_run must not delete files"

    # Counts must reflect what would have happened.
    assert metrics.files_copied == 1
    assert metrics.bytes_copied == 200
    assert metrics.files_pruned == 1
    assert metrics.bytes_pruned == 80
    assert metrics.dry_run is True


# ---------------------------------------------------------------------------
# Test: SAFETY — empty source + prune=True → no deletions, flag set
# ---------------------------------------------------------------------------

def test_safety_empty_source_blocks_prune(tmp_path):
    source = tmp_path / "source"
    source.mkdir()  # Exists but has no files.
    sdcard = tmp_path / "sdcard"

    card_file = _make_file(sdcard / "gb" / "Precious.zip", b"P" * 128)

    opts = SyncOptions(source=source, sdcard=sdcard, prune=True)
    metrics = mirror_to_sdcard(opts)

    assert card_file.exists(), "card file must NOT be deleted when source is empty"
    assert metrics.files_pruned == 0
    assert metrics.prune_blocked_empty_source is True


# ---------------------------------------------------------------------------
# Test: byte totals are correct for a known-size file
# ---------------------------------------------------------------------------

def test_byte_totals_correct(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"
    sdcard.mkdir()

    file_size = 1337
    _make_file(source / "gba" / "Metroid.zip", b"M" * file_size)

    opts = SyncOptions(source=source, sdcard=sdcard)
    metrics = mirror_to_sdcard(opts)

    assert metrics.files_copied == 1
    assert metrics.bytes_copied == file_size


# ---------------------------------------------------------------------------
# Test: multiple files across subdirs — all copied, byte total is sum
# ---------------------------------------------------------------------------

def test_multiple_files_total_bytes(tmp_path):
    source = tmp_path / "source"
    sdcard = tmp_path / "sdcard"
    sdcard.mkdir()

    _make_file(source / "gb" / "A.zip", b"a" * 100)
    _make_file(source / "gba" / "B.zip", b"b" * 200)
    _make_file(source / "snes" / "C.zip", b"c" * 300)

    opts = SyncOptions(source=source, sdcard=sdcard)
    metrics = mirror_to_sdcard(opts)

    assert metrics.files_copied == 3
    assert metrics.bytes_copied == 600
    assert metrics.files_skipped == 0
