"""Phase-2 space-saving estimator (built on the §4.3 hash index shape).

Given a ROM library it projects, per system and in total, how much SD-card space
the collection will occupy once **compressed** and **de-duplicated** -- and how
that compares with its current **decompressed** footprint. It is strictly
read-only: nothing under ``source`` is ever created, moved, or deleted.

The pipeline reuses the engine wholesale:

- enumeration + guards mirror dedup: BIOS folders and disc images are EXCLUDED via
  ``exclusion_reason`` exactly as compression and dedup exclude them;
- ``logical_size`` supplies the uncompressed (decompressed) size for both raw files
  and ``.zip`` archives (summing zip entry sizes, no extraction);
- ``detect_duplicates`` + ``select_keeper`` supply the dedup savings: every non-keeper
  copy in a duplicate group is reclaimable, counted at its *compressed* size because
  dedup runs before compression on disk.

A file's SYSTEM is the first path component relative to ``source`` (the system
folder, e.g. ``megadrive``); a file sitting directly under ``source`` falls back to
an extension->system label, or ``"other"``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rom_stuffer.dedup import DedupOptions, detect_duplicates, select_keeper
from rom_stuffer.guards import SUPPORTED_EXTENSIONS, describe_error, exclusion_reason
from rom_stuffer.hashing import logical_size
from rom_stuffer.metrics import DRY_RUN_COMPRESSION_ESTIMATE, format_size


# Fallback extension -> system label for files that sit directly under the source
# root (no system folder to name them). Anything unmapped becomes "other".
_EXT_SYSTEM: dict[str, str] = {
    ".nes": "nes", ".fds": "fds",
    ".sfc": "snes", ".smc": "snes", ".fig": "snes", ".swc": "snes",
    ".gb": "gb", ".gbc": "gbc", ".gba": "gba",
    ".vb": "virtualboy", ".vboy": "virtualboy",
    ".md": "megadrive", ".gen": "megadrive", ".smd": "megadrive", ".bin": "megadrive",
    ".sms": "mastersystem", ".gg": "gamegear", ".sg": "sg1000", ".32x": "sega32x",
    ".pce": "pcengine", ".sgx": "pcengine",
    ".a26": "atari2600", ".a52": "atari5200", ".a78": "atari7800",
    ".j64": "jaguar", ".lnx": "lynx",
    ".ws": "wonderswan", ".wsc": "wonderswan", ".ngp": "ngp", ".ngc": "ngp",
    ".col": "colecovision", ".int": "intellivision", ".vec": "vectrex",
}


@dataclass
class SystemEstimate:
    """Per-system space projection.

    ``final_bytes`` is the on-SD footprint after compression and dedup:
    ``compressed_bytes - dedup_removable_bytes``.
    """

    system: str
    file_count: int = 0
    decompressed_bytes: int = 0
    compressed_bytes: int = 0
    dedup_removable_bytes: int = 0

    @property
    def final_bytes(self) -> int:
        return self.compressed_bytes - self.dedup_removable_bytes


@dataclass
class LibraryEstimate:
    """Whole-library projection: the per-system rows plus derived totals.

    ``skipped`` records files left out of the numbers (unsupported extension,
    BIOS/disc exclusion, or an unreadable/corrupt file) as
    ``{"file": str, "reason": str}`` -- an unreadable file is a skip, never fatal.
    """

    systems: list[SystemEstimate] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def total_file_count(self) -> int:
        return sum(s.file_count for s in self.systems)

    @property
    def total_decompressed(self) -> int:
        return sum(s.decompressed_bytes for s in self.systems)

    @property
    def total_compressed(self) -> int:
        return sum(s.compressed_bytes for s in self.systems)

    @property
    def total_dedup_removable(self) -> int:
        return sum(s.dedup_removable_bytes for s in self.systems)

    @property
    def total_final(self) -> int:
        return sum(s.final_bytes for s in self.systems)


def _system_of(path: Path, source: Path) -> str:
    """Return the system label for ``path``: the first path component relative to
    ``source``, or an extension fallback for a file sitting directly under it."""
    try:
        rel_parts = path.relative_to(source).parts
    except ValueError:
        rel_parts = path.parts
    if len(rel_parts) > 1:
        return rel_parts[0]
    return _EXT_SYSTEM.get(path.suffix.lower(), "other")


def _compressed_size(path: Path, decompressed: int, compress_ratio: float) -> int:
    """Projected on-disk size after compression.

    An already-``.zip`` file contributes its real stored (on-disk) size; a raw file
    contributes ``decompressed * compress_ratio`` (the same rough DEFLATE estimate
    the dry-run compressor uses)."""
    if path.suffix.lower() == ".zip":
        return path.stat().st_size
    return int(round(decompressed * compress_ratio))


def estimate_library(
    source: Path,
    *,
    recursive: bool = True,
    compress_ratio: float = DRY_RUN_COMPRESSION_ESTIMATE,
    per_system: bool = True,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> LibraryEstimate:
    """Project the compressed, de-duplicated SD-card footprint of ``source``.

    Read-only: enumerates ROM candidates through the shared guards (BIOS/disc
    EXCLUDED), measures each file's decompressed and estimated-compressed size,
    then runs duplicate detection (dry-run) to attribute each reclaimable copy's
    compressed bytes to its system. Returns a :class:`LibraryEstimate`.

    ``compress_ratio`` scales raw files only; ``.zip`` files use their real on-disk
    size. ``per_system`` is passed through to detection (dedup only within a system
    folder when True). ``progress_callback(stage, current, total)`` is forwarded to
    the detection pass -- the long part of the work. Unreadable/corrupt files are
    recorded in ``skipped`` and never abort the run.
    """
    source = Path(source)

    systems: dict[str, SystemEstimate] = {}
    skipped: list[dict] = []
    # path -> (system, compressed_bytes) so dedup removals reuse the exact per-file
    # compressed size measured here instead of recomputing it.
    measured: dict[Path, tuple[str, int]] = {}

    def _system(name: str) -> SystemEstimate:
        est = systems.get(name)
        if est is None:
            est = SystemEstimate(system=name)
            systems[name] = est
        return est

    scan_iter = source.rglob("*") if recursive else source.glob("*")
    for p in scan_iter:
        try:
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS and ext != ".zip":
                skipped.append({"file": p.name, "reason": f"Unsupported: {p.suffix}"})
                continue
            size_for_guard = p.stat().st_size if ext == ".bin" else None
            reason = exclusion_reason(p, ext, size_for_guard, source)
            if reason:
                skipped.append({"file": p.name, "reason": reason})
                continue
        except OSError as e:
            skipped.append({"file": p.name, "reason": f"Unreadable: {describe_error(e)}"})
            continue

        # Sizing may touch the file (stat, or open for a zip's central directory),
        # so a corrupt/unreadable file is a skip, not a fatal error.
        try:
            decompressed = logical_size(p)
            compressed = _compressed_size(p, decompressed, compress_ratio)
        except Exception as e:
            skipped.append({"file": p.name, "reason": f"Unreadable: {describe_error(e)}"})
            continue

        name = _system_of(p, source)
        est = _system(name)
        est.file_count += 1
        est.decompressed_bytes += decompressed
        est.compressed_bytes += compressed
        measured[p] = (name, compressed)

    # Dedup savings: detect_duplicates is read-only (it never uses `dest`), so
    # pointing dest at source is safe. Each non-keeper copy is reclaimable and is
    # charged at its compressed size (dedup runs before compression on disk).
    options = DedupOptions(
        source=source,
        dest=source,
        dry_run=True,
        recursive=recursive,
        per_system=per_system,
    )
    groups, _detect_skipped = detect_duplicates(options, progress_callback=progress_callback)
    for members in groups.values():
        keeper = select_keeper(members, options)
        for member in members:
            if member == keeper:
                continue
            found = measured.get(member)
            if found is None:
                continue  # measured pass dropped it (unreadable) -- stay consistent
            sys_name, compressed = found
            _system(sys_name).dedup_removable_bytes += compressed

    ordered = [systems[k] for k in sorted(systems)]
    return LibraryEstimate(systems=ordered, skipped=skipped)


def render_estimate(est: LibraryEstimate, console=None) -> None:
    """Render the estimate as a themed Rich table with a per-system row, a TOTAL
    row, and a headline. Uses the shared TUI console when ``console`` is None."""
    from rom_stuffer.tui import box, Table, Text  # noqa: PLC0415

    if console is None:
        from rom_stuffer.tui import console as console  # noqa: PLC0415

    table = Table(
        title="Estimated SD-card footprint",
        box=box.SIMPLE_HEAD,
        title_style="accent",
        show_lines=False,
    )
    table.add_column("System", style="brand", overflow="fold")
    table.add_column("Files", style="value", justify="right")
    table.add_column("Decompressed", style="muted", justify="right")
    table.add_column("Compressed est", style="info", justify="right")
    table.add_column("Dupes reclaimable", style="warn", justify="right")
    table.add_column("Final on SD", style="success", justify="right")

    for s in est.systems:
        table.add_row(
            s.system,
            str(s.file_count),
            format_size(s.decompressed_bytes),
            format_size(s.compressed_bytes),
            format_size(s.dedup_removable_bytes),
            format_size(s.final_bytes),
        )

    table.add_section()
    table.add_row(
        "[value]TOTAL[/value]",
        f"[value]{est.total_file_count}[/value]",
        f"[value]{format_size(est.total_decompressed)}[/value]",
        f"[value]{format_size(est.total_compressed)}[/value]",
        f"[value]{format_size(est.total_dedup_removable)}[/value]",
        f"[value]{format_size(est.total_final)}[/value]",
    )

    decompressed = est.total_decompressed
    final = est.total_final
    pct = ((decompressed - final) / decompressed * 100) if decompressed else 0.0

    headline = Text(justify="center")
    headline.append(f"{format_size(final)} on SD", style="success")
    headline.append("   ·   ", style="muted")
    headline.append(f"was {format_size(decompressed)} decompressed", style="muted")
    headline.append("   ·   ", style="muted")
    headline.append(f"{pct:.0f}% smaller", style="accent")

    console.print()
    console.print(headline)
    console.print(table)
    if est.skipped:
        console.print(
            f"[muted]{len(est.skipped)} file(s) excluded from the estimate "
            f"(unsupported, BIOS/disc, or unreadable).[/muted]"
        )


def run_estimate(args) -> LibraryEstimate:
    """CLI entry point: build parameters from an argparse namespace, run the
    estimate behind a Rich progress bar, and render it.

    Robust: a missing/invalid source is reported and returns an empty estimate
    rather than raising; per-file read errors are already handled as skips inside
    ``estimate_library``.
    """
    from rom_stuffer.tui import (  # noqa: PLC0415
        console, Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn,
        TimeRemainingColumn,
    )

    source = Path(getattr(args, "source", None) or ".").expanduser()
    recursive = not bool(getattr(args, "no_recursive", False))
    per_system = bool(getattr(args, "per_system", True))

    if not source.exists() or not source.is_dir():
        console.print(f"[danger]Source directory not found:[/danger] {source}")
        return LibraryEstimate()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[accent]Analysing library[/accent]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("estimate", total=None)

            def _cb(stage: str, current: int, total: int) -> None:
                progress.update(task, total=total or None, completed=current)

            est = estimate_library(
                source,
                recursive=recursive,
                per_system=per_system,
                progress_callback=_cb,
            )
    except Exception as e:  # pragma: no cover - never let a render/scan glitch abort
        console.print(f"[danger]Estimate failed:[/danger] {describe_error(e)}")
        return LibraryEstimate()

    render_estimate(est, console=console)
    return est
