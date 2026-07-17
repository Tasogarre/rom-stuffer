"""Reusable helpers for building synthetic ROM directory trees.

Provides:
- ``rom_bytes(size, seed)``  -- deterministic ROM content
- ``make_zip(dest, rom_name, content)``  -- write a real single-entry ZIP
- ``RomTree``  -- fluent builder for configurable source trees
- ``rom_tree`` fixture  -- yields a fresh RomTree in tmp_path
- ``simple_cartridge_tree`` fixture  -- a ready-made multi-system tree

Usage in tests::

    def test_something(tmp_path):
        tree = RomTree(tmp_path / "source")
        tree.cartridge("megadrive", "Sonic.bin")
        tree.disc_folder("psx", "FF7 Disc1")
        # ...
        rs.compress_roms(str(tree.source), ...)

Duplicate sets for future dedup tests::

    tree.duplicate_pair("snes", "Zelda.sfc", "snes/backup", "Zelda_copy.sfc")
    raw_path, zip_path = tree.zip_pair("gb", "Tetris.gb")
    tree.unicode_rom()   # Pokémon Red.gb
    tree.bracket_rom()   # Zelda (U) [!].gb
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Byte-level helpers
# ---------------------------------------------------------------------------

def rom_bytes(size: int = 64, seed: int = 0xAA) -> bytes:
    """Return deterministic ROM content: *size* bytes all equal to *seed* & 0xFF."""
    return bytes([seed & 0xFF] * size)


def make_zip(dest: Path, rom_name: str, content: bytes) -> Path:
    """Write a single-entry DEFLATE ZIP to *dest* and return the path.

    The archive entry is named *rom_name* and contains *content*.
    Parent directories are created as needed.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(rom_name, content)
    return dest


# ---------------------------------------------------------------------------
# RomTree: fluent builder
# ---------------------------------------------------------------------------

class RomTree:
    """Fluent builder for synthetic ROM directory trees.

    Maintains a list of every file created so tests can reference them.
    The *source* property returns the root directory to pass to compress_roms().
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._files: list[Path] = []

    # ---------------------------------------------------------------- source

    @property
    def source(self) -> Path:
        return self.root

    # --------------------------------------------------------- cartridge ROMs

    def cartridge(
        self,
        folder: str,
        name: str,
        content: bytes | None = None,
        size: int = 64,
        seed: int = 0xAA,
    ) -> "RomTree":
        """Add a single cartridge ROM file under *root/folder/name*."""
        if content is None:
            content = rom_bytes(size, seed)
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self._files.append(path)
        return self

    def cartridges(
        self,
        folder: str,
        ext: str,
        names: list[str],
        content: bytes | None = None,
    ) -> "RomTree":
        """Add multiple cartridge ROMs with the same extension in *folder*."""
        for i, stem in enumerate(names):
            c = content if content is not None else rom_bytes(64, seed=i)
            self.cartridge(folder, f"{stem}{ext}", content=c)
        return self

    # ----------------------------------------------------- disc / CD folders

    def disc_folder(
        self,
        system: str,
        basename: str = "Track01",
        descriptor: str = ".cue",
    ) -> "RomTree":
        """Add a disc-image folder: a .bin track + a descriptor (.cue/.gdi).

        The .bin is sized to 17 MB (above CARTRIDGE_BIN_MAX_BYTES) to trigger
        the size guard even if the folder name check somehow misses it.
        """
        folder = self.root / system
        folder.mkdir(parents=True, exist_ok=True)

        # Sparse-write the bin to avoid allocating 17 MB in RAM.
        bin_path = folder / f"{basename}.bin"
        size = 17 * 1024 * 1024
        with open(bin_path, "wb") as fh:
            fh.seek(size - 1)
            fh.write(b"\x00")

        desc_path = folder / f"{basename}{descriptor}"
        desc_path.write_text(
            f'FILE "{basename}.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
        )
        self._files.extend([bin_path, desc_path])
        return self

    # ------------------------------------------------------------------ BIOS

    def bios(self, name: str = "scph1001.bin", ext_override: str | None = None) -> "RomTree":
        """Add a file inside *bios/* — refused regardless of extension."""
        actual_name = name if ext_override is None else Path(name).stem + ext_override
        path = self.root / "bios" / actual_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rom_bytes(512 * 1024, seed=0xB1))
        self._files.append(path)
        return self

    # ---------------------------------------------------------- oversized bin

    def oversized_bin(
        self,
        folder: str = "unknown",
        name: str = "BigGame.bin",
        size: int | None = None,
    ) -> "RomTree":
        """Add a .bin file just above CARTRIDGE_BIN_MAX_BYTES in a neutral folder.

        The file is sparse-written so it doesn't consume the full size in RAM.
        """
        import compress_roms as _rs
        if size is None:
            size = _rs.CARTRIDGE_BIN_MAX_BYTES + 1
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            fh.seek(size - 1)
            fh.write(b"\x00")
        self._files.append(path)
        return self

    # ---------------------------------------------------------- duplicate sets

    def duplicate_pair(
        self,
        folder1: str,
        name1: str,
        folder2: str,
        name2: str,
        content: bytes | None = None,
    ) -> "RomTree":
        """Add two files with byte-identical content in different locations.

        Used to seed future dedup tests: same content, different name/path.
        """
        if content is None:
            content = rom_bytes(128, seed=0xDD)
        self.cartridge(folder1, name1, content=content)
        self.cartridge(folder2, name2, content=content)
        return self

    def zip_pair(
        self,
        folder: str,
        raw_name: str,
        zip_name: str | None = None,
        content: bytes | None = None,
    ) -> tuple[Path, Path]:
        """Add a raw ROM and a ZIP of the same logical content side by side.

        Returns ``(raw_path, zip_path)``. Used to seed dedup tests that must
        recognise a raw file and its zip as the same logical ROM.
        """
        if content is None:
            content = rom_bytes(128, seed=0xEE)
        if zip_name is None:
            # A zip file named the same as the raw file (with an extra .zip suffix)
            # is what compress_roms itself would produce, so use that convention.
            zip_name = Path(raw_name).stem + ".zip"

        raw_path = self.root / folder / raw_name
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(content)

        zip_path = self.root / folder / zip_name
        make_zip(zip_path, raw_name, content)

        self._files.extend([raw_path, zip_path])
        return raw_path, zip_path

    # ------------------------------------------------ special / edge filenames

    def unicode_rom(self, folder: str = "gb", ext: str = ".gb") -> Path:
        """Add a ROM whose filename contains a non-ASCII character (Pokémon).

        Returns the Path to the created file.
        """
        name = f"Pokémon Red{ext}"
        self.cartridge(folder, name, seed=0x50)
        return self.root / folder / name

    def bracket_rom(self, folder: str = "gb", ext: str = ".gb") -> Path:
        """Add a ROM with bracket/parenthesis-style No-Intro naming.

        Returns the Path to the created file.
        """
        name = f"Zelda (U) [!]{ext}"
        self.cartridge(folder, name, seed=0x5A)
        return self.root / folder / name

    # --------------------------------------------------------------- listing

    @property
    def files(self) -> list[Path]:
        """All paths created by this builder, in insertion order."""
        return list(self._files)


# ---------------------------------------------------------------------------
# Convenience fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rom_tree(tmp_path):
    """Yield a RomTree rooted in a fresh temporary directory."""
    return RomTree(tmp_path / "roms")


@pytest.fixture
def simple_cartridge_tree(tmp_path):
    """A ready-made tree with a few cartridge ROMs across systems.

    Systems: megadrive (.bin), snes (.sfc), gb (.gb).
    Each file has distinct content so hash-based tests don't see false dupes.
    """
    tree = RomTree(tmp_path / "roms")
    tree.cartridge("megadrive", "Sonic.bin", seed=0x01)
    tree.cartridge("snes", "Zelda.sfc", seed=0x02)
    tree.cartridge("nintendo/gb", "Tetris.gb", seed=0x03)
    return tree
