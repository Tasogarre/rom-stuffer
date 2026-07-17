"""Logical-content hashing for ROM de-duplication (U3).

The library mixes raw ROM files and already-compressed ``.zip`` archives. Dedup
must compare the *logical* (uncompressed) ROM content regardless of container,
and it must do so without mass-unzipping the collection:

- ``logical_size``      -- uncompressed content size (a raw ``stat``; for a zip,
  the sum of entry uncompressed sizes read from the central directory).
- ``quick_fingerprint`` -- a cheap pre-filter. Zips ride entirely on their stored
  CRC-32 (no decompression at all); raw files use a partial first/last-block CRC.
- ``content_sha256``    -- the byte-exact confirmation. A raw file and a ``.zip``
  of the same ROM content hash EQUAL, because the zip's entries are decompressed
  and streamed into the same accumulator. Zip entries are streamed in memory and
  never extracted to disk, so peak memory stays constant.
"""
from __future__ import annotations

import hashlib
import zipfile
import zlib
from pathlib import Path


HASH_CHUNK_BYTES: int = 1 * 1024 * 1024        # 1 MB streaming chunk
FINGERPRINT_PARTIAL_BYTES: int = 64 * 1024      # 64 KB partial read for raw files


def logical_size(path: Path) -> int:
    """Return the uncompressed content size in bytes.

    For a ``.zip`` this is the sum of every entry's uncompressed ``file_size``
    (0 for an empty zip). For any other file it is ``stat().st_size``.

    Propagates ``OSError`` (unreadable) and ``zipfile.BadZipFile`` (corrupt zip);
    callers must catch and record these as a skip/error.
    """
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            return sum(zi.file_size for zi in zf.infolist())
    return path.stat().st_size


def quick_fingerprint(path: Path) -> tuple[str, object]:
    """Return a cheap pre-filter fingerprint; same-content files must collide.

    Returns ``(container_tag, data)``:

    - ``"zip"``: ``data`` is a tuple of each entry's CRC-32 (from the central
      directory, NO decompression), entries sorted by filename.
    - ``"raw"``: ``data`` is ``(crc32_first, crc32_last)`` over the first and last
      ``FINGERPRINT_PARTIAL_BYTES`` of the file (the same block for small files).

    Different logical content SHOULD produce different fingerprints (collisions
    are possible but rare -- SHA-256 confirms). Zip and raw fingerprints never
    collide across containers because of the differing ``container_tag``.

    Propagates ``OSError`` and ``zipfile.BadZipFile``.
    """
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            entries = sorted(zf.infolist(), key=lambda z: z.filename)
            crcs = tuple(z.CRC for z in entries)
        return ("zip", crcs)

    sz = path.stat().st_size
    with open(path, "rb") as f:
        first_chunk = f.read(FINGERPRINT_PARTIAL_BYTES)
        if sz > FINGERPRINT_PARTIAL_BYTES:
            f.seek(max(0, sz - FINGERPRINT_PARTIAL_BYTES))
            last_chunk = f.read(FINGERPRINT_PARTIAL_BYTES)
        else:
            last_chunk = first_chunk
    return ("raw", (zlib.crc32(first_chunk), zlib.crc32(last_chunk)))


def content_sha256(path: Path) -> str:
    """Return the hex SHA-256 of the logical (uncompressed) ROM content.

    - Raw file: SHA-256 of the file's bytes, streamed in ``HASH_CHUNK_BYTES`` chunks.
    - ``.zip``: entries sorted by filename; each entry's decompressed bytes are
      streamed via ``ZipFile.open()`` into one accumulator in order. Never
      extracted to disk.

    KEY INVARIANT: ``content_sha256("game.gba") == content_sha256("game.zip")``
    when ``game.zip`` holds exactly ``game.gba`` (one entry, identical bytes).

    Returns a 64-character lowercase hex string. Propagates ``OSError`` and
    ``zipfile.BadZipFile``; callers must catch and record.
    """
    h = hashlib.sha256()
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            entries = sorted(zf.infolist(), key=lambda z: z.filename)
            for entry in entries:
                with zf.open(entry) as stream:
                    while True:
                        chunk = stream.read(HASH_CHUNK_BYTES)
                        if not chunk:
                            break
                        h.update(chunk)
    else:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                h.update(chunk)
    return h.hexdigest()
