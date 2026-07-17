<div align="center">

<img src="assets/banner.png" alt="ROM STUFFER — cartridge ROM compressor for RetroArch handhelds" width="100%">

<br>

![Python](https://img.shields.io/badge/python-3.8%2B-f8c000?style=for-the-badge&labelColor=100e08)
![Platform](https://img.shields.io/badge/platform-win%20%7C%20mac%20%7C%20linux-38c020?style=for-the-badge&labelColor=100e08)
![Cartridge only](https://img.shields.io/badge/cartridge%20ROMs-only-d82800?style=for-the-badge&labelColor=100e08)
![Resumable](https://img.shields.io/badge/resumable-yes-f8c000?style=for-the-badge&labelColor=100e08)

**▲  Compress retro cartridge ROMs into RetroArch-ready `.zip` archives — with an 8-bit terminal UI.  ▲**

</div>

<div align="center"><img src="assets/divider.png" alt="tetromino divider" width="60%"></div>

`rom_stuffer` is a command-line Python utility for fitting the **most games onto an SD card** for retro handhelds. It has three capabilities, all sharing the same safety guards, themed TUI, and reporting:

- **`compress`** — pack each ROM into its own highly-compatible `.zip`, moving the originals to a backup while preserving your folder structure.
- **`dedup`** — find byte-identical duplicate ROMs and quarantine the extras (reversible by default).
- **`estimate`** — report, per system and in total, how much space a library will take once compressed and de-duplicated.

It is built for preparing SD cards for retro handheld consoles (R36S, R36XX, Ayn Thor, Miyoo Mini, etc.) running RetroArch-based systems (ArkOS, AmberELEC, OnionOS).

**Repository:** [https://github.com/Tasogarre/rom-stuffer](https://github.com/Tasogarre/rom-stuffer)

---

## ⚠️ CRITICAL WARNING: Cartridge-Based Systems Only!

This script is designed **exclusively** for cartridge-based systems, such as:
- Nintendo Entertainment System (NES)
- Super Nintendo (SNES)
- Game Boy / Game Boy Color / Game Boy Advance (GB, GBC, GBA)
- Sega Genesis / Mega Drive

**DO NOT** use this script for CD-based games (e.g., PlayStation 1, Sega Saturn, Sega CD, Dreamcast). Emulators do not efficiently read large disc images (`.bin`/`.cue`, `.iso`) from `.zip` files. Doing so will result in massive load times, audio stuttering, or complete crashes. For CD-based games, use a tool like `chdman` to convert them to `.chd` format instead.

---

## Why Use This?

1. **Saves SD Card Space:** Compresses your ROMs using standard DEFLATE compression.
2. **Optimised for Emulators:** Emulators hate "solid" archives or ZIPs with multiple games in them. `rom_stuffer` ensures every single ROM gets its own individual `.zip` file, which is exactly what RetroArch expects.
3. **Fast Decompression:** Uses "Normal" compression level (6) rather than "Ultra." This ensures that lower-powered handhelds can decompress the game on-the-fly without stuttering.
4. **Organised Backups:** Moving your uncompressed files into a single dump folder is messy. `rom_stuffer` recreates your exact subdirectory structure in the backup folder automatically.
5. **SD Card Fast-Sync:** Built-in sequential 4 MB-buffered bulk I/O allows you to reconcile newly compressed files directly to your SD card. It auto-deletes the old uncompressed files, writes the new zip, and fsyncs to confirm the data is durable.
6. **De-duplication:** Finds byte-identical copies of the same ROM (even a raw file vs. a zipped one) and reclaims the wasted space — quarantining the extras to a reversible backup by default. See [De-duplication](#de-duplication).
7. **Space estimates:** Before you commit, see per-system and total figures for what a library will occupy once compressed and de-duplicated. See [Estimating space](#estimating-space).
8. **Detailed Reporting:** Calculates space saved, lists exactly which folders were modified, and outputs a report to the screen (a themed TUI) and to a text log file, plus a rotating diagnostic log. See [Logging](#logging).
9. **Resumable:** Checkpoints progress as it goes, so an interrupted run over tens of thousands of files picks up where it left off instead of rescanning your whole library. See [Resuming an interrupted job](#resuming-an-interrupted-job).

---

## ▲ Preview

<div align="center">

<img src="assets/screenshot-tetris.png" alt="ROM Stuffer running in the tetris theme" width="80%">

<sub>The interactive UI in the default **tetris** theme — switch any time with `--theme kirby|zelda|metroid`. See [Themes](#themes).</sub>

</div>

<div align="center"><img src="assets/divider.png" alt="tetromino divider" width="60%"></div>

## Requirements

- **OS:** Windows, macOS, or Linux
- **Python:** 3.8 or higher
- **Dependencies:** The `rich` library (`pip install -r requirements.txt`)

---

## Quick Start

From zero to your first compressed batch:

```bash
# 1. Clone the repository
git clone https://github.com/Tasogarre/rom-stuffer.git
cd rom-stuffer

# 2. Install the single dependency
pip install -r requirements.txt

# 3. See how much space you'd save (read-only, nothing is touched)
python rom_stuffer.py estimate --source "/path/to/your/roms"

# 4. Preview the compression (no files are modified)
python rom_stuffer.py compress \
  --source "/path/to/your/roms" \
  --dest "/path/to/your/backup" \
  --dry-run

# 5. Run for real (interactive — asks about each extension it finds)
python rom_stuffer.py compress \
  --source "/path/to/your/roms" \
  --dest "/path/to/your/backup"

# 6. Reclaim space from byte-identical duplicates (quarantined, reversible)
python rom_stuffer.py dedup \
  --source "/path/to/your/roms" \
  --dest "/path/to/your/backup"
```

Run `python rom_stuffer.py` with no arguments for an interactive menu that walks you
through picking a command.

### The three commands

| Command | What it does |
| --- | --- |
| [`compress`](#usage) | Pack each ROM into its own `.zip`, back up the originals. |
| [`dedup`](#de-duplication) | Find byte-identical duplicate ROMs and quarantine the extras. |
| [`estimate`](#estimating-space) | Report per-system and total space the library will need. |

> **Windows users:** Use `python` or `py` instead of `python3`, and wrap paths in double quotes:
> `python rom_stuffer.py compress --source "E:\ROMS" --dest "D:\RetroBackups"`

---

## SD Card Setup

### Step 1 — Find your SD card path

**macOS:**
```bash
# List all disks; look for your SD card (e.g. "disk2s1")
diskutil list

# The mount point is usually under /Volumes/
ls /Volumes/
# e.g. /Volumes/SDCARD  or  /Volumes/ROMS
```

**Linux:**
```bash
# List block devices and their mount points
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT

# SD cards are typically mounted under /media/ or /mnt/
ls /media/$USER/
# e.g. /media/marcus/SDCARD
```

**Windows:**
```
Open File Explorer → This PC
Note the drive letter assigned to the SD card (e.g. F:\)
```

### Step 2 — Understand the folder structure

`rom_stuffer` preserves your relative directory tree. If your PC ROMs are at:
```
C:\MyROMs\gba\Mario.gba
C:\MyROMs\snes\Zelda.sfc
```
After running with `--sdcard F:\`:
- Your PC: `C:\MyROMs\gba\Mario.zip` (the new zip)
- Your backup: `D:\Backup\gba\Mario.gba` (the original, safely moved)
- Your SD card: `F:\gba\Mario.zip` (synced to the card)

The SD card's old `F:\gba\Mario.gba` is deleted **before** the new zip is written. This is intentional — cards are often nearly full and cannot hold both at once. The zip already exists locally, so the card is always recoverable by re-running.

> [!NOTE]
> **Same-named games:** If two ROMs in the same folder share a name but differ in extension (e.g. `Mario.gb` and `Mario.gbc`), they would both map to `Mario.zip`. To avoid silently overwriting one, the second gets a disambiguated name: `Mario.zip` and `Mario_gbc.zip`. The ROM's real filename is preserved *inside* the archive, so emulators still load it correctly. This also protects any pre-existing `.zip` already in the folder from being overwritten.

### Step 3 — Run with SD sync

```bash
# macOS example
python rom_stuffer.py compress \
  --source "/Users/marcus/ROMs" \
  --dest "/Users/marcus/ROMs_backup" \
  --sdcard "/Volumes/SDCARD"

# Windows example
python rom_stuffer.py compress \
  --source "C:\MyROMs" \
  --dest "D:\Backups" \
  --sdcard "F:\"

# Linux example
python rom_stuffer.py compress \
  --source "/home/marcus/roms" \
  --dest "/home/marcus/roms_backup" \
  --sdcard "/media/marcus/SDCARD"
```

> **Space note:** The script deletes the old uncompressed file from the SD card first, then copies the new `.zip`. This is by design for nearly-full cards. The new zip is always written to your PC first, so you can safely re-run if anything interrupts the SD sync.

> **After the run:** Safely eject your SD card before unplugging it. On macOS: right-click the volume in Finder → Eject. On Linux: `sudo umount /media/marcus/SDCARD`.

---

## Usage

`rom_stuffer` has three subcommands — `compress`, `dedup`, and `estimate`. Launch it
with **no arguments** for an interactive menu that walks you through choosing one and
filling in every option, so there are no flags to remember:

```bash
python rom_stuffer.py
```

Or name a subcommand directly. This section covers `compress`; see
[De-duplication](#de-duplication) and [Estimating space](#estimating-space) for the
other two.

### `compress`

Packs each ROM into its own `.zip` and moves the original to your backup. Run it with
no flags beyond a source and it prompts interactively for the rest: **destination**,
**dry-run** (preview) mode, **recursive** scanning, **compression level** (1–9,
default 6), and **SD card** sync. It then scans, groups the ROMs it finds by
extension, and asks whether to compress each type. If a previous run was interrupted,
it also offers to [resume](#resuming-an-interrupted-job). Anything you don't pass is
asked interactively.

```bash
# Pass what you know and be prompted for the rest
python rom_stuffer.py compress --source "<source_directory>" --dest "<backup_directory>"

# Or target a single extension headlessly (no prompts)
python rom_stuffer.py compress -s "<source>" -d "<backup>" --type .gba
```

| Argument | Short | Description |
| :--- | :--- | :--- |
| `--source` | `-s` | **(Required)** The directory to scan for ROMs. Searched recursively through all subfolders by default. |
| `--dest` | `-d` | **(Required)** The destination directory where the original, uncompressed files will be safely moved. Must differ from `--source`. |
| `--type` | `-t` | **(Optional)** A specific file extension to target (e.g. `.gba`). Bypasses interactive prompts and processes only that extension. |
| `--sdcard` | `-sd` | **(Optional)** SD card directory to sync newly compressed `.zip` files to. Old uncompressed versions on the card are automatically deleted first. |
| `--dry-run` | | **(Optional)** Preview what will happen without modifying any files. Space savings in the report are estimates. |
| `--no-recursive` | | **(Optional)** Scan only the top-level source folder; do not descend into sub-folders. |
| `--level` | `-l` | **(Optional)** DEFLATE compression level 1–9. Default: `6` (Normal). Level 6 is the recommended balance for RetroArch handhelds — do not go higher without testing on your device. |
| `--resume` | | **(Optional)** Resume a previously interrupted job from its saved progress, skipping the full rescan. See [Resuming an interrupted job](#resuming-an-interrupted-job). |
| `--fresh` | | **(Optional)** Discard any saved progress in the destination and start a brand-new scan. |

### Options shared by every command

| Argument | Description |
| :--- | :--- |
| `--theme` | Visual theme: `tetris` (default), `kirby`, `zelda`, or `metroid`. See [Themes](#themes). |
| `--verbose` | Log at DEBUG level for extra diagnostic detail. See [Logging](#logging). |
| `--log-dir` | Directory for the rotating diagnostic log. Default: `~/.rom_stuffer/logs/`. |
| `--help` / `-h` | Show help and exit. Works on the top level and on each subcommand (e.g. `dedup --help`). |

---

## De-duplication

Retro libraries collect duplicates: the same game re-downloaded, a regional variant
that's byte-for-byte identical, or a raw ROM sitting next to an already-zipped copy of
itself. `dedup` finds these and reclaims the wasted space.

<div align="center">

<img src="assets/screenshot-dedup.png" alt="rom_stuffer dedup: duplicate groups, keeper selection, and a dry-run summary in the tetris theme" width="90%">

</div>

**How it decides two files are the same.** Matching is on *logical content*, not
filename. A raw `Game.gb` and a `Game.zip` containing that exact ROM hash equal — the
zip is streamed and compared by its decompressed bytes. Detection is staged so it
never hashes more than it must: files are grouped by size, then by a CRC-32
fingerprint of a prefix, and only the survivors get a full SHA-256 confirmation.

**Nothing dangerous is ever a duplicate.** BIOS files and disc images (`.bin`/`.cue`
and friends) are excluded from grouping entirely, the same allowlist that protects
`compress`. A group is only ever formed from real cartridge ROMs.

**One keeper per group, and it is never destroyed.** From each set of identical files,
one is kept and the rest are marked for removal. The keeper heuristic prefers,
in order: an already-compressed `.zip`, then the shortest path, then the shortest name
(so `Sonic.md` wins over `Sonic (J) (dupe).md`). You can steer it:

| Argument | Description |
| :--- | :--- |
| `--source` / `-s` | **(Required)** Directory to scan for duplicates. |
| `--dest` / `-d` | Backup/quarantine directory. Removed files are moved here (preserving structure) so the operation is reversible. |
| `--keeper-order` | Comma-separated keeper preference, e.g. `zip,shortest-path,shortest-name`. |
| `--protect` | A path or glob whose files may never be removed — always chosen as the keeper. |
| `--per-system` | Only ever match files within the same system folder, never across systems. |
| `--min-size` | Ignore files smaller than this (e.g. `64k`), avoiding noise from tiny saves. |
| `--hard-delete` | Delete removals outright instead of quarantining them. **Not** the default. |
| `--dry-run` | Detect and report only; change nothing. |

**Quarantine by default — the operation is reversible.** Unless you pass
`--hard-delete`, every removed file is *moved* into `--dest`, mirroring its original
folder layout. Nothing is erased; if the plan removed something you wanted, move it
back.

**Preview, edit, apply.** A run detects duplicates, writes an editable **plan file**
and a hash index (so a re-run doesn't re-hash unchanged files), and shows a review
screen listing each group's keeper and removals before anything moves. Delete a line
from the plan and that file is left alone. A `rom_stuffer_report.txt` summarising kept
vs. removed and bytes reclaimed is written to the backup directory.

```bash
# Preview what dedup would reclaim, touching nothing
python rom_stuffer.py dedup -s "/path/to/roms" -d "/path/to/backup" --dry-run

# Reclaim space, quarantining removals into the backup (reversible)
python rom_stuffer.py dedup -s "/path/to/roms" -d "/path/to/backup"

# Only match within a system, ignore files under 64 KB, protect your curated folder
python rom_stuffer.py dedup -s "/path/to/roms" -d "/path/to/backup" \
  --per-system --min-size 64k --protect "**/Favorites/**"
```

---

## Estimating space

Before you compress or dedup anything, `estimate` tells you what you're working with:
per system and in total, how much space the library takes now, how much it will take
once each ROM is compressed, and how much de-duplication could reclaim. It is
completely **read-only** — it only measures.

<div align="center">

<img src="assets/screenshot-estimate.png" alt="rom_stuffer estimate: a per-system table of decompressed, compressed, and reclaimable bytes with a total footprint in the tetris theme" width="90%">

</div>

```bash
# Whole library, per-system breakdown + total
python rom_stuffer.py estimate --source "/path/to/roms"

# Just the top-level totals, don't descend into sub-folders
python rom_stuffer.py estimate -s "/path/to/roms" --no-recursive
```

| Argument | Description |
| :--- | :--- |
| `--source` / `-s` | **(Required)** Directory to measure. |
| `--per-system` | Show the per-system table (on by default). |
| `--no-recursive` | Measure only the top-level folder. |

The compressed figure is an estimate (it assumes a typical cartridge-ROM compression
ratio), so treat it as a planning number, not a guarantee. BIOS and disc files are
excluded from the estimate for the same reason they're excluded everywhere else.

---

## Logging

Every run writes a rotating diagnostic log to `~/.rom_stuffer/logs/` (5 files of up to
1 MB each) in addition to the on-screen report. This is where file-level warnings —
a ROM that failed to compress, a duplicate that couldn't be moved — are recorded, so a
long overnight run leaves a trail you can inspect afterwards.

- `--verbose` raises the log to DEBUG level for extra detail.
- `--log-dir "<dir>"` writes the log somewhere else instead.

---

## Themes

The interactive UI ships with four retro 8-bit skins, each with an original pixel-art emblem and its own palette. Launch with no arguments and it asks which you'd like; or pick one up front with `--theme`:

```bash
python rom_stuffer.py --theme tetris     # tetromino board (default)
python rom_stuffer.py --theme kirby      # pink star
python rom_stuffer.py --theme zelda      # gold triangle emblem
python rom_stuffer.py --theme metroid    # bio-cyan creature
```

Each theme re-skins the entire interface — banner, panels, section rules, progress bars, and summary colours. Emblems are original geometric pixel-art, not reproductions of any character.

**Want your own emblem art?** Drop a pixel image you have the rights to and it becomes the emblem — no code changes. See [Supplying your own theme art](docs/THEME_ART.md).

<table>
<tr>
<td width="50%" align="center">

**`tetris`** *(default)*<br>
<sub>Tetromino board · "Pack them tight."</sub>

<img src="assets/screenshot-tetris.png" alt="tetris theme" width="100%">

</td>
<td width="50%" align="center">

**`kirby`**<br>
<sub>Pink pixel star · "Inhale the clutter."</sub>

<img src="assets/screenshot-kirby.png" alt="kirby theme" width="100%">

</td>
</tr>
<tr>
<td width="50%" align="center">

**`zelda`**<br>
<sub>Gold triangle emblem · Link-green</sub>

<img src="assets/screenshot-zelda.png" alt="zelda theme" width="100%">

</td>
<td width="50%" align="center">

**`metroid`**<br>
<sub>Samus-orange · bio-cyan creature</sub>

<img src="assets/screenshot-metroid.png" alt="metroid theme" width="100%">

</td>
</tr>
</table>

<div align="center"><img src="assets/divider.png" alt="tetromino divider" width="60%"></div>

## Resuming an interrupted job

For large collections (tens of thousands of files), a run can be interrupted — a full SD card, an unplugged drive, a `Ctrl-C`, or a crash. **rom_stuffer checkpoints its progress so it can pick up where it left off without rescanning your entire library.**

### How it works

As soon as processing begins, the tool writes two small hidden files into your **destination** (backup) folder:

- `.rom_stuffer_state.json` — the full list of files this job will process.
- `.rom_stuffer_journal.log` — an append-only record of every file completed so far (flushed after each file, so an interruption loses nothing).

If a run is interrupted, these files remain. The next run detects them.

### Resuming (interactive)

Just run the same command again. The tool notices the incomplete job and asks:

```
Found an incomplete job in this destination:
  source:   /Volumes/ROMS
  progress: 22,431 / 40,002 done  (17,571 remaining)
Resume where it left off (skip the full rescan)? [y/n] (y):
```

Answer **y** and it processes only the remaining files — no rescan, no re-prompting for which extensions to compress.

### Resuming (headless / scripted)

Pass `--resume` to skip the prompt, or `--fresh` to ignore the saved progress and start over:

```bash
# Continue the interrupted job
python rom_stuffer.py compress -s "/Volumes/ROMS" -d "/backup" -sd "/Volumes/SDCARD" --resume

# Or throw away the saved progress and rescan from scratch
python rom_stuffer.py compress -s "/Volumes/ROMS" -d "/backup" --fresh
```

### Good to know

- **Files that failed are retried, not skipped.** If some files errored (e.g. a momentary card disconnect), the saved progress is kept and the summary tells you to re-run with `--resume` to retry just those. Successful files are never reprocessed.
- **On a clean finish the state files are removed automatically** — no manual cleanup.
- **The saved job is tied to its source.** If you point a *different* source at a destination that already has a saved job, the tool refuses (to avoid mixing two jobs) and tells you to use `--fresh` or a different destination.
- **Dry runs never write state**, since they change nothing.

---

## Supported Extensions

The built-in library recognises the following cartridge ROM extensions automatically:

- **Nintendo:** `.nes`, `.sfc`, `.smc`, `.fig`, `.swc`, `.gb`, `.gbc`, `.gba`, `.fds`, `.vb`, `.vboy`, `.min`, `.mgw`
- **Sega:** `.bin`, `.gen`, `.md`, `.smd`, `.sms`, `.gg`, `.sg`, `.32x`
- **NEC:** `.pce`, `.sgx`
- **Atari:** `.a26`, `.a52`, `.a78`, `.j64`, `.lnx`, `.atr`, `.atx`, `.xfd`, `.xex`, `.cas`, `.st`
- **Commodore:** `.crt`, `.d64`, `.t64`, `.prg`, `.tap`, `.d81`, `.g64`
- **Amiga:** `.adf`, `.dms`, `.fdi`, `.ipf`, `.hdf`, `.hdz`
- **Home Computers:** `.msx`, `.rom`, `.dsk`, `.z80`, `.tzx`, `.cdt`
- **Other:** `.ws`, `.wsc`, `.ngp`, `.ngc`, `.col`, `.int`, `.vec`, `.chf`, `.o2`

> [!IMPORTANT]
> **`.bin` is handled with care.** The `.bin` extension is used both by Sega Genesis / Atari 2600 **cartridge** dumps (safe to compress) *and* by CD/GD-ROM **disc images** (PS1, Saturn, Sega CD, **Dreamcast**, PC Engine CD) and **BIOS** files (never safe). rom_stuffer automatically **refuses** a `.bin` when it looks like a disc image or BIOS — if it sits in a disc-system or `bios` folder, has a companion `.cue`/`.gdi` descriptor, or is larger than a cartridge could be (>16 MB) — and lists the reason in the report. Genuine cartridge `.bin` dumps are still compressed normally.

> [!NOTE]
> **CD-Based Systems Exclusion:** Disc images (PS1, Sega CD, Saturn, Dreamcast) are completely excluded. Emulators must seek and stream large tracks directly from the file, and `.zip` extraction overhead will cause severe stuttering. Use `.chd` format instead.

> [!NOTE]
> **N64 / NDS Exclusion:** Nintendo 64 and Nintendo DS extensions are explicitly excluded. The overhead of extracting these larger files from `.zip` archives on lower-powered devices can severely exacerbate audio/video stuttering.

> [!NOTE]
> **MAME / Arcade Exclusion:** Arcade ROMs are not supported by this tool because they are already distributed and required to be in `.zip` or `.7z` format by default. You should never decompress MAME ROMs.

---

## Examples

### Example 1: Interactive Scan (Recommended for first run)

Scanning your entire ROMs folder and backing up originals to an external drive:

```bash
python rom_stuffer.py compress --source "E:\ROMS" --dest "D:\RetroBackups\Uncompressed"
```

The script will find `.gba` games, list the folders they are in, ask if you want to compress them, then move on to `.nes`, `.sfc`, etc.

### Example 2: Headless / Automated Usage

Bypass the interactive prompts and compress only a specific format (e.g. SNES):

```bash
python rom_stuffer.py compress -s "E:\ROMS\snes" -t ".sfc" -d "D:\Backups\snes_raw"
```

**Result:**
- `E:\ROMS\snes\Action\Super Metroid.zip`
- `D:\Backups\snes_raw\Action\Super Metroid.sfc` (original safely moved)

### Example 3: Full SD Card Fast-Sync

Compress your local PC ROMs, back up the originals locally, and push the new `.zip` files directly to your inserted SD card:

```bash
python rom_stuffer.py compress -s "C:\MyROMs" -d "D:\RetroBackups" -sd "F:\"
```

The script will:
1. Find `C:\MyROMs\gba\Mario.gba`
2. Compress it to `C:\MyROMs\gba\Mario.zip`
3. Delete `F:\gba\Mario.gba` from the SD card (to free space)
4. Copy `Mario.zip` to `F:\gba\Mario.zip` using a 4 MB sequential buffer and fsync
5. Move `C:\MyROMs\gba\Mario.gba` to `D:\RetroBackups\gba\Mario.gba`

### Example 4: Dry Run Before Committing

Always preview before running on a large collection:

```bash
python rom_stuffer.py compress \
  -s "/Volumes/SDCARD/roms" \
  -d "/Users/marcus/roms_backup" \
  --dry-run
```

No files are touched. The report shows estimated space savings and which folders would be affected.

### Example 5: Estimate Before You Start

See the per-system and total footprint before compressing or de-duplicating anything:

```bash
python rom_stuffer.py estimate --source "/Volumes/ROMS"
```

Read-only. Reports decompressed size, estimated compressed size, and how much
de-duplication could reclaim, per system and in total. See [Estimating space](#estimating-space).

### Example 6: Reclaim Duplicates (Reversible)

Find byte-identical duplicate ROMs and quarantine the extras into your backup so the
operation can be undone:

```bash
python rom_stuffer.py dedup -s "/Volumes/ROMS" -d "/Users/marcus/roms_backup"
```

Preview first with `--dry-run`; removed files are moved (not deleted) into `--dest`
unless you pass `--hard-delete`. See [De-duplication](#de-duplication).
