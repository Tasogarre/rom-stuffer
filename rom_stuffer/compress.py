from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from rom_stuffer.tui import (
    console, escape,
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn,
)
from rom_stuffer.metrics import (
    SessionMetrics, format_size,
    FAST_COPY_BUFFER_BYTES, DRY_RUN_COMPRESSION_ESTIMATE,
)
from rom_stuffer.guards import describe_error
from rom_stuffer.logs import get_logger
from rom_stuffer.state import ResumeState


def fast_sd_copy(
    source_path: Path,
    dest_path: Path,
    buffer_size: int = FAST_COPY_BUFFER_BYTES,
) -> None:
    """Copy using a large sequential buffer to maximise sustained write speed on flash media.
    Flushes and fsyncs so the data is durable on the card, not just in OS cache."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(source_path, 'rb') as fsrc, open(dest_path, 'wb') as fdst:
        shutil.copyfileobj(fsrc, fdst, length=buffer_size)
        fdst.flush()
        os.fsync(fdst.fileno())


def build_zip_path(file_path: Path, claimed: set[Path]) -> Path:
    """Return the target .zip path for file_path.

    Uses Game.zip in the common case; falls back to Game_gb.zip / Game_gbc.zip
    when the default name is already taken. A name is "taken" if another file in
    this session already claimed it (the `claimed` set, which spans every batch so
    interactive per-extension runs don't collide) OR a file already exists at that
    path on disk (a prior run, or the batch that just wrote it). The claimed set is
    updated in-place.
    """
    default = file_path.with_suffix('.zip')
    if default not in claimed and not default.exists():
        claimed.add(default)
        return default
    stem_ext = f"{file_path.stem}_{file_path.suffix.lstrip('.')}"
    candidate = file_path.parent / f"{stem_ext}.zip"
    counter = 1
    while candidate in claimed or candidate.exists():
        candidate = file_path.parent / f"{stem_ext}_{counter}.zip"
        counter += 1
    claimed.add(candidate)
    return candidate


def compress_batch(
    files_to_process: list[Path],
    source_path: Path,
    dest_path: Path,
    metrics: SessionMetrics,
    sdcard_path: Path | None = None,
    compress_level: int = 6,
    claimed_zips: set[Path] | None = None,
    resume_state: ResumeState | None = None,
) -> None:
    dry_run = metrics.dry_run

    # Zip paths already claimed this session. Passed in by compress_roms so it spans
    # every batch — interactive mode calls this once per extension, and Game.gb's
    # Game.zip must still block Game.gbc in the next batch. Falls back to a local set
    # for standalone calls.
    if claimed_zips is None:
        claimed_zips = set()

    # Single stat pass — one syscall per file, result reused throughout the loop.
    sized: list[tuple[Path, int]] = []
    total_bytes = 0
    for f in files_to_process:
        try:
            sz = f.stat().st_size
        except OSError:
            sz = 0
        sized.append((f, sz))
        total_bytes += sz

    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None, complete_style="accent", finished_style="success"),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(compact=True),
        console=console,
        expand=True,
    ) as progress:
        overall_task = progress.add_task("[accent]Files[/accent]", total=len(sized))
        byte_task = progress.add_task("[info]Data [/info]", total=total_bytes)

        for file_path, original_size in sized:
            safe_name = escape(file_path.name)
            zip_path: Path | None = None

            try:
                rel_path = file_path.relative_to(source_path)
                original_dest = dest_path / rel_path
                zip_path = build_zip_path(file_path, claimed_zips)

                if not dry_run:
                    original_dest.parent.mkdir(parents=True, exist_ok=True)
                    # Write to .tmp then atomically replace — prevents a corrupt .zip
                    # from being left behind if compression fails mid-write.
                    tmp_zip = zip_path.with_name(zip_path.name + '.tmp')
                    try:
                        with zipfile.ZipFile(
                            tmp_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=compress_level
                        ) as zipf:
                            zipf.write(file_path, file_path.name)
                        tmp_zip.replace(zip_path)
                    except Exception:
                        tmp_zip.unlink(missing_ok=True)
                        raise
                    zip_size = zip_path.stat().st_size
                else:
                    zip_size = int(original_size * DRY_RUN_COMPRESSION_ESTIMATE)

                # SD Card Reconciliation.
                # Delete-before-copy is intentional: the card may be nearly full and
                # cannot hold both the original and the new zip at the same time.
                # The authoritative zip already exists in the source directory, so the
                # SD entry is always recoverable from there on a re-run.
                if sdcard_path:
                    progress.update(
                        overall_task,
                        description=f"[warn]Syncing[/warn] {safe_name} → SD",
                    )
                    sd_equivalent_original = sdcard_path / rel_path
                    # Mirror the local zip filename (may be disambiguated).
                    sd_equivalent_zip = sdcard_path / rel_path.parent / zip_path.name

                    if not dry_run:
                        sd_equivalent_original.unlink(missing_ok=True)
                        fast_sd_copy(zip_path, sd_equivalent_zip)
                    metrics.sd_files_synced += 1
                    metrics.sd_bytes_copied += zip_size

                if not dry_run:
                    shutil.move(str(file_path), str(original_dest))

                metrics.original_size_bytes += original_size
                metrics.zip_size_bytes += zip_size
                metrics.success_count += 1
                metrics.total_files += 1
                metrics.affected_folders.add(str(original_dest.parent))

                # Record durable progress so an interruption can resume here.
                if resume_state is not None:
                    resume_state.mark_done(str(rel_path))

            except Exception as e:
                metrics.error_count += 1
                metrics.errors.append({'file': str(file_path.name), 'error': describe_error(e)})
                get_logger("compress").warning("failed %s: %s", file_path, describe_error(e))

            finally:
                # Live running space-saved readout so progress is visible on long runs,
                # not only in the final summary.
                saved = metrics.original_size_bytes - metrics.zip_size_bytes
                pct = (saved / metrics.original_size_bytes * 100) if metrics.original_size_bytes else 0.0
                progress.update(overall_task, description="[accent]Files[/accent]")
                progress.update(
                    byte_task,
                    description=f"[info]Data [/info][muted]· saved[/muted] [success]{format_size(saved)}[/success] [muted]({pct:.0f}%)[/muted]",
                )
                progress.advance(overall_task)
                progress.advance(byte_task, advance=original_size)
