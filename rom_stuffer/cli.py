from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rom_stuffer.tui import (
    console, print_header, print_warning_banner,
    box, Panel, Confirm, IntPrompt, Prompt,
)
from rom_stuffer.themes import THEMES, DEFAULT_THEME, apply_theme
from rom_stuffer.metrics import SessionMetrics
from rom_stuffer.guards import SUPPORTED_EXTENSIONS, exclusion_reason, describe_error
from rom_stuffer.state import (
    load_manifest, read_journal, write_manifest, clear_state,
    _state_paths, ResumeState,
)
from rom_stuffer.scan import _build_worklist_interactive
from rom_stuffer.compress import compress_batch
from rom_stuffer.report import generate_reports


def _finalise_session(
    metrics: SessionMetrics, dest_path: Path, dry_run: bool
) -> None:
    """Render reports and settle the resume state: clear it on a clean finish, keep
    it (so failures can be retried with --resume) when any file errored."""
    generate_reports(metrics, dest_path)
    if dry_run:
        console.print(Panel(
            "[info]Dry run complete[/info] — nothing was changed.",
            box=box.ROUNDED, border_style="info", padding=(0, 2),
        ))
        return
    if metrics.error_count == 0:
        clear_state(dest_path)
        console.print(Panel(
            "[success]✔  All done.[/success] Your ROMs are compressed and originals are safely backed up.",
            box=box.ROUNDED, border_style="success", padding=(0, 2),
        ))
    else:
        state_file, _ = _state_paths(dest_path)
        keep_note = ""
        if state_file.exists():
            keep_note = "\nProgress has been saved — re-run with [info]--resume[/info] to retry only the ones that did not finish."
        console.print(Panel(
            f"[warn]Finished with {metrics.error_count} failure(s).[/warn]{keep_note}",
            box=box.ROUNDED, border_style="warn", padding=(0, 2),
        ))


def compress_roms(
    source_dir: str,
    file_type: str | None,
    dest_dir: str,
    sdcard_dir: str | None = None,
    dry_run: bool = False,
    recursive: bool = True,
    compress_level: int = 6,
    resume: bool = False,
    fresh: bool = False,
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

    print_warning_banner()

    dest_path.mkdir(parents=True, exist_ok=True)
    metrics = SessionMetrics()
    metrics.dry_run = dry_run

    # One claimed-zip set for the whole session so name collisions are caught across
    # the separate per-extension batches of interactive mode, not just within one.
    claimed_zips: set[Path] = set()

    if dry_run:
        console.print(Panel(
            "[info]DRY RUN[/info] — no files will be modified; report sizes are estimates.",
            box=box.ROUNDED, border_style="info", padding=(0, 2),
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
    elif not file_type and not resume:
        if Confirm.ask("\nDo you want to sync the compressed ROMs directly to an SD Card after compressing?"):
            sd_input = Prompt.ask("Enter the path to the SD Card (e.g. F:\\ or /Volumes/SDCARD)").strip()
            if sd_input:
                sdcard_path = Path(sd_input).resolve()
                if not sdcard_path.exists() or not sdcard_path.is_dir():
                    console.print(f"[bold red]Error: SD Card directory '{sdcard_path}' does not exist.[/bold red]")
                    sys.exit(1)
                console.print(f"[bold green]SD Card Sync Enabled:[/bold green] Pointing to {sdcard_path}\n")

    # ----------------------------------------------------------------------- #
    # Resume detection. Dry-run never touches persisted state.
    # ----------------------------------------------------------------------- #
    manifest = None if dry_run else load_manifest(dest_path)
    do_resume = False
    if manifest is not None:
        if fresh:
            clear_state(dest_path)
            manifest = None
            console.print("[yellow]--fresh: discarded saved progress; starting a new scan.[/yellow]")
        elif manifest.get('source') != str(source_path):
            console.print(
                "[bold red]A saved job exists in this destination for a DIFFERENT source:[/bold red]\n"
                f"  saved source:   {manifest.get('source')}\n"
                f"  current source: {source_path}\n"
                "Refusing to mix jobs. Re-run with --fresh to discard it, or use a different --dest."
            )
            sys.exit(1)
        else:
            done = read_journal(dest_path)
            remaining = manifest['total'] - len(done)
            if resume:
                do_resume = True
            else:
                console.print(
                    "\n[bold cyan]Found an incomplete job in this destination:[/bold cyan]\n"
                    f"  source:   {manifest.get('source')}\n"
                    f"  progress: {len(done):,} / {manifest['total']:,} done  ({remaining:,} remaining)"
                )
                if Confirm.ask("Resume where it left off (skip the full rescan)?", default=True):
                    do_resume = True
                else:
                    clear_state(dest_path)
                    manifest = None
                    console.print("[yellow]Starting a new scan; previous progress discarded.[/yellow]")

    # ----------------------------------------------------------------------- #
    # Build the work-list: either from the saved manifest (resume) or a scan.
    # ----------------------------------------------------------------------- #
    files_to_process: list[Path] = []
    if do_resume and manifest is not None:
        done = read_journal(dest_path)
        for rel in manifest['pending']:
            if rel in done:
                continue
            candidate = source_path / rel
            if candidate.exists():
                files_to_process.append(candidate)
            # Missing candidates were already handled (moved) or removed — skip quietly.
        console.print(
            f"[bold green]Resuming:[/bold green] {len(files_to_process):,} files remaining "
            f"of {manifest['total']:,} (no rescan needed)."
        )
        if not files_to_process:
            console.print("[green]Nothing left to do — the job is already complete.[/green]")
            clear_state(dest_path)
            return

        # The file that was mid-flight when the run was interrupted may have left a
        # committed .zip that was never moved or journalled. Seed claimed_zips with the
        # zips owned by completed files, then delete any *other* stale zip sitting next
        # to a pending file, so resume recreates it under its proper name instead of
        # disambiguating around it (which would duplicate it on disk and on the SD card).
        done_defaults = {(source_path / r).with_suffix('.zip') for r in done}
        claimed_zips |= done_defaults
        for f in files_to_process:
            stale = f.with_suffix('.zip')
            if stale not in done_defaults and stale.exists():
                stale.unlink()
    elif file_type:
        console.print(
            f"Scanning for [cyan]'{file_type}'[/cyan] files in "
            f"[cyan]'{source_path}'[/cyan] (Recursive: {recursive})..."
        )
        scan_iter = source_path.rglob('*') if recursive else source_path.glob('*')
        for p in scan_iter:
            try:
                if p.is_file() and p.suffix.lower() == file_type:
                    size = None
                    if file_type == '.bin':
                        try:
                            size = p.stat().st_size
                        except OSError:
                            size = None
                    reason = exclusion_reason(p, file_type, size, source_path)
                    if reason:
                        metrics.skipped_files.append({'file': str(p.name), 'reason': reason})
                    else:
                        files_to_process.append(p)
            except OSError as e:
                metrics.skipped_files.append({'file': str(p.name), 'reason': f"Unreadable: {describe_error(e)}"})
        if not files_to_process:
            console.print("[yellow]No files found matching the specified type.[/yellow]")
            return
        console.print(f"Found [bold]{len(files_to_process)}[/bold] files to process.")
    else:
        files_to_process = _build_worklist_interactive(source_path, recursive, metrics)
        if not files_to_process:
            # Nothing selected — still emit a report so skips are recorded.
            generate_reports(metrics, dest_path)
            return

    # ----------------------------------------------------------------------- #
    # Persist the manifest for a fresh run, then process with journalling.
    # ----------------------------------------------------------------------- #
    resume_state: ResumeState | None = None
    if not dry_run:
        if not do_resume:
            pending_rel = [str(p.relative_to(source_path)) for p in files_to_process]
            write_manifest(dest_path, source_path, pending_rel)
            resume_state = ResumeState(dest_path, set())
        else:
            resume_state = ResumeState(dest_path, read_journal(dest_path))

    try:
        compress_batch(
            files_to_process, source_path, dest_path, metrics,
            sdcard_path, compress_level, claimed_zips, resume_state,
        )
    finally:
        if resume_state is not None:
            resume_state.close()

    _finalise_session(metrics, dest_path, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rom_stuffer.py",
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
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume a previously interrupted job from its saved progress, skipping the full rescan.",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Discard any saved progress in the destination and start a brand-new scan.",
    )
    parser.add_argument(
        "--theme", choices=sorted(THEMES.keys()), default=None,
        help="Visual theme: kirby (default), tetris, zelda, or metroid.",
    )

    args = parser.parse_args()

    provided_args = [
        args.source, args.dest, args.type, args.sdcard,
        args.dry_run, args.no_recursive, args.resume, args.fresh, args.theme,
    ]
    interactive_mode = not any(provided_args)

    # Theme: explicit flag wins; otherwise ask in the TUI, else default.
    if args.theme:
        apply_theme(args.theme)
    elif interactive_mode:
        choice = Prompt.ask(
            "Choose a theme",
            choices=sorted(THEMES.keys()),
            default=DEFAULT_THEME,
        )
        apply_theme(choice)

    print_header()

    source = args.source
    if not source:
        source = Prompt.ask("[accent]Source[/accent] directory to scan for ROMs").strip()

    dest = args.dest
    if not dest:
        dest = Prompt.ask("[accent]Destination[/accent] directory for the original files").strip()

    dry_run = args.dry_run
    if interactive_mode and not dry_run:
        dry_run = Confirm.ask("Run in [info]dry-run[/info] mode (preview only)?", default=False)

    recursive = not args.no_recursive
    if interactive_mode and not args.no_recursive:
        recursive = Confirm.ask("Scan sub-folders [accent]recursively[/accent]?", default=True)

    level = args.level
    if interactive_mode:
        while True:
            level = IntPrompt.ask(
                "[accent]Compression level[/accent] "
                "[muted](1 = fastest, 9 = smallest; 6 recommended)[/muted]",
                default=6,
            )
            if 1 <= level <= 9:
                break
            console.print("  [warn]Please choose a number from 1 to 9.[/warn]")

    compress_roms(
        source, args.type, dest, args.sdcard, dry_run, recursive, level,
        resume=args.resume, fresh=args.fresh,
    )


if __name__ == "__main__":
    main()
