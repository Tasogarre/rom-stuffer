# LLM Handover Document: rom-stuffer

**Repository:** [https://github.com/Tasogarre/rom-stuffer](https://github.com/Tasogarre/rom-stuffer)

## Introduction
Hello! If you are an AI reading this, this document brings you fully up to speed on the `rom-stuffer` project. This project was conceptualized and built to solve a specific workflow for managing retro gaming ROMs on Windows, specifically targeting handheld emulator devices like the R36S, R36XX, and Ayn Thor.

## Project Purpose
The core objective is to have a robust script that:
1. Recursively scans a specified source directory for cartridge-based ROM file extensions.
2. Compresses each matching ROM file into its *own individual* `.zip` archive.
3. Moves the original, uncompressed ROM file to a specified backup destination folder while preserving the relative directory tree.
4. Reconciles and fast-syncs the newly compressed `.zip` files directly to a mounted SD Card.

## Phase 1: Core Foundation & Rules
During the planning phase, we researched ZIP compression compatibility with **RetroArch**:
*   **Compression Level:** RetroArch relies on standard `zlib`. "Ultra" compression can cause lag on lower-powered handhelds. "Normal" (Level 6 DEFLATE) was hardcoded as the optimal balance.
*   **Archive Grouping:** The strict requirement is **one ROM per ZIP file**, named identically to the ROM.
*   **Cartridge vs. CD-Based:** Cartridge Systems (NES, GBA) work perfectly from `.zip`. CD-Based Systems (PS1, Sega CD) **do not** run well from `.zip`. We explicitly codified this and excluded CD-based extensions from our supported lists.
*   **N64 & MAME Exclusions:** We explicitly excluded N64 from `.zip` automation due to performance overhead on low-end devices. MAME was excluded because arcade ROMs are naturally distributed as highly-dependent zip archives and shouldn't be touched.

## Phase 2: TUI and Reporting
We transitioned the script from a basic CLI tool to a rich Text User Interface (TUI).
*   **Rich Integration:** We introduced the `rich` Python library (`requirements.txt`). This provided interactive `[y/n]` prompts per file extension, progress bars for compression batches, and styled tables for outputs.
*   **Metrics Engine:** We implemented a `SessionMetrics` class to track total files, success/fail counts, and the exact byte-size before and after compression to calculate total "Space Saved".
*   **Log Generation:** At the end of a session, a detailed table report is rendered to the screen and automatically saved to a `rom_stuffer_report.txt` file in the backup destination folder.

## Phase 3: SD Card Reconciliation & Fast-Sync
The user wanted the script to seamlessly sync the newly compressed files directly to the target SD Card. 
*   **Parallel vs Sequential Research:** The user initially requested parallelizing the copy to mimic Windows `FastCopy`. However, our research proved that parallelizing I/O to an SD Card (flash memory) causes severe "thrashing" because of the simplistic memory controller. True `FastCopy` behavior on external flash media relies on *sequential bulk I/O*.
*   **The Implementation:** We created a `fast_sd_copy()` function that utilizes `shutil.copyfileobj` with a massive **16MB buffer**. This drastically minimizes OS kernel context switches and maximizes sustained sequential write speeds.
*   **The Workflow:** If the `--sdcard` flag is used (or provided interactively), the script immediately seeks out the old uncompressed `.gba`/`.sfc` on the SD card, deletes it, and drops the new `.zip` in its place using the high-speed 16MB buffered copy.

## Current Status
The project is fully functional, heavily optimized for its specific use-case, and completely documented in `README.md`.
