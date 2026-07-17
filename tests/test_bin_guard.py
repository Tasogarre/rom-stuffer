"""Tests for the disc-image / BIOS guard (exclusion_reason).

Covers:
- Cartridge .bin files that MUST be kept (megadrive, genesis, mastersystem, atari2600)
- Disc-system folders that REFUSE .bin (psx, ps2, dreamcast, saturn, gamecube, wii,
  xbox, segacd, pcecd, 3do, jaguarcd, psp)
- Any file in bios/ refused regardless of extension
- Oversized .bin (> CARTRIDGE_BIN_MAX_BYTES) refused
- .cue/.gdi companion in folder refuses the .bin
- Source-path scoping: a source root that contains 'psp' in its own path does NOT
  refuse files inside the source tree.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import compress_roms as rs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check(folder: str, source: Path, *, name: str = "Game.bin", size: int = 64) -> str | None:
    """Call exclusion_reason for a .bin file in *source/folder* at *size* bytes."""
    path = source / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"\x00" * min(size, 64))  # don't allocate huge bytes
    return rs.exclusion_reason(path, ".bin", size, source)


# ---------------------------------------------------------------------------
# 1. Cartridge systems that KEEP .bin
# ---------------------------------------------------------------------------

class TestCartridgeBinKept:

    @pytest.mark.parametrize("folder", [
        "megadrive",
        "genesis",        # common alias
        "mastersystem",
        "sms",            # common alias
        "gamegear",
        "atari2600",
        "atari7800",
        "gg",             # Game Gear alias used by EmulationStation
        "sg1000",
    ])
    def test_cartridge_bin_accepted(self, tmp_path, folder):
        reason = _check(folder, tmp_path / "source")
        assert reason is None, (
            f"Expected .bin in '{folder}' to be accepted, got: {reason}"
        )

    def test_small_bin_in_neutral_folder_accepted(self, tmp_path):
        """A small .bin in an unrecognised folder with no descriptor is accepted."""
        source = tmp_path / "source"
        reason = _check("unknown_system", source, size=64)
        assert reason is None


# ---------------------------------------------------------------------------
# 2. Disc-system folders REFUSE .bin
# ---------------------------------------------------------------------------

class TestDiscSystemFoldersRefuseBin:

    @pytest.mark.parametrize("folder", [
        # Sony
        "psx", "ps1", "psone", "playstation",
        "ps2", "playstation2",
        "psp", "playstationportable",
        # Sega
        "dreamcast", "dc",
        "saturn",
        "segacd", "sega-cd",
        "megacd", "mega-cd",
        # NEC / other optical
        "pcecd", "pce-cd",
        "3do",
        "jaguarcd",
        # Nintendo disc
        "gamecube", "gc",
        "wii",
        # Microsoft
        "xbox",
    ])
    def test_disc_folder_bin_refused(self, tmp_path, folder):
        source = tmp_path / "source"
        reason = _check(folder, source)
        assert reason is not None, (
            f"Expected .bin in disc folder '{folder}' to be refused, but got None"
        )
        assert "disc" in reason.lower() or "folder" in reason.lower(), (
            f"Unexpected refusal reason for '{folder}': {reason}"
        )


# ---------------------------------------------------------------------------
# 3. BIOS folder refuses ANY extension
# ---------------------------------------------------------------------------

class TestBiosFolderGuard:

    def test_bios_bin_refused(self, tmp_path):
        source = tmp_path / "source"
        bios_dir = source / "bios"
        bios_dir.mkdir(parents=True)
        path = bios_dir / "scph1001.bin"
        path.write_bytes(b"\x00" * 512)
        reason = rs.exclusion_reason(path, ".bin", 512, source)
        assert reason is not None
        assert "bios" in reason.lower()

    def test_bios_other_ext_refused(self, tmp_path):
        """Files in bios/ are refused for non-.bin extensions too."""
        source = tmp_path / "source"
        bios_dir = source / "bios"
        bios_dir.mkdir(parents=True)
        path = bios_dir / "firmware.rom"
        path.write_bytes(b"\x00" * 64)
        reason = rs.exclusion_reason(path, ".rom", 64, source)
        assert reason is not None
        assert "bios" in reason.lower()

    def test_bios_gb_file_refused(self, tmp_path):
        """Even a .gb extension in bios/ is refused."""
        source = tmp_path / "source"
        bios_dir = source / "bios"
        bios_dir.mkdir(parents=True)
        path = bios_dir / "boot.gb"
        path.write_bytes(b"\x00" * 64)
        reason = rs.exclusion_reason(path, ".gb", 64, source)
        assert reason is not None
        assert "bios" in reason.lower()

    def test_nested_bios_subfolder_refused(self, tmp_path):
        """Files in a subdirectory of bios/ are also refused."""
        source = tmp_path / "source"
        nested = source / "bios" / "ps1"
        nested.mkdir(parents=True)
        path = nested / "scph5501.bin"
        path.write_bytes(b"\x00" * 512)
        reason = rs.exclusion_reason(path, ".bin", 512, source)
        assert reason is not None
        assert "bios" in reason.lower()


# ---------------------------------------------------------------------------
# 4. Oversized .bin refused
# ---------------------------------------------------------------------------

class TestOversizedBin:

    def test_over_limit_refused(self, tmp_path):
        """A .bin above CARTRIDGE_BIN_MAX_BYTES is treated as a disc image."""
        source = tmp_path / "source"
        folder = source / "unknown"
        folder.mkdir(parents=True)
        path = folder / "BigGame.bin"
        path.write_bytes(b"\x00" * 64)  # actual bytes irrelevant — size is passed in
        size = rs.CARTRIDGE_BIN_MAX_BYTES + 1
        reason = rs.exclusion_reason(path, ".bin", size, source)
        assert reason is not None
        assert "too large" in reason

    def test_at_limit_accepted(self, tmp_path):
        """A .bin at exactly the limit (not over) in a neutral folder is accepted."""
        source = tmp_path / "source"
        folder = source / "unknown"
        folder.mkdir(parents=True)
        path = folder / "AtLimit.bin"
        path.write_bytes(b"\x00" * 64)
        size = rs.CARTRIDGE_BIN_MAX_BYTES
        reason = rs.exclusion_reason(path, ".bin", size, source)
        assert reason is None, f"Exactly at limit should be accepted, got: {reason}"

    def test_below_limit_accepted(self, tmp_path):
        """A small .bin in a neutral folder with no descriptor is accepted."""
        source = tmp_path / "source"
        folder = source / "megadrive"
        folder.mkdir(parents=True)
        path = folder / "Sonic.bin"
        path.write_bytes(b"\x00" * 64)
        reason = rs.exclusion_reason(path, ".bin", 64, source)
        assert reason is None


# ---------------------------------------------------------------------------
# 5. .cue / .gdi companion in folder refuses .bin
# ---------------------------------------------------------------------------

class TestDescriptorCompanion:

    def test_cue_companion_refuses_bin(self, tmp_path):
        """A .cue file in the same folder as .bin → disc image refusal."""
        source = tmp_path / "source"
        folder = source / "unknown_system"
        folder.mkdir(parents=True)

        bin_file = folder / "Game.bin"
        bin_file.write_bytes(b"\x00" * 64)
        cue_file = folder / "Game.cue"
        cue_file.write_text('FILE "Game.bin" BINARY\n  TRACK 01 MODE1/2048\n')

        reason = rs.exclusion_reason(bin_file, ".bin", 64, source)
        assert reason is not None
        assert "descriptor" in reason.lower() or "cue" in reason.lower()

    def test_gdi_companion_refuses_bin(self, tmp_path):
        """.gdi descriptor (Dreamcast) also triggers the guard."""
        source = tmp_path / "source"
        folder = source / "unknown_system"
        folder.mkdir(parents=True)

        bin_file = folder / "Track01.bin"
        bin_file.write_bytes(b"\x00" * 64)
        gdi_file = folder / "disc.gdi"
        gdi_file.write_text("3\n1 0 4 2048 Track01.bin 0\n")

        reason = rs.exclusion_reason(bin_file, ".bin", 64, source)
        assert reason is not None

    def test_no_descriptor_no_refusal(self, tmp_path):
        """Without any descriptor, a small .bin in a neutral folder is accepted."""
        source = tmp_path / "source"
        folder = source / "neutral"
        folder.mkdir(parents=True)
        bin_file = folder / "Game.bin"
        bin_file.write_bytes(b"\x00" * 64)
        reason = rs.exclusion_reason(bin_file, ".bin", 64, source)
        assert reason is None


# ---------------------------------------------------------------------------
# 6. Source-path scoping: source rooted inside a folder named 'psp' is fine
# ---------------------------------------------------------------------------

class TestSourcePathScoping:

    def test_source_under_psp_dir_does_not_exclude_all(self, tmp_path):
        """Source root itself is named 'psp' — files inside are judged by relative path."""
        psp_source = tmp_path / "psp"  # source path contains 'psp' component
        megadrive = psp_source / "megadrive"
        megadrive.mkdir(parents=True)
        bin_file = megadrive / "Sonic.bin"
        bin_file.write_bytes(b"\x00" * 64)

        # With source=psp_source, the relative path is "megadrive/Sonic.bin"
        # parts within source: {'megadrive'} — not a disc folder
        reason = rs.exclusion_reason(bin_file, ".bin", 64, psp_source)
        assert reason is None, (
            "Source rooted inside a 'psp' folder must not exclude cartridge ROMs"
        )

    def test_source_under_bios_parent_does_not_exclude_all(self, tmp_path):
        """Source rooted inside a folder named 'bios' is fine for cartridge ROMs."""
        bios_root = tmp_path / "bios" / "roms"  # parent contains 'bios'
        snes = bios_root / "snes"
        snes.mkdir(parents=True)
        rom = snes / "Zelda.sfc"
        rom.write_bytes(b"\x00" * 64)

        reason = rs.exclusion_reason(rom, ".sfc", 64, bios_root)
        assert reason is None, (
            "A source root that has 'bios' as a parent (not inside source) must not "
            "exclude cartridge ROMs — only folders INSIDE source matter"
        )

    def test_psp_folder_inside_source_still_refused(self, tmp_path):
        """A psp/ sub-folder INSIDE the source tree is still a disc folder."""
        source = tmp_path / "roms"
        psp_inside = source / "psp"
        psp_inside.mkdir(parents=True)
        bin_file = psp_inside / "GameUMD.bin"
        bin_file.write_bytes(b"\x00" * 64)

        reason = rs.exclusion_reason(bin_file, ".bin", 64, source)
        assert reason is not None, "psp/ inside source must still be refused"
