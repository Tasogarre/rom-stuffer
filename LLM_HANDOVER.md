# LLM Handover Document: rom_stuffer

**Repository:** [https://github.com/Tasogarre/rom_stuffer](https://github.com/Tasogarre/rom_stuffer)

## Introduction
Hello! If you are an AI reading this, this document brings you fully up to speed on the `rom_stuffer` project. This project was conceptualized and built to solve a specific workflow for managing retro gaming ROMs on Windows, specifically targeting handheld emulator devices like the R36S, R36XX, and Ayn Thor.

## Project Purpose
The core objective is to have a command-line script that:
1. Recursively scans a specified source directory for a specific ROM file extension (e.g., `.gba`).
2. Compresses each matching ROM file into its *own individual* `.zip` archive.
3. Moves the original, uncompressed ROM file to a specified backup destination folder.
4. Preserves the original relative directory structure within the backup destination.

## Background Research
During the planning phase, we researched ZIP compression compatibility with **RetroArch** (the underlying emulator layer for OSes like ArkOS and AmberELEC used on these handhelds):
*   **Compression Level:** RetroArch relies on standard `zlib` for decompression. Using "Maximum" or "Ultra" compression levels can cause noticeable lag or stuttering on lower-powered handhelds during load times. "Normal" (Level 6 DEFLATE) compression was chosen as the optimal balance between file size reduction and decompression speed.
*   **Archive Grouping:** Emulators struggle with "solid" archives or ZIPs containing multiple games. The strict requirement is **one ROM per ZIP file**, named identically to the ROM.
*   **Cartridge vs. CD-Based:** 
    *   *Cartridge Systems* (NES, SNES, Genesis, GBA) work perfectly from `.zip` archives because the emulator loads the entire file into RAM.
    *   *CD-Based Systems* (PS1, Saturn, Sega CD) **do not** run well from `.zip` files because they require random access to track data. `.chd` or `.pbp` formats are the community standard for disc games.

## Decisions Made & Scope Codification
We engaged in a Q&A to nail down the exact technical requirements. Here are the decisions we made:
1.  **Language:** Python was chosen over PowerShell for better cross-platform compatibility, readability, and ease of maintenance, despite the user running it on Windows.
2.  **Archive Grouping:** 1:1 mapping. Each ROM gets its own ZIP.
3.  **Recursive Scanning:** The script must dig through all subfolders in the source directory.
4.  **Directory Structure:** When the original uncompressed file is moved to the backup location, the script must recreate the original subdirectory tree so the backups remain organized.
5.  **Compression Level:** "Normal" (DEFLATE Level 6) is hardcoded via `zipfile.ZIP_DEFLATED`.
6.  **Scope Limitation:** The script is strictly for cartridge-based games. We explicitly decided *not* to support CD-based games, and added warnings to the terminal output and README to reflect this.

## What Has Been Built
1.  `compress_roms.py`: The main Python script. It uses `argparse` for CLI inputs, `pathlib` for robust path manipulation and recursive scanning (`rglob`), `zipfile` for standard compression, and `shutil` for moving files.
2.  `README.md`: Comprehensive documentation for the user, detailing usage, requirements, and the explicit warnings regarding CD-based games.

## Current Status
The script is complete, functional, and resides in the project folder. All initial requirements have been met. Any future work will likely revolve around edge cases (e.g., handling duplicate files in the destination, adding parallel processing for speed, or supporting multiple file extensions simultaneously).
