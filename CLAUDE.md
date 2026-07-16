# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`rom_stuffer` is a single-file Python CLI (`compress_roms.py`) that compresses retro gaming ROM files into individual `.zip` archives for use on RetroArch-based handhelds (R36S, Miyoo Mini, etc.). It also moves originals to a backup directory while preserving folder structure, and optionally fast-syncs the new zips to a mounted SD card.

## Running the script

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
- `compress_batch()` - the core loop: for each file, creates a ZIP (one ROM per ZIP, same name, DEFLATE level 6), optionally syncs to SD card via `fast_sd_copy()`, then moves the original to the backup destination preserving relative path.
- `fast_sd_copy()` - uses `shutil.copyfileobj` with a 16MB buffer to maximize sequential write throughput on flash media. Do not parallelize this - flash memory controllers perform poorly under parallel I/O.
- `generate_reports()` - renders Rich tables to the console and writes a plain-text `rom_stuffer_report.txt` to the backup destination.
- `compress_roms()` - orchestrates a session: validates paths, optionally prompts for SD card, then either processes a single extension (headless) or interactively groups files by extension and prompts the user for each.

## Key design constraints

**One ROM per ZIP, named identically to the ROM.** RetroArch cannot handle solid archives or multi-ROM ZIPs.

**DEFLATE level 6 ("Normal"), not "Ultra".** Higher compression causes decompression lag on low-powered handhelds.

**No CD-based, N64, NDS, or MAME extensions.** These categories must never be added to `SUPPORTED_EXTENSIONS`. The reasons are documented in inline comments and in `LLM_HANDOVER.md`.

**Sequential SD card writes only.** The 16MB buffer in `fast_sd_copy()` is intentional - parallelizing writes to flash media causes controller thrashing and slower throughput.
