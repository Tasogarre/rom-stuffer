from __future__ import annotations

import json
import os
from pathlib import Path


# Resume/checkpoint state (written into the destination directory)
STATE_VERSION: int = 1
STATE_FILENAME: str = ".rom_stuffer_state.json"
JOURNAL_FILENAME: str = ".rom_stuffer_journal.log"
JOURNAL_FSYNC_INTERVAL: int = 200                # fsync the journal every N completions


# --------------------------------------------------------------------------- #
# Resume / checkpoint support
#
# A long run over tens of thousands of files must survive an interruption without
# rescanning the whole tree. Two files in the destination make that possible:
#   * a manifest (JSON) written once, holding the full work-list as paths relative
#     to the source; and
#   * an append-only journal, one relative path per completed file.
# On resume, pending = manifest − journal, so no rescan and no re-prompting.
# --------------------------------------------------------------------------- #

def _state_paths(dest_path: Path) -> tuple[Path, Path]:
    return dest_path / STATE_FILENAME, dest_path / JOURNAL_FILENAME


def load_manifest(dest_path: Path) -> dict | None:
    """Return the saved manifest, or None if absent, unreadable, or incompatible."""
    state_file, _ = _state_paths(dest_path)
    if not state_file.exists():
        return None
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('version') != STATE_VERSION or 'pending' not in data:
        return None
    return data


def read_journal(dest_path: Path) -> set[str]:
    """Return the set of relative paths already recorded as completed."""
    _, journal_file = _state_paths(dest_path)
    done: set[str] = set()
    if not journal_file.exists():
        return done
    try:
        with open(journal_file, 'r', encoding='utf-8') as f:
            for line in f:
                rel = line.rstrip('\n')
                if rel:
                    done.add(rel)
    except OSError:
        pass
    return done


def write_manifest(dest_path: Path, source_path: Path, pending_rel: list[str]) -> None:
    """Atomically write the work-list manifest and reset the journal."""
    state_file, journal_file = _state_paths(dest_path)
    data = {
        'version': STATE_VERSION,
        'source': str(source_path),
        'total': len(pending_rel),
        'pending': pending_rel,
    }
    tmp = state_file.with_name(state_file.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(state_file)
    journal_file.unlink(missing_ok=True)


def clear_state(dest_path: Path) -> None:
    """Remove the manifest and journal (called on clean completion or --fresh)."""
    state_file, journal_file = _state_paths(dest_path)
    state_file.unlink(missing_ok=True)
    journal_file.unlink(missing_ok=True)


class ResumeState:
    """Append-only progress journal. mark_done() is O(1) and flushed per file so a
    process crash loses nothing; fsync runs every JOURNAL_FSYNC_INTERVAL files to
    bound the cost while still guarding against power loss."""

    def __init__(self, dest_path: Path, done: set[str]) -> None:
        _, journal_file = _state_paths(dest_path)
        self.done = done
        self._fh = open(journal_file, 'a', encoding='utf-8')
        self._since_sync = 0

    def is_done(self, rel: str) -> bool:
        return rel in self.done

    def mark_done(self, rel: str) -> None:
        self._fh.write(rel + '\n')
        self._fh.flush()
        self.done.add(rel)
        self._since_sync += 1
        if self._since_sync >= JOURNAL_FSYNC_INTERVAL:
            os.fsync(self._fh.fileno())
            self._since_sync = 0

    def close(self) -> None:
        try:
            os.fsync(self._fh.fileno())
        except OSError:
            pass
        self._fh.close()
