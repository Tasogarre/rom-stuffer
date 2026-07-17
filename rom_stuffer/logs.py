from __future__ import annotations

import logging
import logging.handlers
import tempfile
from pathlib import Path

_LOG_FILE_NAME: str = "rom_stuffer.log"
_DEFAULT_LOG_DIR: Path = Path.home() / ".rom_stuffer" / "logs"
_MAX_BYTES: int = 1_000_000
_BACKUP_COUNT: int = 5
_FORMATTER: logging.Formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


def setup_logging(
    log_dir: Path | None = None,
    *,
    verbose: bool = False,
    level: int = logging.INFO,
) -> Path:
    """Configure the ``rom_stuffer`` logger with a RotatingFileHandler.

    Idempotent: a second call replaces the existing handlers rather than
    stacking new ones.  Returns the path to the active log file.

    If log_dir is not writable the function falls back to a temporary
    directory and still returns a valid path; it never raises.
    """
    if log_dir is None:
        log_dir = _DEFAULT_LOG_DIR

    log_file = _resolve_log_file(log_dir)

    logger = logging.getLogger("rom_stuffer")
    logger.setLevel(level)

    # Clear any existing handlers (idempotency: prevents duplicate handlers
    # if setup_logging is called more than once).
    logger.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(_FORMATTER)
    logger.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(_FORMATTER)
        logger.addHandler(console_handler)

    # Prevent records from bubbling to the root logger, which is typically
    # unconfigured and would produce noise on stderr.
    logger.propagate = False

    return log_file


def _resolve_log_file(log_dir: Path) -> Path:
    """Return the log file path inside log_dir, creating it if necessary.

    Falls back to a fresh temp directory when log_dir cannot be created or
    is not writable; never raises.
    """
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / _LOG_FILE_NAME
        # Verify write access by touching the file before handing it to
        # RotatingFileHandler.
        log_file.touch()
        return log_file
    except OSError:
        fallback = Path(tempfile.mkdtemp(prefix="rom_stuffer_logs_"))
        return fallback / _LOG_FILE_NAME


def get_logger(name: str) -> logging.Logger:
    """Return a child of the ``rom_stuffer`` logger for the given module name.

    Records emitted through the returned logger propagate to the handler
    configured by :func:`setup_logging`, so callers never need to touch
    handler setup directly.

    Typical usage at module level::

        from rom_stuffer.logs import get_logger
        _log = get_logger(__name__)
    """
    return logging.getLogger(f"rom_stuffer.{name}")
