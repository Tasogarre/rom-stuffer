"""Tests for build_zip_path: the zip-name collision guard.

Verifies three behaviours:
  1. Same stem, different extensions in the same folder → distinct zip names.
  2. A pre-existing .zip on disk is not clobbered (build_zip_path disambiguates).
  3. The same stem in different folders each gets its own Game.zip with no
     cross-folder interference from the shared ``claimed`` set.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import compress_roms as rs


# ---------------------------------------------------------------------------
# 1. Same stem, different extensions in the same folder
# ---------------------------------------------------------------------------

class TestSameStemDifferentExt:

    def test_first_file_gets_plain_zip(self, tmp_path):
        gb = tmp_path / "Game.gb"
        gb.write_bytes(b"\x00" * 64)
        claimed: set[Path] = set()
        assert rs.build_zip_path(gb, claimed) == tmp_path / "Game.zip"

    def test_second_file_gets_ext_suffix(self, tmp_path):
        """Game.gb → Game.zip; Game.gbc in the same folder → Game_gbc.zip."""
        gb = tmp_path / "Game.gb"
        gbc = tmp_path / "Game.gbc"
        gb.write_bytes(b"\x00" * 64)
        gbc.write_bytes(b"\x01" * 64)
        claimed: set[Path] = set()
        zip_gb = rs.build_zip_path(gb, claimed)
        zip_gbc = rs.build_zip_path(gbc, claimed)
        assert zip_gb == tmp_path / "Game.zip"
        assert zip_gbc == tmp_path / "Game_gbc.zip"

    def test_both_zips_are_distinct(self, tmp_path):
        """The two returned paths must never be equal (data-loss prevention)."""
        gb = tmp_path / "Game.gb"
        gbc = tmp_path / "Game.gbc"
        gb.write_bytes(b"\x00" * 64)
        gbc.write_bytes(b"\x01" * 64)
        claimed: set[Path] = set()
        zip1 = rs.build_zip_path(gb, claimed)
        zip2 = rs.build_zip_path(gbc, claimed)
        assert zip1 != zip2

    def test_three_same_stem_all_distinct(self, tmp_path):
        """Three same-stem files (.gb, .gbc, .gba) each get a unique zip name."""
        claimed: set[Path] = set()
        files = [tmp_path / f"Game{ext}" for ext in [".gb", ".gbc", ".gba"]]
        for f in files:
            f.write_bytes(b"\x00" * 64)
        zips = [rs.build_zip_path(f, claimed) for f in files]
        assert len(set(zips)) == 3, "all three zip names must differ"

    def test_claimed_set_updated_in_place(self, tmp_path):
        """build_zip_path must add every chosen path to *claimed*."""
        gb = tmp_path / "Game.gb"
        gb.write_bytes(b"\x00" * 64)
        claimed: set[Path] = set()
        result = rs.build_zip_path(gb, claimed)
        assert result in claimed


# ---------------------------------------------------------------------------
# 2. Pre-existing .zip must not be clobbered
# ---------------------------------------------------------------------------

class TestPreexistingZip:

    def test_existing_zip_triggers_fallback(self, tmp_path):
        """If Game.zip already exists, the next file for that stem is disambiguated."""
        existing = tmp_path / "Game.zip"
        existing.write_bytes(b"original content")
        gbc = tmp_path / "Game.gbc"
        gbc.write_bytes(b"\x01" * 64)
        claimed: set[Path] = set()
        zip_path = rs.build_zip_path(gbc, claimed)
        assert zip_path != existing
        assert zip_path == tmp_path / "Game_gbc.zip"

    def test_existing_zip_bytes_unchanged(self, tmp_path):
        """build_zip_path is read-only — it must not write or truncate any file."""
        original = b"must not be overwritten"
        existing = tmp_path / "Game.zip"
        existing.write_bytes(original)
        gb = tmp_path / "Game.gb"
        gb.write_bytes(b"\x00" * 64)
        claimed: set[Path] = set()
        rs.build_zip_path(gb, claimed)
        assert existing.read_bytes() == original

    def test_claimed_zip_also_triggers_fallback(self, tmp_path):
        """A zip claimed in-session (not on disk) is treated as taken."""
        gb = tmp_path / "Game.gb"
        gbc = tmp_path / "Game.gbc"
        gb.write_bytes(b"\x00" * 64)
        gbc.write_bytes(b"\x01" * 64)
        claimed: set[Path] = set()
        # Claim Game.zip first (as if gb was already processed)
        rs.build_zip_path(gb, claimed)
        # Now gbc must not get Game.zip (already in claimed, even if not on disk)
        zip_gbc = rs.build_zip_path(gbc, claimed)
        assert zip_gbc != tmp_path / "Game.zip"


# ---------------------------------------------------------------------------
# 3. Same stem in different folders — no cross-folder interference
# ---------------------------------------------------------------------------

class TestDifferentFolders:

    def test_each_folder_gets_own_game_zip(self, tmp_path):
        """Claiming folder_a/Game.zip must not block folder_b/Game.zip."""
        folder_a = tmp_path / "snes"
        folder_b = tmp_path / "gb"
        folder_a.mkdir()
        folder_b.mkdir()
        (folder_a / "Game.sfc").write_bytes(b"\x00" * 64)
        (folder_b / "Game.gb").write_bytes(b"\x01" * 64)
        claimed: set[Path] = set()
        zip_a = rs.build_zip_path(folder_a / "Game.sfc", claimed)
        zip_b = rs.build_zip_path(folder_b / "Game.gb", claimed)
        assert zip_a == folder_a / "Game.zip"
        assert zip_b == folder_b / "Game.zip"
        # Different folders so the paths differ even though stems match
        assert zip_a != zip_b

    def test_three_folders_all_independent(self, tmp_path):
        """Same stem across three folders — each gets its own plain zip."""
        systems = ["megadrive", "snes", "gb"]
        claimed: set[Path] = set()
        zips = []
        for sys in systems:
            folder = tmp_path / sys
            folder.mkdir()
            rom = folder / "Game.bin"
            rom.write_bytes(b"\x00" * 64)
            zips.append(rs.build_zip_path(rom, claimed))
        assert zips[0] == tmp_path / "megadrive" / "Game.zip"
        assert zips[1] == tmp_path / "snes" / "Game.zip"
        assert zips[2] == tmp_path / "gb" / "Game.zip"
        # All paths are distinct
        assert len(set(zips)) == 3
