from __future__ import annotations

import argparse
import json
import os
import shutil
import zipfile
from pathlib import Path
import sys
from collections import defaultdict

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.markup import escape
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.progress import (
        Progress, SpinnerColumn, TextColumn, BarColumn,
        TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn,
        MofNCompleteColumn,
    )
    from rich.prompt import Confirm, IntPrompt, Prompt
    from rich.theme import Theme
    from rich import print as rprint
except ImportError:
    print("Error: The 'rich' library is required. Please install it using: pip install -r requirements.txt")
    sys.exit(1)

# --------------------------------------------------------------------------- #
# Themes. Each is a full NES-era skin: a semantic colour palette (so the whole
# TUI reads as one design) plus a pixel-art emblem and title drawn in that
# palette. Styles are referenced everywhere by semantic name (brand/accent/...),
# so switching the theme re-skins the entire interface.
# --------------------------------------------------------------------------- #

# "zelda" theme emblem — a gold Triforce (half-block pixel art). Three solid
# triangles; the empty middle is an inverted triangle tapering to a point at the
# base, so it reads as one Triforce. (Theme name only — the app is ROM STUFFER.)
ZELDA_ART = (
    "[brand]██[/brand]\n"
    "[brand]████[/brand]\n"
    "[brand]██████[/brand]\n"
    "[brand]██    ██[/brand]\n"
    "[brand]████  ████[/brand]\n"
    "[brand]████████████[/brand]"
)

# "metroid" theme emblem — bio-cyan membrane dome, three red nuclei, orange mandibles.
METROID_ART = (
    "[accent]▁▄▄▄▄▄▁[/accent]\n"
    "[accent]◢█████████◣[/accent]\n"
    "[accent]██[/accent] [danger]◉[/danger] [danger]◉[/danger] [danger]◉[/danger] [accent]██[/accent]\n"
    "[accent]◥█████████◤[/accent]\n"
    "[brand]▜█▙ ▜█▙ ▜█▙[/brand]\n"
    "[brand]▚   ▚   ▚[/brand]"
)

THEMES: dict[str, dict] = {
    "zelda": {
        "styles": {
            "brand": "bold #f8c000",     # gold
            "accent": "#38c020",         # green
            "info": "#80d010",           # bright leaf green
            "success": "bold #38c020",
            "warn": "#f8c000",           # gold caution
            "danger": "bold #d82800",    # red
            "muted": "dim #b08040",      # aged parchment
            "value": "bold #f8c000",
            "path": "#80d010",
        },
        "art": ZELDA_ART,
        "label": "zelda theme",
        "tagline": "It's dangerous to go alone!  Compress your cartridges first.",
        "border": "#f8c000",
    },
    "metroid": {
        "styles": {
            "brand": "bold #f85000",     # armour orange
            "accent": "#38c0f8",         # bio-cyan
            "info": "#40e0a0",           # membrane green
            "success": "bold #40e0a0",
            "warn": "#f8d000",           # visor yellow
            "danger": "bold #f8005c",    # nuclei magenta-red
            "muted": "dim #7088a0",      # cavern steel
            "value": "bold #f8d000",
            "path": "#38c0f8",
        },
        "art": METROID_ART,
        "label": "metroid theme",
        "tagline": "The last cartridge is in captivity.  The galaxy is at peace.",
        "border": "#f85000",
    },
}
DEFAULT_THEME = "zelda"

console = Console()
_active_theme = {"name": DEFAULT_THEME}


def apply_theme(name: str) -> None:
    """Activate a theme by name, re-skinning every semantic style."""
    if name not in THEMES:
        name = DEFAULT_THEME
    _active_theme["name"] = name
    console.push_theme(Theme(THEMES[name]["styles"]))


APP_TAGLINE = "Compress cartridge ROMs into RetroArch-ready .zip archives"

# Ensure semantic styles always resolve, even when compress_roms() is called
# directly (e.g. from tests) without the CLI selecting a theme first.
apply_theme(DEFAULT_THEME)

# Named constants
FAST_COPY_BUFFER_BYTES: int = 4 * 1024 * 1024   # 4 MB: suits typical SD/flash page sizes
SCAN_FOLDER_SAMPLE: int = 8
CONSOLE_TABLE_ROW_CAP: int = 20
DRY_RUN_COMPRESSION_ESTIMATE: float = 0.4        # rough DEFLATE ratio on ROM data

# Resume/checkpoint state (written into the destination directory)
STATE_VERSION: int = 1
STATE_FILENAME: str = ".rom_stuffer_state.json"
JOURNAL_FILENAME: str = ".rom_stuffer_journal.log"
JOURNAL_FSYNC_INTERVAL: int = 200                # fsync the journal every N completions

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


# --------------------------------------------------------------------------- #
# TUI presentation helpers — keep all styling in one place for a cohesive look.
# --------------------------------------------------------------------------- #

def print_header() -> None:
    """Render the themed banner: emblem + the app name (ROM STUFFER) + theme caption."""
    theme = THEMES[_active_theme["name"]]
    # Each emblem row holds only symmetric content (no leading/trailing padding), so
    # centring every row lands them on one axis. (Rich strips edge whitespace when it
    # justifies, so padding-based positioning would shear the shape.)
    art = Text.from_markup(theme["art"], justify="center")
    title = Text("R O M   S T U F F E R", style="brand", justify="center")
    caption = Text(f"‹ {theme['label']} ›", style="muted", justify="center")
    tagline = Text(theme["tagline"], style="muted", justify="center")
    console.print()
    console.print(Panel(
        Align.center(Group(art, Text(), title, caption, Text(), tagline)),
        box=box.DOUBLE,
        border_style=theme["border"],
        padding=(1, 4),
    ))


def print_warning_banner() -> None:
    """The cartridge-only safety warning, styled as a caution panel."""
    console.print(Panel(
        Text.from_markup(
            "[warn]⚠  Cartridge-based systems only.[/warn]\n"
            "Do [danger]not[/danger] use this for CD-based games (PS1, Saturn, Sega CD) — "
            "convert those to [info].chd[/info] instead.\n"
            "N64, NDS and MAME are intentionally excluded too."
        ),
        title="[warn]Please read[/warn]",
        box=box.ROUNDED,
        border_style="warn",
        padding=(0, 2),
    ))


def section(title: str) -> None:
    """A titled horizontal rule that separates the phases of a run."""
    console.print()
    console.rule(f"[accent]{title}[/accent]", style="accent", align="left")


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


def describe_error(e: Exception) -> str:
    """Human-readable error text. An OSError's str() embeds repr(filename), which
    doubles backslashes on Windows paths (C:\\\\Games); when the OS gives us a
    strerror, build the message from strerror + the raw filename (single backslash)
    instead. Otherwise fall back to str() (which carries the message and, for
    non-OS/message-style errors, no repr'd path)."""
    if isinstance(e, OSError) and e.strerror:
        return f"{e.strerror}: {e.filename}" if e.filename else e.strerror
    return str(e)


# --------------------------------------------------------------------------- #
# Disc-image / BIOS guard.
#
# '.bin' is dangerously ambiguous: Sega Genesis and Atari 2600 CARTRIDGE dumps use
# it (tiny — Genesis tops out ~8 MB), but so do CD/GD-ROM disc images (PS1, Saturn,
# Sega CD, Dreamcast, PC Engine CD — hundreds of MB, usually beside a .cue/.gdi) and
# BIOS files. Compressing a disc image breaks it, and moving a BIOS out of place
# breaks the emulator. These checks keep genuine cartridge .bin files while refusing
# disc images and BIOS. BIOS folders are off-limits for every extension.
# --------------------------------------------------------------------------- #
CARTRIDGE_BIN_MAX_BYTES: int = 16 * 1024 * 1024
DISC_DESCRIPTOR_SUFFIXES: set = {'.cue', '.gdi', '.ccd', '.mds', '.toc', '.m3u'}
# Folders whose contents are NOT cartridge ROMs — optical-disc, UMD, HDD, or arcade
# systems (and their common RetroArch/EmulationStation aliases). A '.bin' in any of
# these is a disc image / data blob, never a Genesis cartridge, so it must never be
# compressed or moved. Matched case-insensitively against each path component.
DISC_SYSTEM_FOLDERS: set = {
    # Sony — all disc / UMD / HDD
    'psx', 'ps1', 'psone', 'playstation', 'ps2', 'playstation2', 'ps3', 'playstation3',
    'psp', 'playstationportable', 'psvita', 'vita',
    # Sega — optical
    'dreamcast', 'dc', 'saturn', 'saturnjp', 'segacd', 'sega-cd', 'megacd', 'mega-cd',
    'mcd', 'naomi', 'atomiswave',
    # NEC and other optical
    'pcecd', 'pce-cd', 'pcenginecd', 'tgcd', 'turbografxcd', 'pcfx', 'neogeocd',
    'neo-geo-cd', 'amigacd32', 'cd32', '3do', 'jaguarcd', 'cdi', 'cdimono1',
    'philipscdi', 'fmtowns', 'fmtownsmarty',
    # Nintendo — disc / HDD-scale
    'gamecube', 'gc', 'ngc', 'wii', 'wiiu', 'switch',
    # Microsoft
    'xbox', 'xbox360', 'xboxone',
    # Arcade (ROM sets ship zipped) and BIOS
    'mame', 'fbneo', 'fba', 'arcade', 'cps1', 'cps2', 'cps3', 'model2', 'model3', 'bios',
}
_disc_dir_cache: dict = {}


def _dir_has_disc_descriptor(directory: Path) -> bool:
    """True if a .cue/.gdi/... descriptor sits in this folder (cached per directory)."""
    key = str(directory)
    if key not in _disc_dir_cache:
        found = False
        try:
            for entry in directory.iterdir():
                if entry.suffix.lower() in DISC_DESCRIPTOR_SUFFIXES:
                    found = True
                    break
        except OSError:
            found = False
        _disc_dir_cache[key] = found
    return _disc_dir_cache[key]


def exclusion_reason(path: Path, ext: str, size: int | None, source: Path | None = None) -> str | None:
    """Return why a supported-extension file must be refused (disc image or BIOS),
    or None if it is a genuine cartridge ROM safe to compress and move.

    Only folder names *inside* the source tree are considered (the system-organisation
    folders), never parent directories above the source, so a source path that happens
    to sit under a folder like 'psp' or 'bios' does not exclude everything.
    """
    relevant = path.parent
    if source is not None:
        try:
            relevant = path.relative_to(source).parent
        except ValueError:
            relevant = path.parent
    parts = {p.lower() for p in relevant.parts}
    # BIOS files must never be moved or compressed, whatever their extension.
    if 'bios' in parts:
        return "BIOS folder — must stay in place"
    # '.bin' is the ambiguous one: disambiguate cartridge dumps from disc images.
    if ext == '.bin':
        disc_folder = parts & DISC_SYSTEM_FOLDERS
        if disc_folder:
            return f"disc-based system folder ('{sorted(disc_folder)[0]}')"
        if _dir_has_disc_descriptor(path.parent):
            return "disc image — a .cue/.gdi descriptor is present in the folder"
        if size is not None and size > CARTRIDGE_BIN_MAX_BYTES:
            return f"disc image — .bin is {format_size(size)}, too large for a cartridge"
    return None


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
    when the default name is already taken. A name is "taken" if another file in
    this session already claimed it (the `claimed` set, which spans every batch so
    interactive per-extension runs don't collide) OR a file already exists at that
    path on disk (a prior run, or the batch that just wrote it). The claimed set is
    updated in-place.
    """
    default = file_path.with_suffix('.zip')
    if default not in claimed and not default.exists():
        claimed.add(default)
        return default
    stem_ext = f"{file_path.stem}_{file_path.suffix.lstrip('.')}"
    candidate = file_path.parent / f"{stem_ext}.zip"
    counter = 1
    while candidate in claimed or candidate.exists():
        candidate = file_path.parent / f"{stem_ext}_{counter}.zip"
        counter += 1
    claimed.add(candidate)
    return candidate


# --------------------------------------------------------------------------- #
# Resume / checkpoint support
#
# A long run over tens of thousands of files must survive an interruption without
# rescanning the whole tree. Two files in the destination make that possible:
#   * a manifest (JSON) written once, holding the full work-list as paths relative
#     to the source; and
#   * an append-only journal, one relative path per completed file.
# On resume, pending = manifest − journal, so no rescan and no re-prompting.
# --------------------------------------------------------------------------- #

def _state_paths(dest_path: Path) -> tuple[Path, Path]:
    return dest_path / STATE_FILENAME, dest_path / JOURNAL_FILENAME


def load_manifest(dest_path: Path) -> dict | None:
    """Return the saved manifest, or None if absent, unreadable, or incompatible."""
    state_file, _ = _state_paths(dest_path)
    if not state_file.exists():
        return None
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('version') != STATE_VERSION or 'pending' not in data:
        return None
    return data


def read_journal(dest_path: Path) -> set[str]:
    """Return the set of relative paths already recorded as completed."""
    _, journal_file = _state_paths(dest_path)
    done: set[str] = set()
    if not journal_file.exists():
        return done
    try:
        with open(journal_file, 'r', encoding='utf-8') as f:
            for line in f:
                rel = line.rstrip('\n')
                if rel:
                    done.add(rel)
    except OSError:
        pass
    return done


def write_manifest(dest_path: Path, source_path: Path, pending_rel: list[str]) -> None:
    """Atomically write the work-list manifest and reset the journal."""
    state_file, journal_file = _state_paths(dest_path)
    data = {
        'version': STATE_VERSION,
        'source': str(source_path),
        'total': len(pending_rel),
        'pending': pending_rel,
    }
    tmp = state_file.with_name(state_file.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(state_file)
    journal_file.unlink(missing_ok=True)


def clear_state(dest_path: Path) -> None:
    """Remove the manifest and journal (called on clean completion or --fresh)."""
    state_file, journal_file = _state_paths(dest_path)
    state_file.unlink(missing_ok=True)
    journal_file.unlink(missing_ok=True)


class ResumeState:
    """Append-only progress journal. mark_done() is O(1) and flushed per file so a
    process crash loses nothing; fsync runs every JOURNAL_FSYNC_INTERVAL files to
    bound the cost while still guarding against power loss."""

    def __init__(self, dest_path: Path, done: set[str]) -> None:
        _, journal_file = _state_paths(dest_path)
        self.done = done
        self._fh = open(journal_file, 'a', encoding='utf-8')
        self._since_sync = 0

    def is_done(self, rel: str) -> bool:
        return rel in self.done

    def mark_done(self, rel: str) -> None:
        self._fh.write(rel + '\n')
        self._fh.flush()
        self.done.add(rel)
        self._since_sync += 1
        if self._since_sync >= JOURNAL_FSYNC_INTERVAL:
            os.fsync(self._fh.fileno())
            self._since_sync = 0

    def close(self) -> None:
        try:
            os.fsync(self._fh.fileno())
        except OSError:
            pass
        self._fh.close()


def compress_batch(
    files_to_process: list[Path],
    source_path: Path,
    dest_path: Path,
    metrics: SessionMetrics,
    sdcard_path: Path | None = None,
    compress_level: int = 6,
    claimed_zips: set[Path] | None = None,
    resume_state: ResumeState | None = None,
) -> None:
    dry_run = metrics.dry_run

    # Zip paths already claimed this session. Passed in by compress_roms so it spans
    # every batch — interactive mode calls this once per extension, and Game.gb's
    # Game.zip must still block Game.gbc in the next batch. Falls back to a local set
    # for standalone calls.
    if claimed_zips is None:
        claimed_zips = set()

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

    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None, complete_style="accent", finished_style="success"),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(compact=True),
        console=console,
        expand=True,
    ) as progress:
        overall_task = progress.add_task("[accent]Files[/accent]", total=len(sized))
        byte_task = progress.add_task("[info]Data [/info]", total=total_bytes)

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
                        description=f"[warn]Syncing[/warn] {safe_name} → SD",
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

                # Record durable progress so an interruption can resume here.
                if resume_state is not None:
                    resume_state.mark_done(str(rel_path))

            except Exception as e:
                metrics.error_count += 1
                metrics.errors.append({'file': str(file_path.name), 'error': describe_error(e)})

            finally:
                # Live running space-saved readout so progress is visible on long runs,
                # not only in the final summary.
                saved = metrics.original_size_bytes - metrics.zip_size_bytes
                pct = (saved / metrics.original_size_bytes * 100) if metrics.original_size_bytes else 0.0
                progress.update(overall_task, description="[accent]Files[/accent]")
                progress.update(
                    byte_task,
                    description=f"[info]Data [/info][muted]· saved[/muted] [success]{format_size(saved)}[/success] [muted]({pct:.0f}%)[/muted]",
                )
                progress.advance(overall_task)
                progress.advance(byte_task, advance=original_size)


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
        help="Visual theme: 'zelda' (default) or 'metroid'.",
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
