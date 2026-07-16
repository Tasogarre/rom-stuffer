# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`rom_stuffer` is a single-file Python CLI (`compress_roms.py`) that compresses retro gaming ROM files into individual `.zip` archives for use on RetroArch-based handhelds (R36S, Miyoo Mini, etc.). It also moves originals to a backup directory while preserving folder structure, and optionally fast-syncs the new zips to a mounted SD card.

## Running the script

Requires Python 3.8+.

```bash
pip install -r requirements.txt

# Interactive mode (prompts for each extension found)
python compress_roms.py --source "/path/to/roms" --dest "/path/to/backup"

# Headless: target a specific extension
python compress_roms.py -s "/path/to/roms" -t ".gba" -d "/path/to/backup"

# With SD card sync
python compress_roms.py -s "/path/to/roms" -d "/path/to/backup" -sd "/Volumes/SDCARD"

# Preview without modifying files
python compress_roms.py -s "/path/to/roms" -d "/path/to/backup" --dry-run
```

There are no tests, no build step, and no linter configured.

## Architecture

Everything lives in `compress_roms.py`:

- `SUPPORTED_EXTENSIONS` - the hardcoded allowlist of cartridge ROM extensions. CD-based systems (PS1, Saturn), N64, NDS, and MAME arcade are intentionally excluded and must stay excluded.
- `SessionMetrics` - accumulates counts, byte totals, errors, and skipped files across all batches in a session.
- `build_zip_path(file_path, claimed)` - returns the target `.zip` path for a source file. Uses `Game.zip` in the common case; falls back to `Game_gb.zip` / `Game_gbc.zip` when two files in the same folder share a stem but differ in extension. `claimed` is a `set[Path]` updated in-place to prevent within-batch collisions.
- `compress_batch()` - the core loop: performs a single stat pass to collect `(Path, size)` pairs, then for each file writes to a `.tmp` before atomically replacing to avoid leaving corrupt archives, syncs to the SD card via `fast_sd_copy()`, and moves the original to the backup destination preserving relative path. `original_size` is always bound before the try so the `finally` progress advance never raises.
- `fast_sd_copy()` - uses `shutil.copyfileobj` with a 4 MB buffer and `os.fsync()` to maximise sequential write throughput on flash media and confirm durability. Do not parallelize this - flash memory controllers perform poorly under parallel I/O.
- `generate_reports()` - renders Rich tables to the console and writes a plain-text `rom_stuffer_report.txt` to the backup destination. Dry-run runs are labelled as estimates.
- `compress_roms()` - orchestrates a session: validates paths (including dest-inside-source guard), validates and normalises `--type`, optionally prompts for SD card, handles resume detection, builds a work-list (from a scan or a saved manifest), persists the manifest, processes, then finalises (report + clear/keep state).
- **Themes** - `THEMES` registry maps a name (`zelda`, `metroid`) to a semantic Rich style palette (brand/accent/info/success/warn/danger/muted/value/path), a pixel-art emblem, a title, a tagline, and a border colour. The whole TUI references styles by semantic name, so `apply_theme(name)` (which `push_theme`s the palette) re-skins everything. A default theme is applied at import so direct `compress_roms()` calls (tests) always resolve styles; the CLI picks a theme via `--theme` or an interactive prompt. `print_header()` renders the active theme's emblem.
- **Resume/checkpoint** - `ResumeState` plus `load_manifest`/`read_journal`/`write_manifest`/`clear_state`. On a fresh run the full work-list is written to `<dest>/.rom_stuffer_state.json` (atomic tmp+replace) and each completed file is appended to `<dest>/.rom_stuffer_journal.log` (flushed per file, fsync every `JOURNAL_FSYNC_INTERVAL`). On resume, `pending = manifest − journal`, filtered to files still present in source, so there is no rescan. A clean finish clears the state; any failure keeps it so `--resume` retries only the unfinished files. The manifest is keyed to its source: a different source pointed at the same dest is refused (use `--fresh`). Dry-run never touches state. `_build_worklist_interactive()` gathers all per-extension prompt answers up front so the whole job fits one manifest.

## Key design constraints

**One ROM per ZIP, named identically to the ROM.** RetroArch cannot handle solid archives or multi-ROM ZIPs.

**DEFLATE level 6 ("Normal"), not "Ultra".** Higher compression causes decompression lag on low-powered handhelds.

**No CD-based, N64, NDS, or MAME extensions.** These categories must never be added to `SUPPORTED_EXTENSIONS`. The reasons are documented in inline comments and in `LLM_HANDOVER.md`.

**Sequential SD card writes only.** The 16MB buffer in `fast_sd_copy()` is intentional - parallelizing writes to flash media causes controller thrashing and slower throughput.
