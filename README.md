# rom_stuffer

**Repository:** [https://github.com/Tasogarre/rom_stuffer](https://github.com/Tasogarre/rom_stuffer)

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

## Requirements

*   **OS:** Windows, macOS, or Linux.
*   **Python:** Python 3.6 or higher must be installed on your system.
*   No external pip packages are required; it uses entirely built-in Python libraries.

## Usage

Open your terminal or Command Prompt and run the script using the following syntax:

```bash
python compress_roms.py --source "<source_directory>" --type "<file_extension>" --dest "<backup_directory>"
```

### CLI Arguments

| Argument | Short | Description |
| :--- | :--- | :--- |
| `--source` | `-s` | **(Required)** The directory to scan for ROMs. The script searches recursively through all subfolders. |
| `--type` | `-t` | **(Required)** The file extension to target (e.g., `.gba`, `.sfc`, `.nes`). You do not strictly need the leading dot, but it is recommended. |
| `--dest` | `-d` | **(Required)** The destination directory where the original, uncompressed files will be safely moved. |
| `--help` | `-h` | Shows the help menu and exits. |

## Examples

### Example 1: Basic Windows Usage
Compressing all Game Boy Advance games on your SD card and backing up the originals to an external hard drive:

```cmd
python compress_roms.py --source "E:\ROMS\gba" --type ".gba" --dest "D:\RetroBackups\Uncompressed\GBA"
```

### Example 2: Deeply Nested Folders
If your source folder looks like this:
```text
E:\ROMS\snes\
├── Action\
│   └── Super Metroid.sfc
└── RPG\
    └── Chrono Trigger.sfc
```

Running the script:
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
