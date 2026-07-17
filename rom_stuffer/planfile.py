"""Dedup plan + hash index persistence (U6).

Two durable artifacts are written into the destination directory:

- ``.rom_stuffer_dedup_plan.txt`` -- a human-editable, reviewable plan (Appendix B).
  Each group lists one ``KEEP`` and N-1 ``REMOVE`` lines; the user may swap them or
  add ``# SKIP`` before a group header. ``load_plan`` re-parses the edited file.
- ``.rom_stuffer_hash_index.json`` -- the per-file hash index (Appendix A) carrying
  BOTH ``logical_size`` (uncompressed) and ``stored_size`` (on-disk), which differ
  for zips. Phase 2's per-system space estimator consumes it.

Both writes are atomic (write to ``.tmp``, fsync, replace). Loading a corrupt or
version-mismatched file raises ``ValueError`` and never touches any ROM.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rom_stuffer.dedup import DedupOptions, select_keeper
from rom_stuffer.hashing import logical_size
from rom_stuffer.metrics import format_size


DEDUP_PLAN_FILENAME: str = ".rom_stuffer_dedup_plan.txt"
HASH_INDEX_FILENAME: str = ".rom_stuffer_hash_index.json"

PLAN_VERSION: int = 1
HASH_INDEX_VERSION: int = 1

_GROUP_HEADER_RE = re.compile(r"^--- GROUP \d+/\d+ ---$")


@dataclass
class DedupGroup:
    """One set of byte-identical files: one keeper, N-1 removals.

    All paths are absolute. ``sha256`` is the 64-char hex content hash.
    ``reclaimed_bytes`` is the sum of stored (on-disk) sizes of all removals.
    ``skipped=True`` means the executor ignores this group.
    """

    sha256: str
    keeper: Path
    removals: list[Path]
    reclaimed_bytes: int
    skipped: bool = False


@dataclass
class DedupPlan:
    """A complete dedup session plan: metadata + list of groups.

    ``source`` is the absolute source directory. ``created_at`` is ISO-8601 UTC.
    ``version`` must equal ``PLAN_VERSION`` for ``load_plan`` to accept it.
    """

    version: int
    source: Path
    created_at: str
    groups: list[DedupGroup]


@dataclass
class HashRecord:
    """Per-file entry in the hash index.

    ``path`` is relative to source (POSIX separators). ``sha256`` is 64-char hex
    (``""`` if the file was enumerated but never content-hashed). ``logical_size``
    is the uncompressed content size; ``stored_size`` is on-disk bytes.
    """

    path: str
    sha256: str
    logical_size: int
    stored_size: int


HashIndex = dict[str, HashRecord]  # keyed by POSIX relative path string


# =========================================================================== #
# Dedup plan
# =========================================================================== #

def build_plan(groups: dict[str, list[Path]], options: DedupOptions) -> DedupPlan:
    """Construct a DedupPlan from detection output + keeper selection.

    One DedupGroup per sha256 entry: the keeper is ``select_keeper(paths, options)``,
    removals are the rest, and ``reclaimed_bytes`` is the sum of the removals'
    on-disk sizes (0 for any file whose ``stat`` fails). Groups are sorted by
    ``reclaimed_bytes`` descending (largest savings first). Never raises.
    """
    dedup_groups: list[DedupGroup] = []
    for sha256, paths in groups.items():
        keeper = select_keeper(paths, options)
        removals = [p for p in paths if p != keeper]
        reclaimed = 0
        for p in removals:
            try:
                reclaimed += p.stat().st_size
            except OSError:
                pass
        dedup_groups.append(
            DedupGroup(
                sha256=sha256,
                keeper=keeper,
                removals=removals,
                reclaimed_bytes=reclaimed,
            )
        )

    dedup_groups.sort(key=lambda g: g.reclaimed_bytes, reverse=True)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return DedupPlan(
        version=PLAN_VERSION,
        source=options.source,
        created_at=created_at,
        groups=dedup_groups,
    )


def save_plan(plan: DedupPlan, dest: Path) -> Path:
    """Serialise ``plan`` to ``dest / DEDUP_PLAN_FILENAME`` (Appendix B format).

    Atomic write (``.tmp`` + fsync + replace), utf-8. Returns the written path.
    Propagates OSError on write failure.
    """
    lines: list[str] = []
    lines.append("# ROM Stuffer Dedup Plan")
    lines.append(f"# version: {plan.version}")
    lines.append(f"# source: {plan.source}")
    lines.append(f"# created: {plan.created_at}")
    lines.append("# Edit: change KEEP/REMOVE, or add '# SKIP' before a group header.")
    lines.append("")

    total = len(plan.groups)
    for i, group in enumerate(plan.groups, start=1):
        if group.skipped:
            lines.append("# SKIP")
        lines.append(f"--- GROUP {i}/{total} ---")
        lines.append(f"sha256: {group.sha256}")
        lines.append(f"reclaims: {format_size(group.reclaimed_bytes)}")
        lines.append(f"KEEP:   {group.keeper.relative_to(plan.source).as_posix()}")
        for removal in group.removals:
            lines.append(f"REMOVE: {removal.relative_to(plan.source).as_posix()}")
        lines.append("")

    target = dest / DEDUP_PLAN_FILENAME
    _atomic_write_text(target, "\n".join(lines))
    return target


def load_plan(dest: Path) -> DedupPlan:
    """Parse and return a DedupPlan from ``dest / DEDUP_PLAN_FILENAME``.

    Honours hand edits: KEEP/REMOVE swaps and ``# SKIP`` markers. KEEP/REMOVE
    paths are resolved to absolute Paths (joined with the header source).
    ``reclaimed_bytes`` is recalculated from the removals on disk.

    Raises ``ValueError`` (never deleting or modifying files) if the file is
    missing, the version is absent/mismatched, or the format is invalid.
    """
    target = dest / DEDUP_PLAN_FILENAME
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ValueError(f"Dedup plan not found: {target}") from e
    except OSError as e:
        raise ValueError(f"Cannot read dedup plan: {e}") from e

    raw_lines = [line.rstrip() for line in text.splitlines()]

    # --- header metadata (before the first GROUP header) ---
    version: int | None = None
    source_str: str | None = None
    created_at: str = ""
    for line in raw_lines:
        if _GROUP_HEADER_RE.match(line):
            break
        if line.startswith("#"):
            body = line[1:].strip()
            key, sep, value = body.partition(":")
            if not sep:
                continue
            key = key.strip().lower()
            value = value.strip()
            if key == "version":
                try:
                    version = int(value)
                except ValueError:
                    version = None
            elif key == "source":
                source_str = value
            elif key == "created":
                created_at = value

    if version is None:
        raise ValueError("Dedup plan is missing a '# version:' header")
    if version != PLAN_VERSION:
        raise ValueError(
            f"Dedup plan version mismatch: got {version}, expected {PLAN_VERSION}"
        )
    if not source_str:
        raise ValueError("Dedup plan is missing a '# source:' header")
    source = Path(source_str)

    # --- groups ---
    groups: list[DedupGroup] = []
    current: DedupGroup | None = None
    pending_skip = False

    def flush() -> None:
        nonlocal current
        if current is not None:
            groups.append(current)
            current = None

    for line in raw_lines:
        if not line:
            continue
        if _GROUP_HEADER_RE.match(line):
            flush()
            current = DedupGroup(
                sha256="", keeper=source, removals=[], reclaimed_bytes=0,
                skipped=pending_skip,
            )
            pending_skip = False
            continue
        if line.startswith("#"):
            if line[1:].strip().lower() == "skip":
                pending_skip = True
            continue
        if current is None:
            continue
        if line.startswith("sha256:"):
            current.sha256 = line[len("sha256:"):].strip()
        elif line.startswith("reclaims:"):
            continue  # informational; recalculated below
        elif line.startswith("KEEP:"):
            rel = line[len("KEEP:"):].strip()
            current.keeper = source / rel
        elif line.startswith("REMOVE:"):
            rel = line[len("REMOVE:"):].strip()
            current.removals.append(source / rel)

    flush()

    # Recalculate reclaimed_bytes from the removals as they exist on disk.
    for group in groups:
        total = 0
        for removal in group.removals:
            try:
                total += removal.stat().st_size
            except OSError:
                pass
        group.reclaimed_bytes = total

    return DedupPlan(version=version, source=source, created_at=created_at, groups=groups)


# =========================================================================== #
# Hash index
# =========================================================================== #

def build_hash_index(
    candidates: list[Path],
    source: Path,
    sha256_map: dict[str, str],
) -> HashIndex:
    """Build a HashIndex from enumerated candidates and pre-computed hashes.

    Each candidate yields a HashRecord keyed by its POSIX-relative path.
    ``sha256`` comes from ``sha256_map[str(path)]`` (``""`` if the file was never
    hashed -- e.g. a size singleton). On any per-file OSError, both size fields
    fall back to 0. Never raises.
    """
    index: HashIndex = {}
    for p in candidates:
        try:
            rel = p.relative_to(source).as_posix()
        except ValueError:
            rel = p.name
        try:
            log_sz = logical_size(p)
            stored_sz = p.stat().st_size
        except OSError:
            log_sz = 0
            stored_sz = 0
        except Exception:
            # BadZipFile etc. -- keep the record but with zero sizes.
            log_sz = 0
            try:
                stored_sz = p.stat().st_size
            except OSError:
                stored_sz = 0
        index[rel] = HashRecord(
            path=rel,
            sha256=sha256_map.get(str(p), ""),
            logical_size=log_sz,
            stored_size=stored_sz,
        )
    return index


def save_hash_index(index: HashIndex, dest: Path) -> Path:
    """Write ``index`` to ``dest / HASH_INDEX_FILENAME`` as JSON (Appendix A).

    Atomic write (``.tmp`` + fsync + replace). Returns the written path.
    Propagates OSError.
    """
    # Derive a source path from the destination is not possible here; the index
    # records already carry relative paths, so we persist an empty source marker
    # only when nothing better is known. Callers that need the source in the file
    # should pass records built from a known root.
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "version": HASH_INDEX_VERSION,
        "created_at": created_at,
        "source": "",
        "records": [
            {
                "path": rec.path,
                "sha256": rec.sha256,
                "logical_size": rec.logical_size,
                "stored_size": rec.stored_size,
            }
            for rec in index.values()
        ],
    }
    target = dest / HASH_INDEX_FILENAME
    _atomic_write_text(target, json.dumps(payload, indent=2))
    return target


def load_hash_index(dest: Path) -> HashIndex:
    """Load and return a HashIndex from ``dest / HASH_INDEX_FILENAME``.

    Returns a dict of POSIX-relative path -> HashRecord. Raises ``ValueError`` on
    schema mismatch; raises ``OSError`` if the file is unreadable.
    """
    target = dest / HASH_INDEX_FILENAME
    with open(target, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise ValueError(f"Hash index is not valid JSON: {e}") from e

    if not isinstance(data, dict) or "records" not in data:
        raise ValueError("Hash index is missing the 'records' array")
    if data.get("version") != HASH_INDEX_VERSION:
        raise ValueError(
            f"Hash index version mismatch: got {data.get('version')}, "
            f"expected {HASH_INDEX_VERSION}"
        )

    index: HashIndex = {}
    for rec in data["records"]:
        try:
            record = HashRecord(
                path=rec["path"],
                sha256=rec["sha256"],
                logical_size=int(rec["logical_size"]),
                stored_size=int(rec["stored_size"]),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Hash index record is malformed: {e}") from e
        index[record.path] = record
    return index


# =========================================================================== #
# Internal helpers
# =========================================================================== #

def _atomic_write_text(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` atomically (tmp + fsync + replace)."""
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(target)
