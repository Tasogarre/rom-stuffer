import argparse
import os
import shutil
import zipfile
from pathlib import Path
import sys

def compress_roms(source_dir, file_type, dest_dir):
    source_path = Path(source_dir).resolve()
    dest_path = Path(dest_dir).resolve()

    if not source_path.exists() or not source_path.is_dir():
        print(f"Error: Source directory '{source_path}' does not exist.")
        sys.exit(1)

    # Ensure file_type starts with a dot
    if not file_type.startswith('.'):
        file_type = '.' + file_type

    print("=========================================================")
    print("WARNING: This script should ONLY be used for cartridge-based")
    print("systems (e.g., NES, SNES, GBA, Genesis).")
    print("DO NOT use this for CD-based games (PS1, Saturn, Sega CD),")
    print("as they do not run well from ZIP files in RetroArch.")
    print("Use CHD format for disc-based games instead.")
    print("=========================================================\n")

    print(f"Scanning for '{file_type}' files recursively in '{source_path}'...")
    
    # Use rglob for recursive scanning
    files_to_process = list(source_path.rglob(f"*{file_type}"))
    
    if not files_to_process:
        print("No files found matching the specified type.")
        return

    print(f"Found {len(files_to_process)} files to process.\n")

    # Create destination directory if it doesn't exist
    dest_path.mkdir(parents=True, exist_ok=True)

    success_count = 0
    error_count = 0

    for file_path in files_to_process:
        try:
            # Calculate relative path to maintain structure
            rel_path = file_path.relative_to(source_path)
            
            # Destination path for the original file
            original_dest = dest_path / rel_path
            
            # Ensure destination subdirectory exists
            original_dest.parent.mkdir(parents=True, exist_ok=True)

            # Zip file path (same directory as original, but with .zip extension)
            zip_path = file_path.with_suffix('.zip')

            print(f"Processing: {rel_path}")
            
            # Compress to zip using normal compression
            # We compress it by storing the base filename inside the zip, without full paths
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(file_path, file_path.name)
                
            print(f"  -> Compressed to: {zip_path.name}")

            # Move the original file
            shutil.move(str(file_path), str(original_dest))
            print(f"  -> Moved original to: {original_dest}")
            
            success_count += 1
            
        except Exception as e:
            print(f"  -> ERROR processing {file_path.name}: {e}")
            error_count += 1

    print("\n=========================================================")
    print("Finished processing!")
    print(f"Successfully processed: {success_count} files")
    if error_count > 0:
        print(f"Errors encountered: {error_count} files")
    print("=========================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Recursively compress ROM files to .zip and move the originals.",
        epilog="WARNING: Only use this script for cartridge-based systems (NES, SNES, GBA, etc). CD-based games should not be zipped."
    )
    
    parser.add_argument("-s", "--source", required=True, help="Source directory to scan for ROMs")
    parser.add_argument("-t", "--type", required=True, help="File extension to look for (e.g., .gba, gbc, .sfc)")
    parser.add_argument("-d", "--dest", required=True, help="Destination directory to move original files to")

    args = parser.parse_args()

    compress_roms(args.source, args.type, args.dest)
