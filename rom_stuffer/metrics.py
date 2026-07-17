from __future__ import annotations

# Named constants
FAST_COPY_BUFFER_BYTES: int = 4 * 1024 * 1024   # 4 MB: suits typical SD/flash page sizes
SCAN_FOLDER_SAMPLE: int = 8
CONSOLE_TABLE_ROW_CAP: int = 20
DRY_RUN_COMPRESSION_ESTIMATE: float = 0.4        # rough DEFLATE ratio on ROM data

# '.bin' cartridge size ceiling — a genuine Genesis/Atari cartridge dump is tiny,
# so anything larger is treated as a disc image by the guard (see guards.py).
CARTRIDGE_BIN_MAX_BYTES: int = 16 * 1024 * 1024


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
