"""Duplicate detection pipeline (U4) and keeper selection (U5).

Detection enumerates ROM candidates through the shared scan + ``exclusion_reason``
guards -- so BIOS folders and disc images are NEVER compared -- then narrows to
byte-identical groups with a cheap-to-expensive funnel:

    size bucket  ->  quick fingerprint  ->  SHA-256 confirmation  ->  group

Only files that survive the size + fingerprint pre-filter are ever content-hashed.

Keeper selection is a deterministic, ordered heuristic: for a group of identical
files it picks the single copy to preserve. It is read-only -- it never moves or
deletes anything. The executor (U8) is a later unit and lives elsewhere.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rom_stuffer.guards import SUPPORTED_EXTENSIONS, describe_error, exclusion_reason
from rom_stuffer.hashing import content_sha256, logical_size, quick_fingerprint
from rom_stuffer.metrics import format_size


@dataclass
class DedupOptions:
    """Runtime configuration for a dedup session.

    All path fields are absolute. ``keeper_order`` and ``protect`` contain folder
    name substrings matched case-insensitively against path components. ``min_size``
    is in bytes and defaults to 0 (no filtering).
    """

    source: Path
    dest: Path
    dry_run: bool = False
    recursive: bool = True
    per_system: bool = False
    min_size: int = 0
    keeper_order: list[str] = field(default_factory=list)
    protect: list[str] = field(default_factory=list)
    interactive: bool = False
    hard_delete: bool = False
    apply_plan_path: Path | None = None


# =========================================================================== #
# U4: Detection pipeline
# =========================================================================== #

def detect_duplicates(
    options: DedupOptions,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[dict[str, list[Path]], list[dict]]:
    """Scan source, find byte-identical ROM files, return duplicate groups.

    Returns ``(groups, skipped_files)`` where ``groups`` maps a 64-char SHA-256
    hex string to a list of >= 2 absolute paths whose logical content is equal,
    and ``skipped_files`` is a list of ``{"file": str, "reason": str}``.

    Files refused by ``exclusion_reason`` (BIOS, disc) never appear in a group.
    Files below ``options.min_size`` are skipped. Singleton files (unique logical
    size, or a unique fingerprint) are never content-hashed. Per-file OSError /
    BadZipFile are caught and the file is dropped from detection.
    """
    candidates, skipped = _enumerate_candidates(options)
    if progress_callback is not None:
        progress_callback("enumerated", 0, len(candidates))

    size_buckets = _bucket_by_size(candidates)

    sha256_groups: dict[str, list[Path]] = defaultdict(list)
    processed = 0
    for sz, paths in size_buckets.items():
        if len(paths) < 2:
            continue  # unique logical size -- never read
        collision_groups = _apply_fingerprint(paths)
        for group in collision_groups:
            if len(group) < 2:
                continue
            confirmed = _confirm_sha256(group)
            for h, members in confirmed.items():
                sha256_groups[h].extend(members)
            processed += len(group)
            if progress_callback is not None:
                progress_callback("hashed", processed, len(candidates))

    # A path can appear via more than one fingerprint representation; collapse
    # duplicates while preserving first-seen order, and keep only real groups.
    result = {
        h: list(dict.fromkeys(ps))
        for h, ps in sha256_groups.items()
        if len(list(dict.fromkeys(ps))) >= 2
    }
    return result, skipped


def _enumerate_candidates(options: DedupOptions) -> tuple[list[Path], list[dict]]:
    """Enumerate ROM candidates, applying guards and the min_size filter.

    Returns ``(candidates, skipped)``. ``candidates`` are absolute paths that
    passed ``exclusion_reason`` and ``min_size``; ``skipped`` records every
    excluded path as ``{"file": str, "reason": str}``. Uses ``rglob`` when
    ``options.recursive`` else ``glob``. Per-file OSError is caught and skipped.
    """
    candidates: list[Path] = []
    skipped: list[dict] = []

    scan_iter = (
        options.source.rglob("*") if options.recursive else options.source.glob("*")
    )
    for p in scan_iter:
        try:
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            # A ``.zip`` is the compressed form of a ROM that this tool itself
            # produces, so it is a first-class dedup candidate even though it is
            # not a raw cartridge extension. The guards below still apply (a zip
            # inside a bios/ folder is refused like any other file).
            if ext not in SUPPORTED_EXTENSIONS and ext != ".zip":
                skipped.append({"file": str(p.name), "reason": f"Unsupported: {p.suffix}"})
                continue
            sz = p.stat().st_size
            size_for_guard = sz if ext == ".bin" else None
            reason = exclusion_reason(p, ext, size_for_guard, options.source)
            if reason:
                skipped.append({"file": str(p.name), "reason": reason})
                continue
            if sz < options.min_size:
                skipped.append(
                    {
                        "file": str(p.name),
                        "reason": f"Below min-size ({format_size(options.min_size)})",
                    }
                )
                continue
            candidates.append(p)
        except OSError as e:
            skipped.append({"file": str(p.name), "reason": f"Unreadable: {describe_error(e)}"})

    if options.per_system:
        # Compare only within a shared direct child folder of source. Retain a
        # candidate only if its top-level (system) component appears >= 2 times.
        def top(p: Path) -> str | None:
            rel_parts = p.relative_to(options.source).parts
            return rel_parts[0] if len(rel_parts) > 1 else None

        system_counts = Counter(top(p) for p in candidates if top(p) is not None)
        candidates = [
            p for p in candidates if top(p) is not None and system_counts[top(p)] >= 2
        ]

    return candidates, skipped


def _bucket_by_size(candidates: list[Path]) -> dict[int, list[Path]]:
    """Group candidates by ``logical_size``. Files whose size cannot be read
    (OSError / BadZipFile) are dropped."""
    buckets: dict[int, list[Path]] = defaultdict(list)
    for p in candidates:
        try:
            buckets[logical_size(p)].append(p)
        except Exception:
            continue
    return buckets


def _apply_fingerprint(size_bucket: list[Path]) -> list[list[Path]]:
    """Pre-filter a same-size bucket into fingerprint collision groups.

    Homogeneous bucket (all zip or all raw): group by ``quick_fingerprint`` and
    return only groups with >= 2 members. Mixed bucket (zip and raw both present):
    the fingerprint cannot compare across containers, so return ``[size_bucket]``
    and let SHA-256 decide. Per-file fingerprint errors drop that file.
    """
    is_zip = [p.suffix.lower() == ".zip" for p in size_bucket]
    if any(is_zip) and not all(is_zip):
        # Mixed containers: defer entirely to SHA-256.
        return [size_bucket]

    fp_groups: dict[object, list[Path]] = defaultdict(list)
    for p in size_bucket:
        try:
            fp_groups[quick_fingerprint(p)].append(p)
        except Exception:
            continue
    return [members for members in fp_groups.values() if len(members) >= 2]


def _confirm_sha256(candidates: list[Path]) -> dict[str, list[Path]]:
    """Compute ``content_sha256`` for each candidate and group by hash; return
    only groups with >= 2 members. Per-file hashing errors drop that file."""
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for p in candidates:
        try:
            by_hash[content_sha256(p)].append(p)
        except Exception:
            continue
    return {h: members for h, members in by_hash.items() if len(members) >= 2}


# =========================================================================== #
# U5: Keeper selection
# =========================================================================== #

# Junk folder names (matched case-insensitively against path components relative
# to source). A copy inside one of these is de-prioritised as a keeper.
_JUNK_FOLDERS: set[str] = {
    "dupes", "dupe", "duplicates", "duplicate", "backup", "backups",
    "copies", "copy", "_dupes", "_backup",
}

# Trailing junk-name suffixes (case-insensitive) on a file stem.
_JUNK_NAME_SUFFIXES: tuple[str, ...] = (
    " (1)", " (2)", " copy", "-copy", "_copy", "- copy", " - copy",
)
_JUNK_NUMBERED_RE = re.compile(r" \(\d+\)$")

# No-Intro region parenthetical (a region-tagged name is preferred).
_REGION_RE = re.compile(
    r"\((USA|Europe|Japan|World|En|Fr|De|Es|It|Pt|Nl|Sv|No|Da|Ko|Zh|Ru|Pl)[^)]*\)"
)


def _has_no_intro_region(stem: str) -> bool:
    """True if ``stem`` contains a No-Intro-style region parenthetical."""
    return _REGION_RE.search(stem) is not None


def _is_junk_name(stem: str) -> bool:
    """True if ``stem`` ends with a junk-copy suffix or a trailing ` (N)`."""
    low = stem.lower()
    if any(low.endswith(suffix) for suffix in _JUNK_NAME_SUFFIXES):
        return True
    return _JUNK_NUMBERED_RE.search(stem) is not None


def _is_junk_folder(path: Path, source: Path) -> bool:
    """True if any component of ``path`` relative to ``source`` is a junk folder."""
    try:
        rel_parts = path.relative_to(source).parts
    except ValueError:
        rel_parts = path.parts
    return any(part.lower() in _JUNK_FOLDERS for part in rel_parts)


def _keeper_sort_key(path: Path, options: DedupOptions) -> tuple:
    """Compute the 8-rule keeper sort key. Sorting ascending puts the preferred
    path first (lower key value == more preferred). Never raises."""
    try:
        rel = path.relative_to(options.source)
    except ValueError:
        rel = path
    parts_lower = {c.lower() for c in path.parts}

    # Rule 0 -- protected folder is maximally preferred.
    r0 = 0 if any(pf.lower() in parts_lower for pf in options.protect) else 1

    # Rule 1 -- keeper-order folder priority; lower index wins, no match is worst.
    r1 = len(options.keeper_order)
    for i, folder in enumerate(options.keeper_order):
        if any(folder.lower() == c.lower() for c in path.parts):
            r1 = i
            break

    # Rule 2 -- not in a junk folder.
    r2 = 1 if _is_junk_folder(path, options.source) else 0
    # Rule 3 -- not a junk name.
    r3 = 1 if _is_junk_name(path.stem) else 0
    # Rule 4 -- No-Intro region tag preferred.
    r4 = 0 if _has_no_intro_region(path.stem) else 1
    # Rule 5 -- compressed (.zip) copy preferred.
    r5 = 0 if path.suffix.lower() == ".zip" else 1
    # Rule 6 -- shallower path preferred.
    r6 = len(rel.parts)
    # Rule 7 -- alphabetical tie-break.
    r7 = str(path)

    return (r0, r1, r2, r3, r4, r5, r6, r7)


def select_keeper(paths: list[Path], options: DedupOptions) -> Path:
    """Return the path in ``paths`` selected by the keeper heuristic.

    Deterministic: the path with the lowest ``_keeper_sort_key`` wins, so the same
    inputs always yield the same result. A protected path always wins (Rule 0); a
    ``--keeper-order`` match takes priority next (Rule 1); ties break
    alphabetically (Rule 7). Never raises.
    """
    return min(paths, key=lambda p: _keeper_sort_key(p, options))
