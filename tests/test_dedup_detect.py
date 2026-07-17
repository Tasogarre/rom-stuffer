"""U4 tests: duplicate detection pipeline + BIOS/disc safety invariant."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import rom_stuffer.dedup as dedup
from rom_stuffer.dedup import DedupOptions, detect_duplicates
from helpers import make_zip, RomTree


def _opts(src: Path, **kw) -> DedupOptions:
    return DedupOptions(source=src, dest=src.parent / "dest", **kw)


# --------------------------------------------------------------------------- #
# T4.1 -- raw + raw identical files grouped
# --------------------------------------------------------------------------- #

def test_raw_raw_identical_grouped(tmp_path):
    content = b"GBA_ROM_CONTENT" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/backup", "game.gba", content=content)

    groups, skipped = detect_duplicates(_opts(tree.source))
    assert len(groups) == 1
    (members,) = groups.values()
    assert len(members) == 2
    assert all("game.gba" in p.name for p in members)


# --------------------------------------------------------------------------- #
# T4.2 -- raw + zip identical content grouped
# --------------------------------------------------------------------------- #

def test_raw_zip_identical_grouped(tmp_path):
    content = b"MIXED CONTAINER " * 64
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    make_zip(tree.source / "gba" / "game.zip", "game.gba", content)

    groups, skipped = detect_duplicates(_opts(tree.source))
    assert len(groups) == 1
    (members,) = groups.values()
    assert len(members) == 2
    suffixes = sorted(p.suffix for p in members)
    assert suffixes == [".gba", ".zip"]


# --------------------------------------------------------------------------- #
# T4.3 -- zip + zip identical content grouped
# --------------------------------------------------------------------------- #

def test_zip_zip_identical_grouped(tmp_path):
    content = b"ZIP TWINS " * 100
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir(parents=True)
    make_zip(src / "a" / "game.zip", "game.gba", content)
    make_zip(src / "b" / "game.zip", "game.gba", content)

    groups, skipped = detect_duplicates(_opts(src))
    assert len(groups) == 1
    (members,) = groups.values()
    assert len(members) == 2
    assert all(p.suffix == ".zip" for p in members)


# --------------------------------------------------------------------------- #
# T4.4 -- singletons never content-hashed
# --------------------------------------------------------------------------- #

def test_singletons_never_hashed(tmp_path, monkeypatch):
    def _boom(path):
        raise AssertionError(f"content_sha256 must not be called (got {path})")

    monkeypatch.setattr(dedup, "content_sha256", _boom)

    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "a.gba", content=b"AAA" * 100)
    tree.cartridge("snes", "b.smc", content=b"BBB" * 200)

    groups, skipped = detect_duplicates(_opts(tree.source))
    assert groups == {}


# --------------------------------------------------------------------------- #
# T4.5 -- three-way duplicate set
# --------------------------------------------------------------------------- #

def test_three_way_duplicate(tmp_path):
    content = b"TRIPLE" * 512
    tree = RomTree(tmp_path / "src")
    tree.cartridge("a", "game.nes", content=content)
    tree.cartridge("b", "game.nes", content=content)
    tree.cartridge("c", "game.nes", content=content)

    groups, skipped = detect_duplicates(_opts(tree.source))
    assert len(groups) == 1
    (members,) = groups.values()
    assert len(members) == 3


# --------------------------------------------------------------------------- #
# T4.6 -- BIOS never appears
# --------------------------------------------------------------------------- #

def test_bios_and_disc_never_grouped(tmp_path):
    same = b"BIOS" * 128
    tree = RomTree(tmp_path / "src")
    # bios/ file (refused for any extension)
    (tree.source / "bios").mkdir(parents=True)
    (tree.source / "bios" / "scph1001.bin").write_bytes(same)
    # disc-system .bin, identical content
    (tree.source / "psx").mkdir(parents=True)
    (tree.source / "psx" / "game.bin").write_bytes(same)
    # a lone genuine cartridge
    tree.cartridge("gba", "game.gba", content=b"ROM" * 100)

    groups, skipped = detect_duplicates(_opts(tree.source))
    assert groups == {}
    skipped_names = {s["file"] for s in skipped}
    assert "scph1001.bin" in skipped_names
    assert "game.bin" in skipped_names


# --------------------------------------------------------------------------- #
# T4.7 -- unique library yields zero groups (and no hashing)
# --------------------------------------------------------------------------- #

def test_unique_library_zero_groups(tmp_path, monkeypatch):
    def _boom(path):
        raise AssertionError("content_sha256 must not be called for unique sizes")

    monkeypatch.setattr(dedup, "content_sha256", _boom)

    tree = RomTree(tmp_path / "src")
    tree.cartridge("x", "a.gba", content=b"A" * 512)
    tree.cartridge("x", "b.gba", content=b"B" * 511)
    tree.cartridge("x", "c.smc", content=b"C" * 510)

    groups, skipped = detect_duplicates(_opts(tree.source))
    assert groups == {}


# --------------------------------------------------------------------------- #
# T4.8 -- per_system limits comparison
# --------------------------------------------------------------------------- #

def test_per_system_scoping(tmp_path):
    content = b"SAME" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba_backup", "game.gba", content=content)
    tree.cartridge("snes", "other.smc", content=b"SNES" * 256)

    # Without per_system: gba vs gba_backup match across top-level dirs.
    groups, _ = detect_duplicates(_opts(tree.source, per_system=False))
    assert len(groups) == 1

    # With per_system: each top-level dir has only 1 file of that size -> no group.
    groups_ps, _ = detect_duplicates(_opts(tree.source, per_system=True))
    assert groups_ps == {}


def test_per_system_same_folder_still_groups(tmp_path):
    content = b"WITHIN" * 256
    tree = RomTree(tmp_path / "src")
    tree.cartridge("gba", "game.gba", content=content)
    tree.cartridge("gba/dupes", "game.gba", content=content)

    groups, _ = detect_duplicates(_opts(tree.source, per_system=True))
    assert len(groups) == 1


# --------------------------------------------------------------------------- #
# min_size filter
# --------------------------------------------------------------------------- #

def test_min_size_filters_small_duplicates(tmp_path):
    content = b"TINY" * 4  # 16 bytes
    tree = RomTree(tmp_path / "src")
    tree.cartridge("a", "game.gba", content=content)
    tree.cartridge("b", "game.gba", content=content)

    groups, skipped = detect_duplicates(_opts(tree.source, min_size=1024))
    assert groups == {}
    assert any("min-size" in s["reason"].lower() for s in skipped)


# --------------------------------------------------------------------------- #
# ADVERSARIAL: BIOS / disc .bin sharing content with real cartridges never join
# --------------------------------------------------------------------------- #

def test_adversarial_bios_disc_never_join_cartridge_group(tmp_path):
    """A BIOS .bin and a disc-folder .bin carry byte-identical content to two
    genuine cartridge .bin files. Detection must group ONLY the two cartridges
    and never pull in the BIOS or disc image."""
    shared = b"\xAB\xCD" * 4096  # small cartridge-sized payload, identical everywhere
    src = tmp_path / "src"

    # Two genuine cartridge .bin dupes (non-disc folders, small enough).
    (src / "megadrive").mkdir(parents=True)
    (src / "megadrive" / "Sonic.bin").write_bytes(shared)
    (src / "genesis").mkdir(parents=True)
    (src / "genesis" / "Sonic.bin").write_bytes(shared)

    # A BIOS .bin with identical content -- must be refused.
    (src / "bios").mkdir(parents=True)
    (src / "bios" / "boot.bin").write_bytes(shared)

    # A disc-system .bin with identical content -- must be refused.
    (src / "psx").mkdir(parents=True)
    (src / "psx" / "boot.bin").write_bytes(shared)

    groups, skipped = detect_duplicates(_opts(src))

    assert len(groups) == 1
    (members,) = groups.values()
    assert len(members) == 2  # exactly the two cartridges, never 3 or 4
    member_parents = sorted(p.parent.name for p in members)
    assert member_parents == ["genesis", "megadrive"]
    # BIOS and disc images must never appear in any group.
    for group_members in groups.values():
        for p in group_members:
            assert "bios" not in {c.lower() for c in p.parts}
            assert "psx" not in {c.lower() for c in p.parts}
    skipped_names = {s["file"] for s in skipped}
    assert "boot.bin" in skipped_names  # both refused boot.bin files recorded
