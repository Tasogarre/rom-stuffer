# rom_stuffer

**Repository:** [https://github.com/Tasogarre/rom-stuffer](https://github.com/Tasogarre/rom-stuffer)

`rom_stuffer` is a command-line Python utility designed to streamline the management of retro gaming ROMs. It recursively scans a directory for specific ROM files, compresses each game into its own highly-compatible `.zip` archive, and safely moves the original uncompressed files to a backup location while perfectly preserving your folder structure.

This tool is specifically optimized for users preparing SD cards for retro handheld consoles (like the R36S, R36XX, Ayn Thor, Miyoo Mini, etc.) running RetroArch-based operating systems (ArkOS, AmberELEC, OnionOS).

---

## ⚠️ CRITICAL WARNING: Cartridge-Based Systems Only!

This script is designed **exclusively** for cartridge-based systems, such as:
*   Nintendo Entertainment System (NES)
*   Super Nintendo (SNES)
*   Game Boy / Game Boy Color / Game Boy Advance (GB, GBC, GBA)
*   Sega Genesis / Mega Drive

**DO NOT** use this script for CD-based games (e.g., PlayStation 1, Sega Saturn, Sega CD, Dreamcast). Emulators do not efficiently read large disc images (`.bin`/`.cue`, `.iso`) from `.zip` files. Doing so will result in massive load times, audio stuttering, or complete crashes. For CD-based games, use a tool like `chdman` to convert them to `.chd` format instead.

---

## Why Use This?

1.  **Saves SD Card Space:** Compresses your ROMs using standard DEFLATE compression.
2.  **Optimized for Emulators:** Emulators hate "solid" archives or ZIPs with multiple games in them. `rom_stuffer` ensures every single ROM gets its own individual `.zip` file, which is exactly what RetroArch expects.
3.  **Fast Decompression:** Uses "Normal" compression levels rather than "Ultra." This ensures that lower-powered handhelds can instantly decompress the game on-the-fly without stuttering.
4.  **Organized Backups:** Moving your uncompressed files into a single dump folder is messy. `rom_stuffer` recreates your exact subdirectory structure in the backup folder automatically.
5.  **SD Card Fast-Sync:** Built-in sequential 16MB-buffered bulk I/O allows you to reconcile newly compressed files directly to your SD card. It auto-deletes the old uncompressed files and maximizes flash-memory write speeds.
6.  **Detailed Reporting:** Calculates space saved, lists exactly which folders were modified, and outputs a detailed error report both to the screen (via a beautiful TUI) and to a text log file.

## Requirements

*   **OS:** Windows, macOS, or Linux.
*   **Python:** Python 3.6 or higher must be installed on your system.
*   **Dependencies:** The `rich` Python library is required for the Text User Interface and reporting.

## Installation

To use `rom_stuffer`, you can clone the repository to your local machine:

```bash
git clone https://github.com/Tasogarre/rom-stuffer.git
cd rom-stuffer
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

Then, run the tool using Python!

## Usage

By default, `rom_stuffer` runs in **Interactive Mode**. It will scan the source directory for all recognized cartridge ROM extensions, group them, and ask you if you want to process each type.

Open your terminal or Command Prompt and run the script using the following syntax:

```bash
python compress_roms.py --source "<source_directory>" --dest "<backup_directory>" --sdcard "<sd_card_drive>"
```

### Supported Extensions

The built-in library recognizes the following cartridge ROM extensions automatically:

*   **Nintendo:** `.nes`, `.sfc`, `.smc`, `.fig`, `.swc`, `.gb`, `.gbc`, `.gba`, `.fds`, `.vb`, `.vboy`, `.min`, `.mgw`
*   **Sega:** `.bin`, `.gen`, `.md`, `.smd`, `.sms`, `.gg`, `.sg`, `.32x`
*   **NEC:** `.pce`, `.sgx`
*   **Atari:** `.a26`, `.a52`, `.a78`, `.j64`, `.lnx`, `.atr`, `.atx`, `.xfd`, `.xex`, `.cas`, `.st`
*   **Commodore:** `.crt`, `.d64`, `.t64`, `.prg`, `.tap`, `.d81`, `.g64`
*   **Amiga:** `.adf`, `.dms`, `.fdi`, `.ipf`, `.hdf`, `.hdz`
*   **Home Computers:** `.msx`, `.rom`, `.dsk`, `.z80`, `.tzx`, `.cdt`
*   **Other:** `.ws`, `.wsc`, `.ngp`, `.ngc`, `.col`, `.int`, `.vec`, `.chf`, `.o2`

> [!NOTE]
> **CD-Based Systems Exclusion:** Disc images (PS1, Sega CD, Saturn, Dreamcast) are completely excluded. Emulators must seek and stream large tracks directly from the file, and `.zip` extraction overhead will cause severe stuttering. Use `.chd` format instead.

> [!NOTE]
> **N64 / NDS Exclusion:** Nintendo 64 and Nintendo DS extensions are explicitly excluded. The overhead of extracting these larger files from `.zip` archives on lower-powered devices can severely exacerbate audio/video stuttering.

> [!NOTE]
> **MAME / Arcade Exclusion:** Arcade ROMs are not supported by this tool because they are already distributed and required to be in `.zip` or `.7z` format by default. You should never decompress MAME ROMs.

### CLI Arguments

| Argument | Short | Description |
| :--- | :--- | :--- |
| `--source` | `-s` | **(Required)** The directory to scan for ROMs. The script searches recursively through all subfolders. |
| `--dest` | `-d` | **(Required)** The destination directory where the original, uncompressed files will be safely moved. |
| `--type` | `-t` | **(Optional)** A specific file extension to target (e.g., `.gba`). If provided, it bypasses the interactive prompts and only processes this exact type. |
| `--sdcard` | `-sd` | **(Optional)** A destination SD Card directory to immediately sync newly compressed `.zip` files to. Old uncompressed versions on the SD card will be automatically deleted. |
| `--dry-run` | | **(Optional)** Preview what will happen without actually modifying or copying any files. Generates the report based on estimates. |
| `--help` | `-h` | Shows the help menu and exits. |

## Examples

### Example 1: Interactive Scan (Recommended)
Scanning your entire SD card ROMs folder and backing up originals to an external drive:

```bash
python compress_roms.py --source "E:\ROMS" --dest "D:\RetroBackups\Uncompressed"
```

*The script will find `.gba` games, list the folders they are in, ask if you want to compress them, then move on to `.nes`, `.sfc`, etc.*

### Example 2: Headless/Automated Usage
If you want to bypass the interactive prompts (e.g., in a script) and only compress a specific format like SNES:

```bash
python compress_roms.py -s "E:\ROMS\snes" -t ".sfc" -d "D:\Backups\snes_raw"
```

**The Result:**
Your SD card (`E:\ROMS\snes\`) will now contain:
*   `Action\Super Metroid.zip`
*   `RPG\Chrono Trigger.zip`

Your backup drive (`D:\Backups\snes_raw\`) will automatically have the folders created and contain:
*   `Action\Super Metroid.sfc`
*   `RPG\Chrono Trigger.sfc`

### Example 3: SD Card Fast-Sync
If you want to compress your local PC ROMs, back up the originals locally, but instantly push the new `.zip` versions out to your inserted SD Card while deleting the uncompressed versions off the SD Card:

```bash
python compress_roms.py -s "C:\MyROMs" -d "D:\RetroBackups" -sd "F:\"
```

*The script will find `C:\MyROMs\gba\game.gba`, compress it to `game.zip`, move the original to `D:\RetroBackups\gba\game.gba`. Then, it will check `F:\gba\game.gba`. If it exists, it deletes it from the SD card and copies the new `game.zip` to the SD card at extremely high speeds using a 16MB sequential buffer.*
