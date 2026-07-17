from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from rom_stuffer.tui import console, Prompt
from rom_stuffer.metrics import SessionMetrics, SCAN_FOLDER_SAMPLE
from rom_stuffer.guards import SUPPORTED_EXTENSIONS, exclusion_reason, describe_error


def _build_worklist_interactive(
    source_path: Path, recursive: bool, metrics: SessionMetrics
) -> list[Path]:
    """Scan, group by extension, prompt per extension, and gather all confirmed files
    into a single list. Prompting up front (rather than per-batch) is what lets the
    whole job be captured in one resumable manifest."""
    console.print(
        f"Scanning for supported cartridge ROMs in [cyan]'{source_path}'[/cyan] "
        f"(Recursive: {recursive})..."
    )
    grouped_files: dict[str, list[Path]] = defaultdict(list)
    scan_iter = source_path.rglob('*') if recursive else source_path.glob('*')
    for p in scan_iter:
        try:
            if p.is_file():
                ext = p.suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    size = None
                    if ext == '.bin':
                        try:
                            size = p.stat().st_size
                        except OSError:
                            size = None
                    reason = exclusion_reason(p, ext, size, source_path)
                    if reason:
                        metrics.skipped_files.append({'file': str(p.name), 'reason': reason})
                    else:
                        grouped_files[ext].append(p)
                else:
                    metrics.skipped_files.append({'file': str(p.name), 'reason': f"Unsupported extension: {p.suffix}"})
        except OSError as e:
            metrics.skipped_files.append({'file': str(p.name), 'reason': f"Unreadable: {describe_error(e)}"})

    disc_excluded = [s for s in metrics.skipped_files if 'disc' in s['reason'] or 'BIOS' in s['reason']]
    if disc_excluded:
        console.print(
            f"[warn]Protected {len(disc_excluded)} disc-image / BIOS file(s)[/warn] "
            f"[muted]— CD-based systems (PS1, Saturn, Dreamcast…) and BIOS are never "
            f"compressed or moved. See the report for the list.[/muted]"
        )

    if not grouped_files:
        console.print("[yellow]No supported cartridge ROM files found.[/yellow]")
        return []

    selected: list[Path] = []
    for ext, files in sorted(grouped_files.items()):
        folders = sorted(set(f.parent for f in files))
        console.print()
        console.print(
            f"[brand]{ext}[/brand]  [muted]·[/muted]  "
            f"[value]{len(files)}[/value] files in [value]{len(folders)}[/value] folders"
        )
        for folder in folders[:SCAN_FOLDER_SAMPLE]:
            console.print(f"  [muted]•[/muted] [path]{folder}[/path]")
        truncated = len(folders) - SCAN_FOLDER_SAMPLE
        if truncated > 0:
            console.print(f"  [muted]• … and {truncated} more (type 'a' to list them all)[/muted]")

        # Prompt with an optional 'a' to print every folder, then re-ask.
        while True:
            choices = ["y", "n", "a"] if truncated > 0 else ["y", "n"]
            answer = Prompt.ask(
                f"  Compress and move these [brand]{ext}[/brand] files?",
                choices=choices, default="y", show_choices=False,
            )
            if answer == "a":
                for folder in folders:
                    console.print(f"  [muted]•[/muted] [path]{folder}[/path]")
                continue
            break

        if answer == "y":
            selected.extend(files)
        else:
            console.print(f"  [warn]Skipping {ext}[/warn]")
            for f in files:
                metrics.skipped_files.append({'file': str(f.name), 'reason': f"Extension {ext} skipped by user"})
    return selected
