"""Phase-2 estimator tests (rom_stuffer/estimate.py).

Uses ``realistic_library`` (helpers) whose sizes are fixed, so every per-system and
grand-total number below is hand-computed from the module constants.

The library (compress ratio 0.4):

    megadrive/  Sonic.md 100000, Sonic2.md 120000, Shared.md 90000   (3 raw)
    gb/         Tetris.gb 50000, Tetris_copy.gb 50000, Shared.gb 90000 (3 raw)
    snes/       Zelda.sfc 200000 (raw), Mario.zip <logical 80000>      (1 raw + 1 zip)
    bios/       scph1001.bin            -> EXCLUDED
    dreamcast/  Track01.bin (17 MB)+cue -> EXCLUDED

Duplicate pairs (grouped regardless of per_system, because every system folder
holds >= 2 candidate files so none are pre-filtered out):
    - gb/Tetris.gb == gb/Tetris_copy.gb  -> keeper Tetris.gb, remove Tetris_copy.gb (gb)
    - megadrive/Shared.md == gb/Shared.gb -> keeper gb/Shared.gb (alphabetical),
      remove megadrive/Shared.md (megadrive)
"""
from __future__ import annotations

from pathlib import Path

import rom_stuffer.estimate as estimate
from rom_stuffer.estimate import estimate_library, render_estimate
from helpers import (
    REALISTIC_COMPRESS_RATIO,
    RomTree,
    realistic_library,
    rom_bytes,
)


def _by_system(est) -> dict:
    return {s.system: s for s in est.systems}


def _mario_zip_size(tree: RomTree) -> int:
    return (tree.source / "snes" / "Mario.zip").stat().st_size


# --------------------------------------------------------------------------- #
# Per-system decompressed / compressed / file-count numbers
# --------------------------------------------------------------------------- #

def test_per_system_sizes(tmp_path):
    tree = realistic_library(tmp_path)
    mz = _mario_zip_size(tree)

    est = estimate_library(tree.source)
    sysmap = _by_system(est)

    # Only cartridge systems -- BIOS and disc folders never become a system.
    assert set(sysmap) == {"megadrive", "gb", "snes"}

    mega = sysmap["megadrive"]
    assert mega.file_count == 3
    assert mega.decompressed_bytes == 310_000
    assert mega.compressed_bytes == 124_000            # 40000 + 48000 + 36000

    gb = sysmap["gb"]
    assert gb.file_count == 3
    assert gb.decompressed_bytes == 190_000
    assert gb.compressed_bytes == 76_000               # 20000 + 20000 + 36000

    snes = sysmap["snes"]
    assert snes.file_count == 2
    assert snes.decompressed_bytes == 280_000          # 200000 + 80000
    assert snes.compressed_bytes == 80_000 + mz        # raw est + zip on-disk size


# --------------------------------------------------------------------------- #
# Dedup attribution: reclaimable bytes land in the removed copy's system
# --------------------------------------------------------------------------- #

def test_dedup_reclaimable_per_system(tmp_path):
    tree = realistic_library(tmp_path)
    est = estimate_library(tree.source)
    sysmap = _by_system(est)

    # Tetris_copy.gb removed -> its compressed 20000 reclaimable in gb.
    assert sysmap["gb"].dedup_removable_bytes == 20_000
    # megadrive/Shared.md removed -> its compressed 36000 reclaimable in megadrive.
    assert sysmap["megadrive"].dedup_removable_bytes == 36_000
    assert sysmap["snes"].dedup_removable_bytes == 0

    # final = compressed - reclaimable
    assert sysmap["gb"].final_bytes == 56_000          # 76000 - 20000
    assert sysmap["megadrive"].final_bytes == 88_000   # 124000 - 36000
    assert sysmap["snes"].final_bytes == sysmap["snes"].compressed_bytes


# --------------------------------------------------------------------------- #
# Grand totals
# --------------------------------------------------------------------------- #

def test_grand_totals(tmp_path):
    tree = realistic_library(tmp_path)
    mz = _mario_zip_size(tree)
    est = estimate_library(tree.source)

    assert est.total_file_count == 8
    assert est.total_decompressed == 780_000
    assert est.total_compressed == 280_000 + mz
    assert est.total_dedup_removable == 56_000
    assert est.total_final == 224_000 + mz


# --------------------------------------------------------------------------- #
# BIOS / disc excluded from every number
# --------------------------------------------------------------------------- #

def test_bios_and_disc_excluded(tmp_path):
    tree = realistic_library(tmp_path)
    est = estimate_library(tree.source)

    names = {s.system for s in est.systems}
    assert "bios" not in names
    assert "dreamcast" not in names
    # 8 counted files == the two-system carts + snes pair; the 17 MB disc .bin
    # never inflates any byte total.
    assert est.total_file_count == 8
    assert est.total_decompressed == 780_000

    reasons = " ".join(s["reason"] for s in est.skipped).lower()
    assert "bios" in reasons
    assert "disc" in reasons


# --------------------------------------------------------------------------- #
# A library with no duplicates reports zero reclaimable
# --------------------------------------------------------------------------- #

def test_no_duplicates_zero_reclaimable(tmp_path):
    tree = RomTree(tmp_path / "unique")
    tree.cartridge("gb", "A.gb", content=rom_bytes(1000, seed=0x01))
    tree.cartridge("gb", "B.gb", content=rom_bytes(2000, seed=0x02))
    tree.cartridge("snes", "C.sfc", content=rom_bytes(3000, seed=0x03))

    est = estimate_library(tree.source)
    assert est.total_dedup_removable == 0
    assert all(s.dedup_removable_bytes == 0 for s in est.systems)
    assert all(s.final_bytes == s.compressed_bytes for s in est.systems)


# --------------------------------------------------------------------------- #
# progress_callback is invoked
# --------------------------------------------------------------------------- #

def test_progress_callback_invoked(tmp_path):
    tree = realistic_library(tmp_path)
    calls: list[tuple] = []

    estimate_library(
        tree.source,
        progress_callback=lambda stage, cur, total: calls.append((stage, cur, total)),
    )
    assert calls, "progress_callback should be invoked during detection"
    for stage, cur, total in calls:
        assert isinstance(stage, str)
        assert isinstance(cur, int)
        assert isinstance(total, int)


# --------------------------------------------------------------------------- #
# An unreadable file is skipped, not fatal
# --------------------------------------------------------------------------- #

def test_unreadable_file_skipped_not_fatal(tmp_path, monkeypatch):
    tree = RomTree(tmp_path / "flaky")
    tree.cartridge("gb", "Good.gb", content=rom_bytes(1000, seed=0x01))
    tree.cartridge("gb", "Broken.gb", content=rom_bytes(2000, seed=0x02))

    real_logical_size = estimate.logical_size

    def _flaky(path: Path) -> int:
        if path.name == "Broken.gb":
            raise OSError("simulated unreadable file")
        return real_logical_size(path)

    # Patch only the estimator's copy; detection keeps its own working logical_size.
    monkeypatch.setattr(estimate, "logical_size", _flaky)

    est = estimate_library(tree.source)  # must not raise

    sysmap = _by_system(est)
    assert sysmap["gb"].file_count == 1                 # only Good.gb counted
    assert sysmap["gb"].decompressed_bytes == 1000
    skipped_names = {s["file"] for s in est.skipped}
    assert "Broken.gb" in skipped_names


# --------------------------------------------------------------------------- #
# The estimator never modifies the source tree
# --------------------------------------------------------------------------- #

def _snapshot(root: Path) -> dict:
    snap = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        snap[rel] = ("dir" if p.is_dir() else p.stat().st_size)
    return snap


def test_source_tree_unchanged(tmp_path):
    tree = realistic_library(tmp_path)
    before = _snapshot(tree.source)

    estimate_library(tree.source)

    after = _snapshot(tree.source)
    assert after == before
    # No dedup quarantine / backup dir was created under source.
    assert not (tree.source / "dedup_backup").exists()


# --------------------------------------------------------------------------- #
# render_estimate smoke test (headline + table render without error)
# --------------------------------------------------------------------------- #

def test_render_estimate_smoke(tmp_path):
    tree = realistic_library(tmp_path)
    est = estimate_library(tree.source)

    # Use the themed shared console (semantic styles like "brand" are registered on
    # it at import) and capture its output.
    from rom_stuffer.tui import console as tui_console

    with tui_console.capture() as cap:
        render_estimate(est)  # console=None -> the themed tui console
    out = cap.get()

    assert "on SD" in out
    assert "smaller" in out
    assert "TOTAL" in out
