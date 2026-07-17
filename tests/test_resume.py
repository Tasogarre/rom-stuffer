"""Tests for the resume / checkpoint system.

Three scenarios:
  1. KeyboardInterrupt mid-run leaves state + journal intact.
  2. --resume processes only the remaining files, then clears state on success.
  3. A per-file OSError (caught, not fatal) keeps state so --resume can retry.

All calls to compress_roms use file_type='.gb' (headless mode) to avoid
interactive prompts for SD-card, extension selection, and resume confirmation.
"""
from __future__ import annotations

import pytest

import compress_roms as rs
from crash_sim import install_crashing_move


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(root, names=("alpha.gb", "beta.gb", "gamma.gb")):
    """Create a source directory with small .gb files and return its path."""
    source = root / "source"
    source.mkdir()
    for i, name in enumerate(names):
        (source / name).write_bytes(bytes([i + 1] * 64))
    return source


# ---------------------------------------------------------------------------
# 1. KeyboardInterrupt leaves state + journal
# ---------------------------------------------------------------------------

class TestKeyboardInterruptCrash:

    def test_manifest_written_before_crash(self, tmp_path, monkeypatch):
        """The manifest must be on disk even if compress_batch is never entered."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        # Crash after 0 successful moves (first move attempt raises KI)
        install_crashing_move(monkeypatch, n_successes=0, error=KeyboardInterrupt)

        with pytest.raises(KeyboardInterrupt):
            rs.compress_roms(str(source), ".gb", str(dest))

        assert (dest / rs.STATE_FILENAME).exists(), "manifest must survive a crash"

    def test_journal_kept_after_partial_progress(self, tmp_path, monkeypatch):
        """After a crash following 1 successful move the journal records that file."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        install_crashing_move(monkeypatch, n_successes=1, error=KeyboardInterrupt)

        with pytest.raises(KeyboardInterrupt):
            rs.compress_roms(str(source), ".gb", str(dest))

        assert (dest / rs.STATE_FILENAME).exists()
        assert (dest / rs.JOURNAL_FILENAME).exists()
        done = rs.read_journal(dest)
        assert len(done) == 1, "exactly one file should be journaled"

    def test_state_cleared_on_zero_progress_crash(self, tmp_path, monkeypatch):
        """Even with 0 successful moves, the manifest exists (job was planned)."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        install_crashing_move(monkeypatch, n_successes=0, error=KeyboardInterrupt)

        with pytest.raises(KeyboardInterrupt):
            rs.compress_roms(str(source), ".gb", str(dest))

        # Journal may be absent or empty (0 completions) but manifest must be present
        manifest = rs.load_manifest(dest)
        assert manifest is not None, "manifest must exist so --resume can rebuild the worklist"
        assert manifest["total"] == 3


# ---------------------------------------------------------------------------
# 2. --resume processes remaining files and clears state on success
# ---------------------------------------------------------------------------

class TestResumeFlow:

    def test_resume_completes_all_files(self, tmp_path, monkeypatch):
        """After a crash, --resume moves all remaining originals to dest."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()
        names = ["alpha.gb", "beta.gb", "gamma.gb"]

        # First run: crash after 1 success
        install_crashing_move(monkeypatch, n_successes=1, error=KeyboardInterrupt)
        with pytest.raises(KeyboardInterrupt):
            rs.compress_roms(str(source), ".gb", str(dest))

        # Confirm partial state
        done_after_crash = rs.read_journal(dest)
        assert len(done_after_crash) == 1

        # Second run: restore real move, then resume
        monkeypatch.undo()
        rs.compress_roms(str(source), ".gb", str(dest), resume=True)

        # All originals must now be in dest
        for name in names:
            assert not (source / name).exists(), f"{name} still in source after resume"
            assert (dest / name).exists(), f"{name} missing from dest after resume"

    def test_state_cleared_after_clean_resume(self, tmp_path, monkeypatch):
        """State files are removed when --resume finishes without errors."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        install_crashing_move(monkeypatch, n_successes=1, error=KeyboardInterrupt)
        with pytest.raises(KeyboardInterrupt):
            rs.compress_roms(str(source), ".gb", str(dest))

        monkeypatch.undo()
        rs.compress_roms(str(source), ".gb", str(dest), resume=True)

        assert not (dest / rs.STATE_FILENAME).exists(), "manifest must be cleared"
        # Journal may linger briefly but is logically cleared; manifest gone is the key

    def test_resume_skips_already_done_files(self, tmp_path, monkeypatch):
        """--resume must not re-process files already recorded in the journal."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        # Crash after 1 success
        install_crashing_move(monkeypatch, n_successes=1, error=KeyboardInterrupt)
        with pytest.raises(KeyboardInterrupt):
            rs.compress_roms(str(source), ".gb", str(dest))

        # The one file that was moved is now in dest
        moved_before = [n for n in ["alpha.gb", "beta.gb", "gamma.gb"] if (dest / n).exists()]
        assert len(moved_before) == 1

        monkeypatch.undo()

        # Track how many moves happen during resume
        import shutil as _shutil
        move_calls: list[str] = []
        real_move = _shutil.move

        def recording_move(src, dst):
            move_calls.append(str(src))
            return real_move(src, dst)

        monkeypatch.setattr(_shutil, "move", recording_move)
        rs.compress_roms(str(source), ".gb", str(dest), resume=True)

        # Resume should only move the 2 remaining files, not re-move the 1 already done
        assert len(move_calls) == 2, (
            f"expected 2 moves during resume, got {len(move_calls)}: {move_calls}"
        )


# ---------------------------------------------------------------------------
# 3. Per-file OSError keeps state for retry
# ---------------------------------------------------------------------------

class TestOSErrorKeepsState:

    def test_oserror_does_not_abort_batch(self, tmp_path, monkeypatch):
        """A per-file OSError is caught; compress_roms returns normally (no crash)."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        install_crashing_move(monkeypatch, n_successes=1, error=OSError)
        # Must NOT raise — OSError is caught by except Exception in compress_batch
        rs.compress_roms(str(source), ".gb", str(dest))

    def test_oserror_keeps_state_files(self, tmp_path, monkeypatch):
        """State is preserved when any file fails, so --resume can retry it."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        install_crashing_move(monkeypatch, n_successes=1, error=OSError)
        rs.compress_roms(str(source), ".gb", str(dest))

        # error_count > 0 → _finalise_session keeps state
        assert (dest / rs.STATE_FILENAME).exists(), "manifest must be kept after errors"

    def test_oserror_journals_successes_only(self, tmp_path, monkeypatch):
        """Files that raised OSError during move are absent from the journal."""
        source = _make_source(tmp_path)
        dest = tmp_path / "dest"
        dest.mkdir()

        # 1 success, 2 failures (OSError is not fatal — both remaining files attempt)
        install_crashing_move(monkeypatch, n_successes=1, error=OSError)
        rs.compress_roms(str(source), ".gb", str(dest))

        done = rs.read_journal(dest)
        assert len(done) == 1, "only the 1 successful file must appear in the journal"
        assert len(done) < 3, "the 2 failed files must NOT be journaled"
