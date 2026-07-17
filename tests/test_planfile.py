"""U6 tests: dedup plan + hash index persistence (save/load, hand edits)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from rom_stuffer.dedup import DedupOptions
from rom_stuffer.hashing import content_sha256
from rom_stuffer.planfile import (
    DEDUP_PLAN_FILENAME,
    HASH_INDEX_FILENAME,
    DedupGroup,
    DedupPlan,
    HashRecord,
    PLAN_VERSION,
    build_hash_index,
    build_plan,
    load_hash_index,
    load_plan,
    save_hash_index,
    save_plan,
)


def _make_files(source: Path, rels: list[str], content: bytes = b"ROM" * 100) -> list[Path]:
    paths = []
    for rel in rels:
        p = source / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        paths.append(p)
    return paths


def _plan_with_two_groups(source: Path) -> DedupPlan:
    g1 = _make_files(source, ["gba/keep.gba", "gba/backup/keep.gba"])
    g2 = _make_files(source, ["nes/keep.nes", "nes/dupes/keep.nes"], content=b"NES" * 50)
    groups = [
        DedupGroup(sha256="a" * 64, keeper=g1[0], removals=[g1[1]], reclaimed_bytes=300),
        DedupGroup(sha256="b" * 64, keeper=g2[0], removals=[g2[1]], reclaimed_bytes=150),
    ]
    return DedupPlan(version=PLAN_VERSION, source=source,
                     created_at="2026-07-17T00:00:00Z", groups=groups)


# --------------------------------------------------------------------------- #
# T6.1 -- round-trip save/load preserves groups
# --------------------------------------------------------------------------- #

def test_plan_round_trip(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    plan = _plan_with_two_groups(source)

    save_plan(plan, dest)
    loaded = load_plan(dest)

    assert len(loaded.groups) == 2
    assert loaded.groups[0].keeper == plan.groups[0].keeper
    assert loaded.groups[0].removals == plan.groups[0].removals
    assert loaded.groups[0].sha256 == plan.groups[0].sha256
    assert loaded.groups[1].keeper == plan.groups[1].keeper
    assert loaded.version == PLAN_VERSION
    assert loaded.source == source


# --------------------------------------------------------------------------- #
# T6.2 -- hand-edited keeper is honoured
# --------------------------------------------------------------------------- #

def test_hand_edited_keeper_honoured(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    plan = _plan_with_two_groups(source)
    save_plan(plan, dest)

    plan_file = dest / DEDUP_PLAN_FILENAME
    text = plan_file.read_text(encoding="utf-8")
    # Swap KEEP <-> REMOVE for group 1 by rewriting the two lines.
    text = text.replace("KEEP:   gba/keep.gba", "KEEP:   gba/backup/keep.gba__TMP")
    text = text.replace("REMOVE: gba/backup/keep.gba", "REMOVE: gba/keep.gba")
    text = text.replace("KEEP:   gba/backup/keep.gba__TMP", "KEEP:   gba/backup/keep.gba")
    plan_file.write_text(text, encoding="utf-8")

    loaded = load_plan(dest)
    assert loaded.groups[0].keeper == source / "gba/backup/keep.gba"
    assert loaded.groups[0].removals == [source / "gba/keep.gba"]


# --------------------------------------------------------------------------- #
# T6.3 -- SKIP group is loaded with skipped=True
# --------------------------------------------------------------------------- #

def test_skip_marker_loaded(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    plan = _plan_with_two_groups(source)
    save_plan(plan, dest)

    plan_file = dest / DEDUP_PLAN_FILENAME
    text = plan_file.read_text(encoding="utf-8")
    text = text.replace("--- GROUP 1/2 ---", "# SKIP\n--- GROUP 1/2 ---")
    plan_file.write_text(text, encoding="utf-8")

    loaded = load_plan(dest)
    assert loaded.groups[0].skipped is True
    assert loaded.groups[1].skipped is False


def test_skip_written_and_re_read(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    plan = _plan_with_two_groups(source)
    plan.groups[1].skipped = True
    save_plan(plan, dest)

    loaded = load_plan(dest)
    assert loaded.groups[0].skipped is False
    assert loaded.groups[1].skipped is True


# --------------------------------------------------------------------------- #
# T6.4 -- hash index contains both sizes
# --------------------------------------------------------------------------- #

def test_hash_index_both_sizes(tmp_path):
    raw = tmp_path / "game.gba"
    raw.write_bytes(b"ROM" * 1000)  # 3000 bytes
    zip_path = tmp_path / "game.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("game.gba", b"ROM" * 1000)

    candidates = [raw, zip_path]
    sha256_map = {
        str(raw): content_sha256(raw),
        str(zip_path): content_sha256(zip_path),
    }
    index = build_hash_index(candidates, tmp_path, sha256_map)

    assert index["game.gba"].logical_size == 3000
    assert index["game.gba"].stored_size == 3000  # raw: identical
    assert index["game.zip"].logical_size == 3000
    assert index["game.zip"].stored_size < 3000   # compressed: smaller
    # Same content -> same sha256
    assert index["game.gba"].sha256 == index["game.zip"].sha256


def test_hash_index_unhashed_singleton_has_empty_sha(tmp_path):
    lone = tmp_path / "lone.gba"
    lone.write_bytes(b"UNIQUE" * 10)
    index = build_hash_index([lone], tmp_path, {})  # no hash provided
    assert index["lone.gba"].sha256 == ""
    assert index["lone.gba"].logical_size == 60
    assert index["lone.gba"].stored_size == 60


# --------------------------------------------------------------------------- #
# T6.5 -- corrupt plan -> ValueError, no files deleted
# --------------------------------------------------------------------------- #

def test_corrupt_plan_raises_valueerror(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    # A pre-existing ROM to prove nothing is deleted on load failure.
    victim = source / "keep.gba"
    victim.write_bytes(b"SAFE")

    (dest / DEDUP_PLAN_FILENAME).write_text("total garbage no header here\n@@@@", encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan(dest)
    assert victim.exists()


def test_missing_plan_raises_valueerror(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ValueError):
        load_plan(dest)


def test_version_mismatch_raises_valueerror(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / DEDUP_PLAN_FILENAME).write_text(
        "# version: 999\n# source: /src\n# created: x\n\n"
        "--- GROUP 1/1 ---\nsha256: aaa\nKEEP:   a.gba\nREMOVE: b.gba\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_plan(dest)


# --------------------------------------------------------------------------- #
# T6.6 -- hash index round-trip
# --------------------------------------------------------------------------- #

def test_hash_index_round_trip(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    index = {
        "gba/a.gba": HashRecord("gba/a.gba", "a" * 64, 1024, 1024),
        "gba/a.zip": HashRecord("gba/a.zip", "a" * 64, 1024, 400),
        "nes/b.nes": HashRecord("nes/b.nes", "", 512, 512),
    }
    save_hash_index(index, dest)
    loaded = load_hash_index(dest)

    assert set(loaded.keys()) == set(index.keys())
    for key in index:
        assert loaded[key].path == index[key].path
        assert loaded[key].sha256 == index[key].sha256
        assert loaded[key].logical_size == index[key].logical_size
        assert loaded[key].stored_size == index[key].stored_size

    # File is valid JSON with the documented top-level shape.
    raw = json.loads((dest / HASH_INDEX_FILENAME).read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert isinstance(raw["records"], list)
    assert "created_at" in raw


def test_load_hash_index_bad_version_raises(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / HASH_INDEX_FILENAME).write_text(
        json.dumps({"version": 999, "records": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_hash_index(dest)


def test_load_hash_index_invalid_json_raises(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / HASH_INDEX_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_hash_index(dest)


# --------------------------------------------------------------------------- #
# build_plan integration: keeper selection + descending sort
# --------------------------------------------------------------------------- #

def test_build_plan_selects_keeper_and_sorts(tmp_path):
    source = tmp_path / "src"
    source.mkdir()

    # Group A: small reclaim (128 bytes). zip is the keeper (Rule 5).
    a_raw = source / "gba" / "small.gba"
    a_raw.parent.mkdir(parents=True)
    a_raw.write_bytes(b"S" * 128)
    a_zip = source / "gba" / "small.zip"
    with zipfile.ZipFile(a_zip, "w") as zf:
        zf.writestr("small.gba", b"S" * 128)

    # Group B: large reclaim (4096 bytes removal).
    b_keep = source / "nes" / "big.nes"
    b_keep.parent.mkdir(parents=True)
    b_keep.write_bytes(b"B" * 4096)
    b_dupe = source / "nes" / "dupes" / "big.nes"
    b_dupe.parent.mkdir(parents=True)
    b_dupe.write_bytes(b"B" * 4096)

    groups = {
        "a" * 64: [a_raw, a_zip],
        "b" * 64: [b_keep, b_dupe],
    }
    opts = DedupOptions(source=source, dest=tmp_path / "dest")
    plan = build_plan(groups, opts)

    assert len(plan.groups) == 2
    # Sorted by reclaimed_bytes descending: group B (4096) first.
    assert plan.groups[0].reclaimed_bytes >= plan.groups[1].reclaimed_bytes
    # Group A keeper is the zip (Rule 5).
    zip_group = next(g for g in plan.groups if g.sha256 == "a" * 64)
    assert zip_group.keeper == a_zip
    assert zip_group.removals == [a_raw]
    # Group B keeper is the non-junk-folder copy.
    nes_group = next(g for g in plan.groups if g.sha256 == "b" * 64)
    assert nes_group.keeper == b_keep
    assert nes_group.removals == [b_dupe]
