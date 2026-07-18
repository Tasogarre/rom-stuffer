from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rom_stuffer.tui import console, box, Align, Group, Panel, Table, Text, escape
from rom_stuffer.metrics import SessionMetrics, format_size, CONSOLE_TABLE_ROW_CAP
from rom_stuffer.guards import describe_error

if TYPE_CHECKING:  # pragma: no cover - type hints only (avoids an import cycle)
    from rom_stuffer.dedup import DedupMetrics
    from rom_stuffer.planfile import DedupPlan


def generate_reports(metrics: SessionMetrics, dest_dir: str | Path) -> None:
    saved_bytes = metrics.original_size_bytes - metrics.zip_size_bytes
    ratio = (saved_bytes / metrics.original_size_bytes * 100) if metrics.original_size_bytes else 0.0

    # Summary metrics laid out as a clean two-column grid (no heavy gridlines).
    summary_table = Table.grid(padding=(0, 3))
    summary_table.add_column(justify="right", style="muted")
    summary_table.add_column(justify="left", style="value")
    summary_table.add_row("Files processed", str(metrics.total_files))
    summary_table.add_row("Successful", f"[success]{metrics.success_count}[/success]")
    fail_style = "danger" if metrics.error_count else "muted"
    summary_table.add_row("Failed", f"[{fail_style}]{metrics.error_count}[/{fail_style}]")
    summary_table.add_row("Skipped", str(len(metrics.skipped_files)))
    summary_table.add_row("", "")
    summary_table.add_row("Original size", format_size(metrics.original_size_bytes))
    summary_table.add_row("Compressed size", format_size(metrics.zip_size_bytes))
    if metrics.sd_files_synced > 0:
        summary_table.add_row("", "")
        summary_table.add_row("SD files synced", str(metrics.sd_files_synced))
        summary_table.add_row("SD data written", format_size(metrics.sd_bytes_copied))

    # Headline: space saved + ratio, front and centre.
    headline = Text(justify="center")
    headline.append(f"{format_size(saved_bytes)} saved", style="success")
    headline.append(f"   ({ratio:.0f}% smaller)", style="muted")

    title = "Session Summary" + (" — DRY RUN (estimates)" if metrics.dry_run else "")
    console.print()
    console.print(Panel(
        Group(Align.center(headline), Text(), Align.center(summary_table)),
        title=f"[accent]{title}[/accent]",
        box=box.ROUNDED,
        border_style="success" if metrics.error_count == 0 else "warn",
        padding=(1, 2),
    ))

    # Affected folders
    if metrics.affected_folders:
        folders_table = Table(
            title="Folders updated",
            box=box.SIMPLE_HEAD, title_style="accent", show_lines=False,
        )
        folders_table.add_column("Originals moved here", style="path")
        for f in sorted(metrics.affected_folders):
            folders_table.add_row(f)
        console.print(folders_table)

    # Skipped (console cap)
    if metrics.skipped_files:
        skip_table = Table(title="Skipped files", box=box.SIMPLE_HEAD, title_style="warn")
        skip_table.add_column("File", style="warn")
        skip_table.add_column("Reason", style="muted")
        for skip in metrics.skipped_files[:CONSOLE_TABLE_ROW_CAP]:
            skip_table.add_row(skip['file'], skip['reason'])
        if len(metrics.skipped_files) > CONSOLE_TABLE_ROW_CAP:
            skip_table.add_row("...", f"and {len(metrics.skipped_files) - CONSOLE_TABLE_ROW_CAP} more (see report file)")
        console.print(skip_table)

    # Errors (console cap)
    if metrics.errors:
        error_table = Table(title="Errors", box=box.SIMPLE_HEAD, title_style="danger")
        error_table.add_column("File", style="danger")
        error_table.add_column("Message", style="muted")
        for err in metrics.errors[:CONSOLE_TABLE_ROW_CAP]:
            error_table.add_row(err['file'], err['error'])
        if len(metrics.errors) > CONSOLE_TABLE_ROW_CAP:
            error_table.add_row("...", f"and {len(metrics.errors) - CONSOLE_TABLE_ROW_CAP} more (see report file)")
        console.print(error_table)

    # Write plain-text log
    log_path = Path(dest_dir) / "rom_stuffer_report.txt"
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("=== ROM STUFFER REPORT ===\n")
            if metrics.dry_run:
                f.write("*** DRY RUN — no files were modified; sizes are estimates ***\n")
            f.write("\n--- SUMMARY ---\n")
            f.write(f"Total Files Processed: {metrics.total_files}\n")
            f.write(f"Successful: {metrics.success_count}\n")
            f.write(f"Failed: {metrics.error_count}\n")
            estimate_note = " (estimated)" if metrics.dry_run else ""
            f.write(f"Original Size: {format_size(metrics.original_size_bytes)}\n")
            f.write(f"Compressed Size: {format_size(metrics.zip_size_bytes)}{estimate_note}\n")
            f.write(f"Total Space Saved: {format_size(saved_bytes)}{estimate_note}\n")
            if metrics.sd_files_synced > 0:
                f.write(f"SD Card Files Synced: {metrics.sd_files_synced}\n")
                f.write(f"SD Card Data Written: {format_size(metrics.sd_bytes_copied)}\n")
            f.write("\n--- AFFECTED FOLDERS ---\n")
            for folder in sorted(metrics.affected_folders):
                f.write(f"{folder}\n")
            f.write("\n--- SKIPPED FILES ---\n")
            if not metrics.skipped_files:
                f.write("No files skipped.\n")
            else:
                for skip in metrics.skipped_files:
                    f.write(f"{skip['file']}: {skip['reason']}\n")
            f.write("\n--- ERRORS ---\n")
            if not metrics.errors:
                f.write("No errors occurred.\n")
            else:
                for err in metrics.errors:
                    f.write(f"{err['file']}: {err['error']}\n")
        console.print(f"[bold green]Report saved to: {log_path}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to write log file: {describe_error(e)}[/bold red]")


# =========================================================================== #
# Dedup report (U9)
# =========================================================================== #

def _format_dedup_summary_panel(plan: "DedupPlan", metrics: "DedupMetrics") -> Panel:
    """Build the themed summary Panel for dedup results.

    Border is ``success`` when there were no errors, ``warn`` otherwise. The title
    is labelled ``DRY RUN (estimates)`` when ``metrics.dry_run`` is set.
    """
    grid = Table.grid(padding=(0, 3))
    grid.add_column(justify="right", style="muted")
    grid.add_column(justify="left", style="value")
    grid.add_row("Duplicate groups", str(metrics.groups_found))
    grid.add_row("Files removed", str(metrics.files_removed))
    grid.add_row("Space reclaimed", format_size(metrics.bytes_reclaimed))
    if metrics.sd_files_pruned > 0:
        grid.add_row("SD files pruned", str(metrics.sd_files_pruned))
        grid.add_row("SD data freed", format_size(metrics.sd_bytes_pruned))
    if metrics.errors:
        grid.add_row("Errors", f"[danger]{len(metrics.errors)}[/danger]")

    headline = Text(justify="center")
    headline.append(f"{format_size(metrics.bytes_reclaimed)} reclaimed", style="success")
    headline.append(f"   ({metrics.files_removed} removed)", style="muted")

    title = "Dedup Summary" + (" — DRY RUN (estimates)" if metrics.dry_run else "")
    return Panel(
        Group(Align.center(headline), Text(), Align.center(grid)),
        title=f"[accent]{title}[/accent]",
        box=box.ROUNDED,
        border_style="success" if not metrics.errors else "warn",
        padding=(1, 2),
    )


def _format_keeper_table(plan: "DedupPlan") -> Table:
    """Build the keeper -> removal table (kept path in ``success``, removed in
    ``muted``), one row per removal, capped at ``CONSOLE_TABLE_ROW_CAP`` rows."""
    table = Table(
        title="Kept vs removed", box=box.SIMPLE_HEAD, title_style="accent",
    )
    table.add_column("Kept", style="success", overflow="fold")
    table.add_column("Removed", style="muted", overflow="fold")

    rows = 0
    total_pairs = 0
    for group in plan.groups:
        if group.skipped:
            continue
        total_pairs += len(group.removals)

    for group in plan.groups:
        if group.skipped:
            continue
        for removal in group.removals:
            if rows >= CONSOLE_TABLE_ROW_CAP:
                table.add_row(
                    "...", f"and {total_pairs - CONSOLE_TABLE_ROW_CAP} more (see report file)"
                )
                return table
            table.add_row(escape(str(group.keeper)), escape(str(removal)))
            rows += 1
    return table


def generate_dedup_report(
    plan: "DedupPlan",
    metrics: "DedupMetrics",
    dest_dir: str | Path,
) -> None:
    """Render dedup results to the console and append a ``--- DEDUP ---`` section
    to ``<dest_dir>/rom_stuffer_report.txt``.

    Console: a themed summary panel, a capped keeper->removed table, and an error
    table when there were failures. File: the same information, uncapped, with all
    paths written via ``str()`` (single backslash on Windows -- never repr'd).
    Dry-run runs are labelled. Rendering / write failures fall back to plain text.
    """
    try:
        console.print()
        console.print(_format_dedup_summary_panel(plan, metrics))
        if any(not g.skipped and g.removals for g in plan.groups):
            console.print(_format_keeper_table(plan))
        if metrics.errors:
            error_table = Table(title="Errors", box=box.SIMPLE_HEAD, title_style="danger")
            error_table.add_column("File", style="danger")
            error_table.add_column("Message", style="muted")
            for err in metrics.errors[:CONSOLE_TABLE_ROW_CAP]:
                error_table.add_row(escape(str(err["file"])), escape(str(err["error"])))
            if len(metrics.errors) > CONSOLE_TABLE_ROW_CAP:
                error_table.add_row(
                    "...", f"and {len(metrics.errors) - CONSOLE_TABLE_ROW_CAP} more (see report file)"
                )
            console.print(error_table)
    except Exception as e:  # pragma: no cover - Rich fallback, never abort a run
        console.print(f"Dedup summary: {metrics.files_removed} removed, "
                      f"{format_size(metrics.bytes_reclaimed)} reclaimed "
                      f"({describe_error(e)})")

    log_path = Path(dest_dir) / "rom_stuffer_report.txt"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n--- DEDUP ---\n")
            if metrics.dry_run:
                f.write("*** DRY RUN — no files were removed; sizes are estimates ***\n")
            f.write(f"Duplicate Groups: {metrics.groups_found}\n")
            f.write(f"Files Removed: {metrics.files_removed}\n")
            f.write(f"Space Reclaimed: {format_size(metrics.bytes_reclaimed)}\n")
            if metrics.sd_files_pruned > 0:
                f.write(f"SD Files Pruned: {metrics.sd_files_pruned}\n")
                f.write(f"SD Data Freed: {format_size(metrics.sd_bytes_pruned)}\n")
            f.write("\nKept vs removed:\n")
            any_row = False
            for group in plan.groups:
                if group.skipped or not group.removals:
                    continue
                for removal in group.removals:
                    any_row = True
                    f.write(f"KEEP   {group.keeper}\n")
                    f.write(f"REMOVE {removal}\n")
            if not any_row:
                f.write("No files removed.\n")
            if metrics.errors:
                f.write("\nDedup errors:\n")
                for err in metrics.errors:
                    f.write(f"{err['file']}: {err['error']}\n")
        console.print(f"[bold green]Report saved to: {log_path}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to write log file: {describe_error(e)}[/bold red]")
