"""Tests for rom_stuffer.logs.

Covers:
- setup_logging creates the log file and messages land in it via get_logger.
- Idempotency: two setup_logging calls leave exactly one RotatingFileHandler.
- Rotation: a tiny maxBytes (monkeypatched) triggers a .1 backup file.
- get_logger returns a child whose records propagate to the configured handler.
- Non-writable log_dir falls back without raising and returns a valid Path.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

import rom_stuffer.logs as logs_mod
from rom_stuffer.logs import get_logger, setup_logging


# ---------------------------------------------------------------------------
# Autouse fixture: reset the 'rom_stuffer' logger after each test so that
# handler state from one test cannot bleed into the next.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_rom_stuffer_logger():
    yield
    logger = logging.getLogger("rom_stuffer")
    logger.handlers.clear()
    logger.propagate = True  # restore default


# ---------------------------------------------------------------------------
# 1. File creation and message delivery
# ---------------------------------------------------------------------------

class TestSetupLoggingCreatesFile:

    def test_creates_log_file(self, tmp_path):
        log_file = setup_logging(log_dir=tmp_path)
        assert log_file.exists()
        assert log_file.name == "rom_stuffer.log"

    def test_message_via_get_logger_lands_in_file(self, tmp_path):
        log_file = setup_logging(log_dir=tmp_path)
        logger = get_logger("test_delivery")
        logger.info("sentinel_message_xyz")
        # Flush before reading.
        for h in logging.getLogger("rom_stuffer").handlers:
            h.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "sentinel_message_xyz" in content

    def test_returns_path_object(self, tmp_path):
        result = setup_logging(log_dir=tmp_path)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# 2. Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:

    def test_two_calls_leave_one_file_handler(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        setup_logging(log_dir=tmp_path)
        rom_logger = logging.getLogger("rom_stuffer")
        file_handlers = [
            h for h in rom_logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1

    def test_second_call_does_not_add_console_handler_unless_verbose(self, tmp_path):
        setup_logging(log_dir=tmp_path, verbose=False)
        setup_logging(log_dir=tmp_path, verbose=False)
        rom_logger = logging.getLogger("rom_stuffer")
        stream_handlers = [
            h for h in rom_logger.handlers
            if type(h) is logging.StreamHandler
        ]
        assert len(stream_handlers) == 0


# ---------------------------------------------------------------------------
# 3. Rotation
# ---------------------------------------------------------------------------

class TestRotation:

    def test_rotation_creates_backup_file(self, tmp_path, monkeypatch):
        # Patch the module-level constant so setup_logging uses tiny maxBytes.
        monkeypatch.setattr(logs_mod, "_MAX_BYTES", 300)
        log_file = setup_logging(log_dir=tmp_path)
        logger = get_logger("rotate_test")
        # Write enough bytes to overflow the 300-byte limit.
        for _ in range(30):
            logger.info("A" * 20)
        for h in logging.getLogger("rom_stuffer").handlers:
            h.flush()
        # RotatingFileHandler appends ".1" to the base filename.
        backup = log_file.parent / (log_file.name + ".1")
        assert backup.exists(), (
            f"Expected rotation backup at {backup}; "
            f"files present: {list(log_file.parent.iterdir())}"
        )


# ---------------------------------------------------------------------------
# 4. Child logger propagation
# ---------------------------------------------------------------------------

class TestChildLoggerPropagation:

    def test_child_record_lands_in_parent_handler(self, tmp_path):
        log_file = setup_logging(log_dir=tmp_path)
        child = get_logger("propagation_check")
        child.info("child_propagation_sentinel")
        for h in logging.getLogger("rom_stuffer").handlers:
            h.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "child_propagation_sentinel" in content

    def test_get_logger_returns_child_logger(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        child = get_logger("mymodule")
        assert child.name == "rom_stuffer.mymodule"

    def test_child_logger_name_prefixed(self, tmp_path):
        setup_logging(log_dir=tmp_path)
        child = get_logger("compress")
        assert child.name.startswith("rom_stuffer.")


# ---------------------------------------------------------------------------
# 5. Non-writable log_dir fallback
# ---------------------------------------------------------------------------

class TestNonWritableLogDir:

    def test_fallback_does_not_raise(self, tmp_path):
        bad_dir = tmp_path / "unwritable"
        bad_dir.mkdir()
        # Remove write permission.
        bad_dir.chmod(0o444)
        try:
            result = setup_logging(log_dir=bad_dir)
            assert isinstance(result, Path)
        finally:
            # Restore so tmp_path cleanup can delete the directory.
            bad_dir.chmod(0o755)

    def test_fallback_log_file_usable(self, tmp_path):
        bad_dir = tmp_path / "unwritable2"
        bad_dir.mkdir()
        bad_dir.chmod(0o444)
        try:
            log_file = setup_logging(log_dir=bad_dir)
            logger = get_logger("fallback_test")
            logger.info("fallback_sentinel")
            for h in logging.getLogger("rom_stuffer").handlers:
                h.flush()
            content = log_file.read_text(encoding="utf-8")
            assert "fallback_sentinel" in content
        finally:
            bad_dir.chmod(0o755)
