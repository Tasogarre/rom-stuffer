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
from rom_stuffer.logs import setup_logging, get_logger


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


# ---------------------------------------------------------------------------
# Subcommand parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Construct and return the ArgumentParser with shared parent + subparsers.

    The shared parent defines -s/--source, -d/--dest, -sd/--sdcard, --dry-run,
    --theme, --resume, --fresh. The compress subparser adds -t/--type,
    --no-recursive, -l/--level. The dedup subparser adds --keeper-order,
    --protect, --per-system, --min-size, --interactive, --hard-delete,
    --apply-plan.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("-s", "--source", default=None, help="Source directory to scan for ROMs")
    parent.add_argument("-d", "--dest", default=None, help="Destination/backup directory for original files")
    parent.add_argument(
        "-sd", "--sdcard", default=None,
        help="SD card directory to sync compressed files to (delete-before-copy)",
    )
    parent.add_argument(
        "--dry-run", action="store_true",
        help="Preview what will happen without modifying any files",
    )
    parent.add_argument(
        "--theme", choices=sorted(THEMES.keys()), default=None,
        help="Visual theme: " + ", ".join(sorted(THEMES.keys())),
    )
    parent.add_argument(
        "--resume", action="store_true",
        help="Resume a previously interrupted job from its saved progress",
    )
    parent.add_argument(
        "--fresh", action="store_true",
        help="Discard any saved progress in the destination and start a brand-new scan",
    )
    parent.add_argument(
        "--verbose", action="store_true",
        help="Verbose logging (also echoes the rotating log to the console)",
    )
    parent.add_argument(
        "--log-dir", default=None,
        help="Directory for the rotating log file (default: ~/.rom_stuffer/logs)",
    )

    parser = argparse.ArgumentParser(
        prog="rom_stuffer.py",
        description="Recursively compress ROM files to .zip and move the originals.",
        epilog=(
            "WARNING: Only use this script for cartridge-based systems (NES, SNES, GBA, etc). "
            "CD-based games should not be zipped."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="COMMAND")

    compress_p = subparsers.add_parser(
        "compress",
        parents=[parent],
        help="Compress ROM files into individual .zip archives",
        description="Compress ROM files to .zip and move originals to the backup destination.",
    )
    compress_p.add_argument(
        "-t", "--type", default=None,
        help="Target a specific file extension, bypassing the interactive prompts (e.g. .gba)",
    )
    compress_p.add_argument(
        "--no-recursive", action="store_true",
        help="Disable recursive sub-folder scanning",
    )
    compress_p.add_argument(
        "-l", "--level", type=int, default=6, choices=range(1, 10), metavar="1-9",
        help=(
            "DEFLATE compression level (1=fastest, 9=smallest). "
            "Default 6 (Normal) is the recommended balance for RetroArch handhelds."
        ),
    )

    dedup_p = subparsers.add_parser(
        "dedup",
        parents=[parent],
        help="Find and remove duplicate ROM files",
        description="Detect byte-identical ROM duplicates and generate a removal plan.",
    )
    dedup_p.add_argument(
        "--keeper-order", default=None,
        help=(
            "Comma-separated folder-name substrings; earlier entries have higher keep priority "
            "(e.g. 'golden,primary')"
        ),
    )
    dedup_p.add_argument(
        "--protect", action="append", default=[],
        help="Folder name (substring) whose files are never removed; may be repeated",
    )
    dedup_p.add_argument(
        "--per-system", action="store_true",
        help="Only compare files that share the same top-level system folder",
    )
    dedup_p.add_argument(
        "--min-size", type=int, default=0,
        help="Skip files smaller than N bytes when scanning for duplicates",
    )
    dedup_p.add_argument(
        "--interactive", action="store_true",
        help="Confirm each duplicate group interactively in the TUI before acting",
    )
    dedup_p.add_argument(
        "--hard-delete", action="store_true",
        help="Permanently delete duplicates instead of quarantining them to a backup folder",
    )
    dedup_p.add_argument(
        "--apply-plan", default=None,
        help="Path to a previously saved dedup plan file to apply instead of re-scanning",
    )

    estimate_p = subparsers.add_parser(
        "estimate",
        parents=[parent],
        help="Estimate SD-card space per system (compressed + de-duplicated)",
        description="Report per-system and total space: decompressed vs compressed size and dedup savings.",
    )
    estimate_p.add_argument(
        "--no-recursive", action="store_true",
        help="Scan only the top-level source folder",
    )
    estimate_p.add_argument(
        "--per-system", action="store_true", default=True,
        help="Group the estimate by system folder (default)",
    )

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _run_compress(args: argparse.Namespace) -> None:
    """Route parsed args to compress_roms().

    Prompts for source and/or dest if they are absent from args.
    """
    source = args.source
    if not source:
        source = Prompt.ask("[accent]Source[/accent] directory to scan for ROMs").strip()

    dest = args.dest
    if not dest:
        dest = Prompt.ask("[accent]Destination[/accent] directory for the original files").strip()

    recursive = not getattr(args, "no_recursive", False)
    level = getattr(args, "level", 6)

    compress_roms(
        source,
        getattr(args, "type", None),
        dest,
        args.sdcard,
        args.dry_run,
        recursive,
        level,
        resume=args.resume,
        fresh=args.fresh,
    )


def _run_dedup(args: argparse.Namespace) -> None:
    """Route parsed args to the dedup flow via a lazy import.

    The dedup engine (rom_stuffer.dedup) may not exist yet; if it is absent,
    a clear error message is printed and the function returns without raising.
    """
    try:
        from rom_stuffer.dedup import run_dedup  # noqa: PLC0415
        run_dedup(args)
    except ImportError:
        console.print(
            "[warn]Dedup engine not yet available.[/warn] "
            "Build or install the rom_stuffer.dedup module to use this feature."
        )


def _run_both(args: argparse.Namespace) -> None:
    """De-duplicate first, then compress the surviving files."""
    _run_dedup(args)
    _run_compress(args)


def _interactive_menu() -> None:
    """Display the themed no-arg menu and route to the chosen handler.

    Prompts the user for a theme, an action (1=Compress, 2=Find duplicates,
    3=Both), and the required paths, then delegates to the appropriate handler.
    Ctrl-C prints a goodbye message and exits 0.
    """
    try:
        choice = Prompt.ask(
            "Choose a theme",
            choices=sorted(THEMES.keys()),
            default=DEFAULT_THEME,
        )
        apply_theme(choice)
        print_header()

        console.print("\n[bold]What would you like to do?[/bold]\n")
        console.print("  [1]  Compress ROMs")
        console.print("  [2]  Find duplicates")
        console.print("  [3]  Both  (de-duplicate first, then compress)\n")

        action = IntPrompt.ask("Choose", default=1)
        while action not in (1, 2, 3):
            console.print("  [warn]Please choose 1, 2, or 3.[/warn]")
            action = IntPrompt.ask("Choose", default=1)

        source = Prompt.ask("[accent]Source[/accent] directory").strip()
        dest = Prompt.ask("[accent]Destination[/accent] directory").strip()
        dry_run = Confirm.ask("Dry run?", default=False)

        ns = argparse.Namespace(
            source=source,
            dest=dest,
            sdcard=None,
            dry_run=dry_run,
            resume=False,
            fresh=False,
            # compress-specific defaults
            type=None,
            no_recursive=False,
            level=6,
            # dedup-specific defaults
            keeper_order=None,
            protect=[],
            per_system=False,
            min_size=0,
            interactive=False,
            hard_delete=False,
            apply_plan=None,
        )

        if action == 1:
            _run_compress(ns)
        elif action == 2:
            _run_dedup(ns)
        else:
            _run_both(ns)

    except KeyboardInterrupt:
        console.print("\n[muted]Goodbye.[/muted]")
        sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Top-level CLI entry point.

    Routes to the correct handler based on argv:
    - No arguments: shows the themed interactive menu (_interactive_menu).
    - 'compress' subcommand: runs the compress flow (_run_compress).
    - 'dedup' subcommand: runs the dedup flow (_run_dedup).
    - Unknown / missing subcommand: prints help and exits 1.
    """
    setup_logging()  # baseline config so the no-arg menu path also logs

    if len(sys.argv) == 1:
        _interactive_menu()
        return

    args = _build_parser().parse_args()

    # Reconfigure the rotating log with the user's preferences before any operation.
    from pathlib import Path as _Path
    log_dir = _Path(args.log_dir) if getattr(args, "log_dir", None) else None
    log_file = setup_logging(log_dir=log_dir, verbose=getattr(args, "verbose", False))
    _log = get_logger("cli")
    _log.info("start subcommand=%s source=%s dest=%s", args.subcommand, args.source, args.dest)

    if args.theme:
        apply_theme(args.theme)
    else:
        apply_theme(DEFAULT_THEME)

    print_header()

    try:
        if args.subcommand == "compress":
            _run_compress(args)
        elif args.subcommand == "dedup":
            _run_dedup(args)
        elif args.subcommand == "estimate":
            _run_estimate(args)
        else:
            _build_parser().print_help()
            sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        _log.exception("unhandled error in %s", args.subcommand)
        raise
    finally:
        _log.info("done subcommand=%s (log: %s)", args.subcommand, log_file)


def _run_estimate(args: argparse.Namespace) -> None:
    """Route parsed args to the space-saving estimator."""
    from rom_stuffer.estimate import run_estimate
    if not args.source:
        args.source = Prompt.ask("[accent]Source[/accent] directory to estimate").strip()
    get_logger("estimate").info("estimating source=%s", args.source)
    run_estimate(args)


if __name__ == "__main__":
    main()
