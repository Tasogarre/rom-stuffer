"""U3 tests: logical-content hashing (raw + zip), size, and fingerprint prefilter."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from rom_stuffer.hashing import (
    content_sha256,
    logical_size,
    quick_fingerprint,
)
from helpers import make_zip, RomTree


# --------------------------------------------------------------------------- #
# T3.1 -- raw vs zip SHA-256 equality (the key invariant)
# --------------------------------------------------------------------------- #

def test_raw_and_zip_of_same_content_hash_equal(tmp_path):
    content = b"SNES ROM DATA " * 512  # 7168 bytes
    raw = tmp_path / "game.smc"
    raw.write_bytes(content)
    zip_path = tmp_path / "game.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("game.smc", content)

    h_raw = content_sha256(raw)
    h_zip = content_sha256(zip_path)
    assert h_raw == h_zip
    assert len(h_raw) == 64
    assert h_raw == h_raw.lower()


# --------------------------------------------------------------------------- #
# T3.2 -- different content yields different SHA-256
# --------------------------------------------------------------------------- #

def test_different_content_different_hash(tmp_path):
    a = tmp_path / "a.gba"
    b = tmp_path / "b.gba"
    a.write_bytes(b"ROM_A" * 100)
    b.write_bytes(b"ROM_B" * 100)
    assert content_sha256(a) != content_sha256(b)


# --------------------------------------------------------------------------- #
# T3.3 -- logical_size for raw vs zip
# --------------------------------------------------------------------------- #

def test_logical_size_raw_and_zip_match(tmp_path):
    content = b"X" * 8192
    raw = tmp_path / "big.gba"
    raw.write_bytes(content)
    zip_path = make_zip(tmp_path / "big.zip", "big.gba", content)

    assert logical_size(raw) == 8192
    assert logical_size(zip_path) == 8192


def test_logical_size_empty_zip_is_zero(tmp_path):
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w"):
        pass
    assert logical_size(zip_path) == 0


# --------------------------------------------------------------------------- #
# T3.4 -- zip hashing never writes temp files
# --------------------------------------------------------------------------- #

def test_zip_hashing_writes_no_temp_files(tmp_path):
    content = b"NO TEMP FILES " * 300
    zip_path = make_zip(tmp_path / "game.zip", "game.gba", content)
    before = sorted(os.listdir(tmp_path))
    content_sha256(zip_path)
    after = sorted(os.listdir(tmp_path))
    assert before == after


# --------------------------------------------------------------------------- #
# T3.5 -- large file stays memory-bounded (streaming)
# --------------------------------------------------------------------------- #

def test_large_raw_file_streams(tmp_path):
    big = tmp_path / "big.gba"
    # 32 MB written sparsely to keep the test cheap.
    size = 32 * 1024 * 1024
    with open(big, "wb") as fh:
        fh.seek(size - 1)
        fh.write(b"\x00")
    before = sorted(os.listdir(tmp_path))
    digest = content_sha256(big)
    after = sorted(os.listdir(tmp_path))
    assert len(digest) == 64
    assert before == after  # no temp files created


# --------------------------------------------------------------------------- #
# T3.6 -- unreadable file raises OSError
# --------------------------------------------------------------------------- #

def test_missing_file_raises_oserror():
    with pytest.raises(OSError):
        content_sha256(Path("/nonexistent/path/rom.gba"))


# --------------------------------------------------------------------------- #
# T3.7 -- corrupt zip raises BadZipFile
# --------------------------------------------------------------------------- #

def test_corrupt_zip_raises_badzipfile(tmp_path):
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"this is not a zip file at all!!!!!!!!!!!!!!!!!!!!!!")
    with pytest.raises(zipfile.BadZipFile):
        content_sha256(corrupt)


# --------------------------------------------------------------------------- #
# quick_fingerprint behaviour
# --------------------------------------------------------------------------- #

def test_fingerprint_raw_tag_and_collision(tmp_path):
    content = b"IDENTICAL RAW CONTENT " * 40
    a = tmp_path / "a.gba"
    b = tmp_path / "b.gba"
    a.write_bytes(content)
    b.write_bytes(content)
    tag_a, data_a = quick_fingerprint(a)
    tag_b, data_b = quick_fingerprint(b)
    assert tag_a == tag_b == "raw"
    assert data_a == data_b  # same content -> same fingerprint


def test_fingerprint_zip_tag_uses_crc(tmp_path):
    content = b"ZIP CONTENT " * 40
    z1 = make_zip(tmp_path / "one.zip", "game.gba", content)
    z2 = make_zip(tmp_path / "two.zip", "game.gba", content)
    tag1, data1 = quick_fingerprint(z1)
    tag2, data2 = quick_fingerprint(z2)
    assert tag1 == tag2 == "zip"
    assert data1 == data2


def test_fingerprint_zip_and_raw_never_collide(tmp_path):
    content = b"CROSS CONTAINER " * 40
    raw = tmp_path / "game.gba"
    raw.write_bytes(content)
    zip_path = make_zip(tmp_path / "game.zip", "game.gba", content)
    assert quick_fingerprint(raw)[0] != quick_fingerprint(zip_path)[0]


def test_fingerprint_large_raw_first_last_differ(tmp_path):
    # Two files with identical first block but different tail must differ.
    head = b"H" * (128 * 1024)
    a = tmp_path / "a.gba"
    b = tmp_path / "b.gba"
    a.write_bytes(head + b"AAAA")
    b.write_bytes(head + b"BBBB")
    assert quick_fingerprint(a) != quick_fingerprint(b)
