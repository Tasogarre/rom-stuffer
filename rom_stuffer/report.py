from __future__ import annotations

from pathlib import Path

from rom_stuffer.tui import console, box, Align, Group, Panel, Table, Text
from rom_stuffer.metrics import SessionMetrics, format_size, CONSOLE_TABLE_ROW_CAP
from rom_stuffer.guards import describe_error


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
