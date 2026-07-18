"""SD-card mirror engine for rom-stuffer.

Provides a full one-way mirror from a local ROM library to a mounted SD card:
copy new/changed files, optionally prune card files with no local counterpart.

Sequential writes only — DO NOT parallelize. Flash-memory controllers perform
poorly under parallel I/O: concurrent writes thrash the controller's write
queue and produce lower sustained throughput than a single sequential stream.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from rom_stuffer.compress import fast_sd_copy
from rom_stuffer.tui import (
    console as _default_console,
    box, Align, Group, Panel, Table, Text, escape,
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn,
)
from rom_stuffer.metrics import format_size
from rom_stuffer.logs import get_logger
from rom_stuffer.guards import describe_error


_log = get_logger("sync")


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class SyncOptions:
    """Configuration for a single mirror run."""
    source: Path            # local library to mirror FROM
    sdcard: Path            # SD-card directory to mirror TO
    dry_run: bool = False
    prune: bool = True      # full mirror: delete card files with no local counterpart
    recursive: bool = True


@dataclass
class SyncMetrics:
    """Counters accumulated during a mirror run."""
    files_copied: int = 0
    bytes_copied: int = 0
    files_skipped: int = 0                              # already identical on card (same size)
    files_pruned: int = 0
    bytes_pruned: int = 0
    errors: list = field(default_factory=list)          # list[dict] {'file':..., 'error':...}
    dry_run: bool = False
    prune_blocked_empty_source: bool = False            # safety flag: prune skipped because source was empty


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def mirror_to_sdcard(options: SyncOptions, progress_callback=None) -> SyncMetrics:
    """One-way mirror from options.source to options.sdcard.

    Copy pass: for every source file, copy to the card when absent or
    size-mismatched. Skip when already identical (same size).

    Prune pass (if options.prune): delete card files with no source
    counterpart — UNLESS the source has zero files (safety guard, never
    wipe the card because of a bad source path).

    Both passes are sequential. Do not parallelise — flash-memory
    controllers thrash under concurrent writes/deletes.
    """
    metrics = SyncMetrics(dry_run=options.dry_run)

    # ------------------------------------------------------------------ #
    # 1. Collect source files as relative paths.
    # ------------------------------------------------------------------ #
    rel_paths: set[Path] = set()
    sized: list[tuple[Path, int]] = []   # (abs_source_path, size_bytes)

    if options.recursive:
        walker = options.source.rglob("*")
    else:
        walker = options.source.iterdir()

    for entry in walker:
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        rel = entry.relative_to(options.source)
        rel_paths.add(rel)
        sized.append((entry, size))

    total_bytes = sum(sz for _, sz in sized)

    # ------------------------------------------------------------------ #
    # 2. Copy pass — with Rich progress bar.
    # ------------------------------------------------------------------ #
    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None, complete_style="accent", finished_style="success"),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(compact=True),
        console=_default_console,
        expand=True,
    ) as progress:
        file_task = progress.add_task("[accent]Syncing files[/accent]", total=len(sized))
        byte_task = progress.add_task("[info]Data   [/info]", total=max(total_bytes, 1))

        for src_path, src_size in sized:
            rel = src_path.relative_to(options.source)
            dest_path = options.sdcard / rel
            safe_name = escape(src_path.name)

            try:
                # Skip when the destination already exists with the same size.
                try:
                    dest_stat = dest_path.stat()
                    already_there = (dest_stat.st_size == src_size)
                except OSError:
                    already_there = False

                if already_there:
                    metrics.files_skipped += 1
                else:
                    progress.update(
                        file_task,
                        description=f"[accent]Copying[/accent] {safe_name}",
                    )
                    if not options.dry_run:
                        # fast_sd_copy creates parent directories automatically.
                        fast_sd_copy(src_path, dest_path)
                    metrics.files_copied += 1
                    metrics.bytes_copied += src_size

                if progress_callback is not None:
                    progress_callback(rel, metrics)

            except OSError as e:
                err = describe_error(e)
                metrics.errors.append({'file': str(src_path), 'error': err})
                _log.warning("copy failed %s: %s", src_path, err)

            finally:
                progress.advance(file_task)
                progress.advance(byte_task, advance=src_size)

    # ------------------------------------------------------------------ #
    # 3. Prune pass.
    # ------------------------------------------------------------------ #
    if options.prune:
        if not rel_paths:
            # SAFETY: never delete card files when source is empty/missing.
            # A misconfigured or disconnected source path must not wipe the card.
            metrics.prune_blocked_empty_source = True
            _log.warning(
                "prune skipped: source directory '%s' contains no files; "
                "refusing to delete anything from the SD card.",
                options.sdcard,
            )
        else:
            for card_entry in options.sdcard.rglob("*"):
                if not card_entry.is_file():
                    continue
                card_rel = card_entry.relative_to(options.sdcard)
                if card_rel not in rel_paths:
                    # This card file has no local counterpart — prune it.
                    try:
                        card_size = card_entry.stat().st_size
                    except OSError:
                        card_size = 0

                    try:
                        if not options.dry_run:
                            card_entry.unlink()
                        metrics.files_pruned += 1
                        metrics.bytes_pruned += card_size
                    except OSError as e:
                        err = describe_error(e)
                        metrics.errors.append({'file': str(card_entry), 'error': err})
                        _log.warning("prune failed %s: %s", card_entry, err)

    return metrics


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_sync_report(
    metrics: SyncMetrics,
    sdcard: Path,
    console=None,
) -> None:
    """Print a Rich summary panel for a completed (or dry-run) sync."""
    if console is None:
        console = _default_console

    label_suffix = " — DRY RUN (estimates)" if metrics.dry_run else ""
    border = "warn" if metrics.errors else "success"

    table = Table.grid(padding=(0, 3))
    table.add_column(justify="right", style="muted")
    table.add_column(justify="left", style="value")

    table.add_row("Files copied", f"[success]{metrics.files_copied}[/success]")
    table.add_row("Bytes copied", format_size(metrics.bytes_copied))
    table.add_row("Files skipped", str(metrics.files_skipped))

    if metrics.prune_blocked_empty_source:
        table.add_row("", "")
        table.add_row(
            "Prune",
            "[warn]SKIPPED — source was empty (safety guard)[/warn]",
        )
    elif metrics.files_pruned > 0 or metrics.prune_blocked_empty_source is False:
        table.add_row("", "")
        table.add_row("Files pruned", str(metrics.files_pruned))
        table.add_row("Bytes pruned", format_size(metrics.bytes_pruned))

    if metrics.errors:
        table.add_row("", "")
        fail_count = len(metrics.errors)
        table.add_row("Errors", f"[danger]{fail_count}[/danger]")

    headline = Text(str(sdcard), style="path", justify="center")

    console.print()
    console.print(Panel(
        Group(headline, Text(), Align.center(table)),
        title=f"[accent]SD Sync Summary{label_suffix}[/accent]",
        box=box.ROUNDED,
        border_style=border,
        padding=(1, 2),
    ))

    # Warn prominently if prune was blocked.
    if metrics.prune_blocked_empty_source:
        console.print(Panel(
            Text.from_markup(
                "[warn]⚠  Pruning was SKIPPED because the source directory contained no files.[/warn]\n"
                "Check that the source path is correct and the drive is mounted before retrying."
            ),
            title="[warn]Safety warning[/warn]",
            box=box.ROUNDED,
            border_style="warn",
            padding=(0, 2),
        ))


# ---------------------------------------------------------------------------
# CLI integration point
# ---------------------------------------------------------------------------

def run_sync(args) -> SyncMetrics:
    """Build SyncOptions from argparse-style attrs, validate, run, report.

    Expected attrs on `args`:
        source       str   -- path to local ROM library
        sdcard       str   -- path to SD card mount
        dry_run      bool
        no_prune     bool  (optional, default False)
        no_recursive bool  (optional, default False)
    """
    source = Path(args.source)
    sdcard = Path(args.sdcard)

    empty = SyncMetrics()

    if not source.exists() or not source.is_dir():
        _default_console.print(
            f"[danger]Error:[/danger] source path does not exist or is not a directory: {source}"
        )
        return empty

    if not sdcard.exists() or not sdcard.is_dir():
        _default_console.print(
            f"[danger]Error:[/danger] SD card path does not exist or is not a directory: {sdcard}"
        )
        return empty

    options = SyncOptions(
        source=source,
        sdcard=sdcard,
        dry_run=args.dry_run,
        prune=not getattr(args, "no_prune", False),
        recursive=not getattr(args, "no_recursive", False),
    )

    metrics = mirror_to_sdcard(options)
    render_sync_report(metrics, sdcard)
    return metrics
