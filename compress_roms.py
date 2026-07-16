import argparse
import os
import shutil
import zipfile
from pathlib import Path
import sys
from collections import defaultdict

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.prompt import Confirm
    from rich import print as rprint
except ImportError:
    print("Error: The 'rich' library is required. Please install it using: pip install -r requirements.txt")
    sys.exit(1)

console = Console()

SUPPORTED_EXTENSIONS = {
    # Nintendo
    '.nes', '.sfc', '.smc', '.fig', '.swc', '.gb', '.gbc', '.gba', '.fds', 
    # Sega
    '.bin', '.gen', '.md', '.smd', '.sms', '.gg', 
    # Atari
    '.a26', '.a52', '.a78', '.j64', '.lnx', '.atr', '.atx', '.xfd', '.xex', '.cas', '.st',
    # Amiga
    '.adf', '.dms', '.fdi', '.ipf', '.hdf', '.hdz',
    # Other
    '.ws', '.wsc', '.ngp', '.ngc'
    # Note: N64 removed due to performance overhead on low-end devices.
    # Note: MAME arcade ROMs are already zipped by default, so they are excluded.
}

class SessionMetrics:
    def __init__(self):
        self.total_files = 0
        self.original_size_bytes = 0
        self.zip_size_bytes = 0
        self.success_count = 0
        self.error_count = 0
        self.sd_files_synced = 0
        self.sd_bytes_copied = 0
        self.affected_folders = set()
        self.errors = []

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def fast_sd_copy(source_path, dest_path, buffer_size=16 * 1024 * 1024):
    """
    Copies a file using a large buffer (default 16MB) to maximize 
    sequential write speeds on flash media like SD cards, avoiding OS caching overhead.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(source_path, 'rb') as fsrc:
        with open(dest_path, 'wb') as fdst:
            shutil.copyfileobj(fsrc, fdst, length=buffer_size)

def compress_batch(files_to_process, source_path, dest_path, metrics, sdcard_path=None):
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Compressing...", total=len(files_to_process))

        for file_path in files_to_process:
            try:
                rel_path = file_path.relative_to(source_path)
                original_dest = dest_path / rel_path
                original_dest.parent.mkdir(parents=True, exist_ok=True)
                zip_path = file_path.with_suffix('.zip')
                
                original_size = file_path.stat().st_size

                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(file_path, file_path.name)
                    
                zip_size = zip_path.stat().st_size

                # SD Card Reconciliation Logic
                if sdcard_path:
                    progress.update(task, description=f"[magenta]Syncing {file_path.name} to SD...[/magenta]")
                    sd_equivalent_original = sdcard_path / rel_path
                    sd_equivalent_zip = sd_equivalent_original.with_suffix('.zip')
                    
                    # Delete original on SD card if it exists
                    if sd_equivalent_original.exists():
                        sd_equivalent_original.unlink()
                        
                    # Fast copy the zip to SD card
                    fast_sd_copy(zip_path, sd_equivalent_zip)
                    metrics.sd_files_synced += 1
                    metrics.sd_bytes_copied += zip_size

                shutil.move(str(file_path), str(original_dest))
                
                metrics.original_size_bytes += original_size
                metrics.zip_size_bytes += zip_size
                metrics.success_count += 1
                metrics.total_files += 1
                metrics.affected_folders.add(str(original_dest.parent))
                
            except Exception as e:
                metrics.error_count += 1
                metrics.errors.append({'file': str(file_path.name), 'error': str(e)})
            
            progress.update(task, description="[cyan]Compressing...")
            progress.advance(task)

def generate_reports(metrics, dest_dir):
    # 1. Affected Folders Table
    folders_table = Table(title="Affected Folders (Where uncompressed files were moved)", show_lines=True)
    folders_table.add_column("Folder Path", style="cyan")
    for f in sorted(metrics.affected_folders):
        folders_table.add_row(f)

    # 2. Summary Report Table
    summary_table = Table(title="Session Summary", show_lines=True)
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

    # 3. Error Report Table
    error_table = None
    if metrics.errors:
        error_table = Table(title="Error Report", show_lines=True)
        error_table.add_column("File", style="red")
        error_table.add_column("Error Message", style="red")
        for err in metrics.errors:
            error_table.add_row(err['file'], err['error'])

    # Print to console
    console.print()
    if metrics.affected_folders:
        console.print(folders_table)
    console.print(summary_table)
    if error_table:
        console.print(error_table)

    # Write to log file
    log_path = Path(dest_dir) / "rom_stuffer_report.txt"
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("=== ROM STUFFER REPORT ===\n\n")
            
            f.write("--- SUMMARY ---\n")
            f.write(f"Total Files Processed: {metrics.total_files}\n")
            f.write(f"Successful: {metrics.success_count}\n")
            f.write(f"Failed: {metrics.error_count}\n")
            f.write(f"Original Size: {format_size(metrics.original_size_bytes)}\n")
            f.write(f"Compressed Size: {format_size(metrics.zip_size_bytes)}\n")
            f.write(f"Total Space Saved: {format_size(saved_bytes)}\n")
            if metrics.sd_files_synced > 0:
                f.write(f"SD Card Files Synced: {metrics.sd_files_synced}\n")
                f.write(f"SD Card Data Written: {format_size(metrics.sd_bytes_copied)}\n")
            f.write("\n")
            
            f.write("--- AFFECTED FOLDERS ---\n")
            for folder in sorted(metrics.affected_folders):
                f.write(f"{folder}\n")
            f.write("\n")
            
            f.write("--- ERRORS ---\n")
            if not metrics.errors:
                f.write("No errors occurred.\n")
            else:
                for err in metrics.errors:
                    f.write(f"{err['file']}: {err['error']}\n")
                    
        console.print(f"[bold green]Report saved to: {log_path}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to write log file: {e}[/bold red]")

def compress_roms(source_dir, file_type, dest_dir, sdcard_dir=None):
    source_path = Path(source_dir).resolve()
    dest_path = Path(dest_dir).resolve()

    if not source_path.exists() or not source_path.is_dir():
        console.print(f"[bold red]Error: Source directory '{source_path}' does not exist.[/bold red]")
        sys.exit(1)

    console.print(Panel("[bold yellow]WARNING:[/bold yellow] This script should ONLY be used for cartridge-based systems.\nDO NOT use this for CD-based games (PS1, Saturn, Sega CD).\nUse CHD format for disc-based games instead.", title="ROM Stuffer"))

    dest_path.mkdir(parents=True, exist_ok=True)
    metrics = SessionMetrics()
    
    sdcard_path = None
    if sdcard_dir:
        sdcard_path = Path(sdcard_dir).resolve()
        if not sdcard_path.exists() or not sdcard_path.is_dir():
            console.print(f"[bold red]Error: SD Card directory '{sdcard_path}' does not exist.[/bold red]")
            sys.exit(1)
        console.print(f"[bold green]SD Card Sync Enabled:[/bold green] Pointing to {sdcard_path}\n")
    elif not file_type:
        if Confirm.ask("\nDo you want to sync the compressed ROMs directly to an SD Card after compressing?"):
            sd_input = input("Enter the path to the SD Card (e.g., F:\\ or /Volumes/SDCARD): ").strip()
            if sd_input:
                sdcard_path = Path(sd_input).resolve()
                if not sdcard_path.exists() or not sdcard_path.is_dir():
                    console.print(f"[bold red]Error: SD Card directory '{sdcard_path}' does not exist.[/bold red]")
                    sys.exit(1)
                console.print(f"[bold green]SD Card Sync Enabled:[/bold green] Pointing to {sdcard_path}\n")

    if file_type:
        if not file_type.startswith('.'):
            file_type = '.' + file_type
        console.print(f"Scanning for [cyan]'{file_type}'[/cyan] files recursively in [cyan]'{source_path}'[/cyan]...")
        files_to_process = list(source_path.rglob(f"*{file_type}"))
        
        if not files_to_process:
            console.print("[yellow]No files found matching the specified type.[/yellow]")
            return

        console.print(f"Found [bold]{len(files_to_process)}[/bold] files to process.")
        compress_batch(files_to_process, source_path, dest_path, metrics, sdcard_path)
        generate_reports(metrics, dest_dir)
        return

    # Interactive mode
    console.print(f"Scanning for supported cartridge ROMs recursively in [cyan]'{source_path}'[/cyan]...")
    
    grouped_files = defaultdict(list)
    for p in source_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            grouped_files[p.suffix.lower()].append(p)

    if not grouped_files:
        console.print("[yellow]No supported ROM files found.[/yellow]")
        return

    for ext, files in sorted(grouped_files.items()):
        console.print()
        console.print(f"[bold magenta]--- Extension: {ext} ---[/bold magenta]")
        folders = set(f.parent for f in files)
        console.print(f"Found [bold]{len(files)}[/bold] files in [bold]{len(folders)}[/bold] folders.")
        
        sample_folders = list(folders)[:5]
        for folder in sample_folders:
            console.print(f"  - {folder}")
        if len(folders) > 5:
            console.print(f"  - ... and {len(folders) - 5} more")

        if Confirm.ask(f"Do you want to compress and move these [bold]{ext}[/bold] files?"):
            compress_batch(files, source_path, dest_path, metrics, sdcard_path)
        else:
            console.print(f"[yellow]Skipping {ext} files.[/yellow]")

    console.print("\n[bold green]Finished processing all batches![/bold green]")
    generate_reports(metrics, dest_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Recursively compress ROM files to .zip and move the originals.",
        epilog="WARNING: Only use this script for cartridge-based systems (NES, SNES, GBA, etc). CD-based games should not be zipped."
    )
    
    parser.add_argument("-s", "--source", required=True, help="Source directory to scan for ROMs")
    parser.add_argument("-t", "--type", required=False, help="Optional: specific file extension to target bypassing prompts (e.g., .gba)")
    parser.add_argument("-d", "--dest", required=True, help="Destination directory to move original files to")
    parser.add_argument("-sd", "--sdcard", required=False, help="Optional: Destination SD card directory to sync the compressed files to.")

    args = parser.parse_args()

    compress_roms(args.source, args.type, args.dest, args.sdcard)

