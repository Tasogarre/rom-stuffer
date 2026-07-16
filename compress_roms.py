from __future__ import annotations

import argparse
import os
import shutil
import zipfile
from pathlib import Path
import sys
from collections import defaultdict

try:
    from rich.console import Console
    from rich.markup import escape
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import (
        Progress, SpinnerColumn, TextColumn, BarColumn,
        TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn,
    )
    from rich.prompt import Confirm, Prompt
    from rich import print as rprint
except ImportError:
    print("Error: The 'rich' library is required. Please install it using: pip install -r requirements.txt")
    sys.exit(1)

console = Console()

# Named constants
FAST_COPY_BUFFER_BYTES: int = 4 * 1024 * 1024   # 4 MB: suits typical SD/flash page sizes
SCAN_FOLDER_SAMPLE: int = 5
CONSOLE_TABLE_ROW_CAP: int = 20
DRY_RUN_COMPRESSION_ESTIMATE: float = 0.4        # rough DEFLATE ratio on ROM data

SUPPORTED_EXTENSIONS: set = {
    # Nintendo
    '.nes', '.sfc', '.smc', '.fig', '.swc', '.gb', '.gbc', '.gba', '.fds',
    '.vb', '.vboy', '.min', '.mgw',
    # Sega
    '.bin', '.gen', '.md', '.smd', '.sms', '.gg', '.sg', '.32x',
    # NEC
    '.pce', '.sgx',
    # Atari
    '.a26', '.a52', '.a78', '.j64', '.lnx', '.atr', '.atx', '.xfd', '.xex', '.cas', '.st',
    # Commodore
    '.crt', '.d64', '.t64', '.prg', '.tap', '.d81', '.g64',
    # Amiga
    '.adf', '.dms', '.fdi', '.ipf', '.hdf', '.hdz',
    # Home Computers
    '.msx', '.rom', '.dsk', '.z80', '.tzx', '.cdt',
    # Other Consoles / Handhelds
    '.ws', '.wsc', '.ngp', '.ngc', '.col', '.int', '.vec', '.chf', '.o2',
    # Note: CD-based systems (PSX, Sega CD, Saturn) are EXCLUDED. Emulators stream
    # audio tracks from CD images, and zip extraction overhead causes massive stuttering.
    # Note: N64 and NDS are EXCLUDED due to size and performance overhead on low-end devices.
    # Note: MAME arcade ROMs are already zipped by default, so they are excluded.
}


class SessionMetrics:
    def __init__(self) -> None:
        self.total_files: int = 0
        self.original_size_bytes: int = 0
        self.zip_size_bytes: int = 0
        self.success_count: int = 0
        self.error_count: int = 0
        self.sd_files_synced: int = 0
        self.sd_bytes_copied: int = 0
        self.affected_folders: set = set()
        self.errors: list = []
        self.skipped_files: list = []
        self.dry_run: bool = False


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def fast_sd_copy(
    source_path: Path,
    dest_path: Path,
    buffer_size: int = FAST_COPY_BUFFER_BYTES,
) -> None:
    """Copy using a large sequential buffer to maximise sustained write speed on flash media.
    Flushes and fsyncs so the data is durable on the card, not just in OS cache."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(source_path, 'rb') as fsrc, open(dest_path, 'wb') as fdst:
        shutil.copyfileobj(fsrc, fdst, length=buffer_size)
        fdst.flush()
        os.fsync(fdst.fileno())


def build_zip_path(file_path: Path, claimed: set[Path]) -> Path:
    """Return the target .zip path for file_path.

    Uses Game.zip in the common case; falls back to Game_gb.zip / Game_gbc.zip
    when the default name is already claimed by another file in the current batch.
    The claimed set is updated in-place.
    """
    default = file_path.with_suffix('.zip')
    if default not in claimed:
        claimed.add(default)
        return default
    stem_ext = f"{file_path.stem}_{file_path.suffix.lstrip('.')}"
    candidate = file_path.parent / f"{stem_ext}.zip"
    counter = 1
    while candidate in claimed:
        candidate = file_path.parent / f"{stem_ext}_{counter}.zip"
        counter += 1
    claimed.add(candidate)
    return candidate


def compress_batch(
    files_to_process: list[Path],
    source_path: Path,
    dest_path: Path,
    metrics: SessionMetrics,
    sdcard_path: Path | None = None,
    compress_level: int = 6,
) -> None:
    dry_run = metrics.dry_run

    # Single stat pass — one syscall per file, result reused throughout the loop.
    sized: list[tuple[Path, int]] = []
    total_bytes = 0
    for f in files_to_process:
        try:
            sz = f.stat().st_size
        except OSError:
            sz = 0
        sized.append((f, sz))
        total_bytes += sz

    # Track which .zip paths this batch has already claimed, to detect within-batch
    # name collisions (e.g. Game.gb and Game.gbc in the same folder).
    claimed_zips: set[Path] = set()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        overall_task = progress.add_task("[cyan]Processing files...", total=len(sized))
        byte_task = progress.add_task("[green]Data processed...", total=total_bytes)

        for file_path, original_size in sized:
            safe_name = escape(file_path.name)
            zip_path: Path | None = None

            try:
                rel_path = file_path.relative_to(source_path)
                original_dest = dest_path / rel_path
                zip_path = build_zip_path(file_path, claimed_zips)

                if not dry_run:
                    original_dest.parent.mkdir(parents=True, exist_ok=True)
                    # Write to .tmp then atomically replace — prevents a corrupt .zip
                    # from being left behind if compression fails mid-write.
                    tmp_zip = zip_path.with_name(zip_path.name + '.tmp')
                    try:
                        with zipfile.ZipFile(
                            tmp_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=compress_level
                        ) as zipf:
                            zipf.write(file_path, file_path.name)
                        tmp_zip.replace(zip_path)
                    except Exception:
                        tmp_zip.unlink(missing_ok=True)
                        raise
                    zip_size = zip_path.stat().st_size
                else:
                    zip_size = int(original_size * DRY_RUN_COMPRESSION_ESTIMATE)

                # SD Card Reconciliation.
                # Delete-before-copy is intentional: the card may be nearly full and
                # cannot hold both the original and the new zip at the same time.
                # The authoritative zip already exists in the source directory, so the
                # SD entry is always recoverable from there on a re-run.
                if sdcard_path:
                    progress.update(
                        overall_task,
                        description=f"[magenta]Syncing {safe_name} to SD...[/magenta]",
                    )
                    sd_equivalent_original = sdcard_path / rel_path
                    # Mirror the local zip filename (may be disambiguated).
                    sd_equivalent_zip = sdcard_path / rel_path.parent / zip_path.name

                    if not dry_run:
                        sd_equivalent_original.unlink(missing_ok=True)
                        fast_sd_copy(zip_path, sd_equivalent_zip)
                    metrics.sd_files_synced += 1
                    metrics.sd_bytes_copied += zip_size

                if not dry_run:
                    shutil.move(str(file_path), str(original_dest))

                metrics.original_size_bytes += original_size
                metrics.zip_size_bytes += zip_size
                metrics.success_count += 1
                metrics.total_files += 1
                metrics.affected_folders.add(str(original_dest.parent))

            except Exception as e:
                metrics.error_count += 1
                metrics.errors.append({'file': str(file_path.name), 'error': str(e)})

            finally:
                progress.update(
                    overall_task, description=f"[cyan]Processed {safe_name}..."
                )
                progress.advance(overall_task)
                progress.advance(byte_task, advance=original_size)


def generate_reports(metrics: SessionMetrics, dest_dir: str | Path) -> None:
    dry_run_label = " (DRY RUN — sizes are estimates)" if metrics.dry_run else ""

    # Affected Folders
    folders_table = Table(
        title="Affected Folders (Where uncompressed files were moved)", show_lines=True
    )
    folders_table.add_column("Folder Path", style="cyan")
    for f in sorted(metrics.affected_folders):
        folders_table.add_row(f)

    # Summary
    summary_table = Table(title=f"Session Summary{dry_run_label}", show_lines=True)
    summary_table.add_column("Metric", style="bold green")
    summary_table.add_column("Value", style="bold yellow")
    saved_bytes = metrics.original_size_bytes - metrics.zip_size_bytes
    summary_table.add_row("Total Files Processed", str(metrics.total_files))
    summary_table.add_row("Successful", str(metrics.success_count))
    summary_table.add_row("Failed", str(metrics.error_count))
    summary_table.add_row("Original Size", format_size(metrics.original_size_bytes))
    summary_table.add_row("Compressed Size", format_size(metrics.zip_size_bytes))
    summary_table.add_row("Total Space Saved", format_size(saved_bytes))
    if metrics.sd_files_synced > 0:
        summary_table.add_row("SD Card Files Synced", str(metrics.sd_files_synced))
        summary_table.add_row("SD Card Data Written", format_size(metrics.sd_bytes_copied))
    summary_table.add_row("Files Skipped", str(len(metrics.skipped_files)))

    # Skipped Files (console cap)
    skip_table = None
    if metrics.skipped_files:
        skip_table = Table(title="Skipped Files", show_lines=True)
        skip_table.add_column("File", style="yellow")
        skip_table.add_column("Reason", style="yellow")
        for skip in metrics.skipped_files[:CONSOLE_TABLE_ROW_CAP]:
            skip_table.add_row(skip['file'], skip['reason'])
        if len(metrics.skipped_files) > CONSOLE_TABLE_ROW_CAP:
            skip_table.add_row("...", f"and {len(metrics.skipped_files) - CONSOLE_TABLE_ROW_CAP} more (see report file)")

    # Errors (console cap)
    error_table = None
    if metrics.errors:
        error_table = Table(title="Error Report", show_lines=True)
        error_table.add_column("File", style="red")
        error_table.add_column("Error Message", style="red")
        for err in metrics.errors[:CONSOLE_TABLE_ROW_CAP]:
            error_table.add_row(err['file'], err['error'])
        if len(metrics.errors) > CONSOLE_TABLE_ROW_CAP:
            error_table.add_row("...", f"and {len(metrics.errors) - CONSOLE_TABLE_ROW_CAP} more (see report file)")

    console.print()
    if metrics.affected_folders:
        console.print(folders_table)
    console.print(summary_table)
    if skip_table:
        console.print(skip_table)
    if error_table:
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
        console.print(f"[bold red]Failed to write log file: {e}[/bold red]")


def compress_roms(
    source_dir: str,
    file_type: str | None,
    dest_dir: str,
    sdcard_dir: str | None = None,
    dry_run: bool = False,
    recursive: bool = True,
    compress_level: int = 6,
) -> None:
    source_path = Path(source_dir).resolve()
    dest_path = Path(dest_dir).resolve()

    if not source_path.exists() or not source_path.is_dir():
        console.print(f"[bold red]Error: Source directory '{source_path}' does not exist.[/bold red]")
        sys.exit(1)

    # Reject dest == source or either nested inside the other.
    if dest_path == source_path or source_path in dest_path.parents or dest_path in source_path.parents:
        console.print(
            "[bold red]Error: destination must differ from source and must not "
            "be nested inside it (or vice versa).[/bold red]"
        )
        sys.exit(1)

    console.print(Panel(
        "[bold yellow]WARNING:[/bold yellow] This script should ONLY be used for cartridge-based systems.\n"
        "DO NOT use this for CD-based games (PS1, Saturn, Sega CD).\n"
        "Use CHD format for disc-based games instead.",
        title="ROM Stuffer",
    ))

    dest_path.mkdir(parents=True, exist_ok=True)
    metrics = SessionMetrics()
    metrics.dry_run = dry_run

    if dry_run:
        console.print(Panel(
            "[bold cyan]DRY RUN MODE ENABLED:[/bold cyan] No files will be modified.",
            title="Dry Run",
        ))

    # Validate and normalise --type
    if file_type:
        if not file_type.startswith('.'):
            file_type = '.' + file_type
        file_type = file_type.lower()
        if file_type not in SUPPORTED_EXTENSIONS:
            console.print(
                f"[bold red]Error: '{file_type}' is not a recognised supported extension. "
                f"Refusing to process to prevent accidental data loss. "
                f"Use --help to see the full supported list.[/bold red]"
            )
            sys.exit(1)

    # Resolve SD card path
    sdcard_path: Path | None = None
    if sdcard_dir:
        sdcard_path = Path(sdcard_dir).resolve()
        if not sdcard_path.exists() or not sdcard_path.is_dir():
            console.print(f"[bold red]Error: SD Card directory '{sdcard_path}' does not exist.[/bold red]")
            sys.exit(1)
        console.print(f"[bold green]SD Card Sync Enabled:[/bold green] Pointing to {sdcard_path}\n")
    elif not file_type:
        if Confirm.ask("\nDo you want to sync the compressed ROMs directly to an SD Card after compressing?"):
            sd_input = Prompt.ask("Enter the path to the SD Card (e.g. F:\\ or /Volumes/SDCARD)").strip()
            if sd_input:
                sdcard_path = Path(sd_input).resolve()
                if not sdcard_path.exists() or not sdcard_path.is_dir():
                    console.print(f"[bold red]Error: SD Card directory '{sdcard_path}' does not exist.[/bold red]")
                    sys.exit(1)
                console.print(f"[bold green]SD Card Sync Enabled:[/bold green] Pointing to {sdcard_path}\n")

    # Headless / --type mode
    if file_type:
        console.print(
            f"Scanning for [cyan]'{file_type}'[/cyan] files in "
            f"[cyan]'{source_path}'[/cyan] (Recursive: {recursive})..."
        )
        files_to_process: list[Path] = []
        scan_iter = source_path.rglob('*') if recursive else source_path.glob('*')
        for p in scan_iter:
            try:
                if p.is_file() and p.suffix.lower() == file_type:
                    files_to_process.append(p)
            except OSError as e:
                metrics.skipped_files.append({'file': str(p.name), 'reason': f"Unreadable (OS Error): {e}"})

        if not files_to_process:
            console.print("[yellow]No files found matching the specified type.[/yellow]")
            return

        console.print(f"Found [bold]{len(files_to_process)}[/bold] files to process.")
        compress_batch(files_to_process, source_path, dest_path, metrics, sdcard_path, compress_level)
        generate_reports(metrics, dest_dir)
        return

    # Interactive mode
    console.print(f"Scanning for supported cartridge ROMs in [cyan]'{source_path}'[/cyan] (Recursive: {recursive})...")
    grouped_files: dict[str, list[Path]] = defaultdict(list)
    scan_iter = source_path.rglob('*') if recursive else source_path.glob('*')
    for p in scan_iter:
        try:
            if p.is_file():
                ext = p.suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    grouped_files[ext].append(p)
                else:
                    metrics.skipped_files.append({'file': str(p.name), 'reason': f"Unsupported extension: {p.suffix}"})
        except OSError as e:
            metrics.skipped_files.append({'file': str(p.name), 'reason': f"Unreadable (OS Error): {e}"})

    if not grouped_files:
        console.print("[yellow]No supported ROM files found.[/yellow]")
        return

    for ext, files in sorted(grouped_files.items()):
        console.print()
        console.print(f"[bold magenta]--- Extension: {ext} ---[/bold magenta]")
        folders = set(f.parent for f in files)
        console.print(f"Found [bold]{len(files)}[/bold] files in [bold]{len(folders)}[/bold] folders.")
        sample_folders = list(folders)[:SCAN_FOLDER_SAMPLE]
        for folder in sample_folders:
            console.print(f"  - {folder}")
        if len(folders) > SCAN_FOLDER_SAMPLE:
            console.print(f"  - ... and {len(folders) - SCAN_FOLDER_SAMPLE} more")

        if Confirm.ask(f"Do you want to compress and move these [bold]{ext}[/bold] files?"):
            compress_batch(files, source_path, dest_path, metrics, sdcard_path, compress_level)
        else:
            console.print(f"[yellow]Skipping {ext} files.[/yellow]")
            for f in files:
                metrics.skipped_files.append({'file': str(f.name), 'reason': f"Extension {ext} skipped by user"})

    console.print("\n[bold green]Finished processing all batches![/bold green]")
    generate_reports(metrics, dest_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Recursively compress ROM files to .zip and move the originals.",
        epilog=(
            "WARNING: Only use this script for cartridge-based systems (NES, SNES, GBA, etc). "
            "CD-based games should not be zipped."
        ),
    )
    parser.add_argument("-s", "--source", required=False, help="Source directory to scan for ROMs")
    parser.add_argument(
        "-t", "--type", required=False,
        help="Target a specific file extension and bypass interactive prompts (e.g. .gba)",
    )
    parser.add_argument("-d", "--dest", required=False, help="Destination directory to move original files to")
    parser.add_argument(
        "-sd", "--sdcard", required=False,
        help="SD card directory to sync compressed files to (delete-before-copy; card may be nearly full)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what will happen without modifying any files. Sizes in the report are estimates.",
    )
    parser.add_argument(
        "--no-recursive", action="store_true", help="Disable recursive sub-folder scanning."
    )
    parser.add_argument(
        "-l", "--level", type=int, default=6, choices=range(1, 10), metavar="1-9",
        help=(
            "DEFLATE compression level (1=fastest, 9=smallest). "
            "Default 6 (Normal) is the recommended balance for RetroArch handhelds."
        ),
    )

    args = parser.parse_args()

    provided_args = [args.source, args.dest, args.type, args.sdcard, args.dry_run, args.no_recursive]
    interactive_mode = not any(provided_args)

    source = args.source
    if not source:
        source = Prompt.ask("Enter the source directory to scan for ROMs").strip()

    dest = args.dest
    if not dest:
        dest = Prompt.ask("Enter the destination directory to move original files to").strip()

    dry_run = args.dry_run
    if interactive_mode and not dry_run:
        dry_run = Confirm.ask("Do you want to run in DRY-RUN mode (preview only)?", default=False)

    recursive = not args.no_recursive
    if interactive_mode and not args.no_recursive:
        recursive = Confirm.ask("Do you want to scan sub-folders recursively?", default=True)

    compress_roms(source, args.type, dest, args.sdcard, dry_run, recursive, args.level)
