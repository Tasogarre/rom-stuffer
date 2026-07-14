import argparse
import os
import shutil
import zipfile
from pathlib import Path
import sys
from collections import defaultdict

SUPPORTED_EXTENSIONS = {
    # Nintendo
    '.nes', '.sfc', '.smc', '.fig', '.swc', '.gb', '.gbc', '.gba', '.fds', 
    # Sega
    '.bin', '.gen', '.md', '.smd', '.sms', '.gg', 
    # Atari
    '.a26', '.a52', '.a78', '.j64', '.lnx', '.atr', '.atx', '.xfd', '.xex', '.cas', '.st',
    # Amiga
    '.adf', '.dms', '.fdi', '.ipf', '.hdf', '.hdz',
    # Other
    '.ws', '.wsc', '.ngp', '.ngc'
    # Note: N64 removed due to performance overhead on low-end devices.
    # Note: MAME arcade ROMs are already zipped by default, so they are excluded.
}

def compress_batch(files_to_process, source_path, dest_path):
    success_count = 0
    error_count = 0

    for file_path in files_to_process:
        try:
            rel_path = file_path.relative_to(source_path)
            original_dest = dest_path / rel_path
            original_dest.parent.mkdir(parents=True, exist_ok=True)
            zip_path = file_path.with_suffix('.zip')

            print(f"Processing: {rel_path}")
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(file_path, file_path.name)
                
            print(f"  -> Compressed to: {zip_path.name}")

            shutil.move(str(file_path), str(original_dest))
            print(f"  -> Moved original to: {original_dest}")
            
            success_count += 1
        except Exception as e:
            print(f"  -> ERROR processing {file_path.name}: {e}")
            error_count += 1

    return success_count, error_count

def compress_roms(source_dir, file_type, dest_dir):
    source_path = Path(source_dir).resolve()
    dest_path = Path(dest_dir).resolve()

    if not source_path.exists() or not source_path.is_dir():
        print(f"Error: Source directory '{source_path}' does not exist.")
        sys.exit(1)

    print("=========================================================")
    print("WARNING: This script should ONLY be used for cartridge-based")
    print("systems (e.g., NES, SNES, GBA, Genesis).")
    print("DO NOT use this for CD-based games (PS1, Saturn, Sega CD),")
    print("as they do not run well from ZIP files in RetroArch.")
    print("Use CHD format for disc-based games instead.")
    print("=========================================================\n")

    dest_path.mkdir(parents=True, exist_ok=True)

    if file_type:
        if not file_type.startswith('.'):
            file_type = '.' + file_type
        print(f"Scanning for '{file_type}' files recursively in '{source_path}'...")
        files_to_process = list(source_path.rglob(f"*{file_type}"))
        
        if not files_to_process:
            print("No files found matching the specified type.")
            return

        print(f"Found {len(files_to_process)} files to process.\n")
        s, e = compress_batch(files_to_process, source_path, dest_path)
        print("\n=========================================================")
        print("Finished processing!")
        print(f"Successfully processed: {s} files")
        if e > 0:
            print(f"Errors encountered: {e} files")
        print("=========================================================")
        return

    # Interactive mode
    print(f"Scanning for supported cartridge ROMs recursively in '{source_path}'...")
    
    # Gather files
    grouped_files = defaultdict(list)
    for p in source_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            grouped_files[p.suffix.lower()].append(p)

    if not grouped_files:
        print("No supported ROM files found.")
        return

    total_success = 0
    total_error = 0

    for ext, files in sorted(grouped_files.items()):
        print(f"\n--- Extension: {ext} ---")
        folders = set(f.parent for f in files)
        print(f"Found {len(files)} files in {len(folders)} folders.")
        
        # Show sample of folders
        sample_folders = list(folders)[:5]
        for folder in sample_folders:
            print(f"  - {folder}")
        if len(folders) > 5:
            print(f"  - ... and {len(folders) - 5} more")

        ans = input(f"\nDo you want to compress and move these {ext} files? (y/N): ").strip().lower()
        if ans == 'y':
            s, e = compress_batch(files, source_path, dest_path)
            total_success += s
            total_error += e
        else:
            print(f"Skipping {ext} files.")

    print("\n=========================================================")
    print("Finished processing all batches!")
    print(f"Successfully processed: {total_success} files total")
    if total_error > 0:
        print(f"Errors encountered: {total_error} files total")
    print("=========================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Recursively compress ROM files to .zip and move the originals.",
        epilog="WARNING: Only use this script for cartridge-based systems (NES, SNES, GBA, etc). CD-based games should not be zipped."
    )
    
    parser.add_argument("-s", "--source", required=True, help="Source directory to scan for ROMs")
    parser.add_argument("-t", "--type", required=False, help="Optional: specific file extension to target bypassing prompts (e.g., .gba)")
    parser.add_argument("-d", "--dest", required=True, help="Destination directory to move original files to")

    args = parser.parse_args()

    compress_roms(args.source, args.type, args.dest)
