"""Miscellaneous guard and validation tests.

Covers:
- dest == source exits (SystemExit)
- dest nested inside source exits (SystemExit)
- source nested inside dest exits (SystemExit)
- Unsupported --type (e.g. '.zip') exits (SystemExit)
- describe_error: OSError with Windows-style filename → single-backslash path
- describe_error: message-style OSError (no strerror) → falls back to str()
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import compress_roms as rs


# ---------------------------------------------------------------------------
# Helper: run the CLI as a subprocess and return (returncode, stdout+stderr)
# ---------------------------------------------------------------------------

def _run_cli(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "compress_roms.py", *args],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,  # project root
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# 1. dest == source exits
# ---------------------------------------------------------------------------

class TestDestEqualsSourceGuard:

    def test_raises_system_exit(self, tmp_path):
        """compress_roms() must call sys.exit when dest equals source."""
        source = tmp_path / "roms"
        source.mkdir()
        with pytest.raises(SystemExit):
            rs.compress_roms(str(source), ".gb", str(source))

    def test_cli_nonzero_exit(self, tmp_path):
        """CLI must exit non-zero when dest equals source."""
        source = tmp_path / "roms"
        source.mkdir()
        rc, output = _run_cli("-s", str(source), "-t", ".gb", "-d", str(source))
        assert rc != 0
        assert "error" in output.lower() or "must differ" in output.lower()


# ---------------------------------------------------------------------------
# 2. dest nested inside source exits
# ---------------------------------------------------------------------------

class TestDestNestedInsideSource:

    def test_raises_system_exit(self, tmp_path):
        """Dest that is a sub-directory of source must be rejected."""
        source = tmp_path / "roms"
        source.mkdir()
        nested = source / "backup"
        with pytest.raises(SystemExit):
            rs.compress_roms(str(source), ".gb", str(nested))

    def test_cli_nonzero_exit(self, tmp_path):
        source = tmp_path / "roms"
        source.mkdir()
        nested = source / "backup"
        rc, output = _run_cli("-s", str(source), "-t", ".gb", "-d", str(nested))
        assert rc != 0

    def test_deeply_nested_dest_rejected(self, tmp_path):
        """Even a grandchild dest inside source is rejected."""
        source = tmp_path / "roms"
        source.mkdir()
        deep = source / "a" / "b" / "dest"
        with pytest.raises(SystemExit):
            rs.compress_roms(str(source), ".gb", str(deep))


# ---------------------------------------------------------------------------
# 3. source nested inside dest exits
# ---------------------------------------------------------------------------

class TestSourceNestedInsideDest:

    def test_raises_system_exit(self, tmp_path):
        """Source that is a sub-directory of dest must be rejected."""
        outer = tmp_path / "outer"
        source = outer / "roms"
        outer.mkdir()
        source.mkdir()
        with pytest.raises(SystemExit):
            rs.compress_roms(str(source), ".gb", str(outer))

    def test_cli_nonzero_exit(self, tmp_path):
        outer = tmp_path / "outer"
        source = outer / "roms"
        outer.mkdir()
        source.mkdir()
        rc, _ = _run_cli("-s", str(source), "-t", ".gb", "-d", str(outer))
        assert rc != 0


# ---------------------------------------------------------------------------
# 4. Unsupported --type rejected
# ---------------------------------------------------------------------------

class TestUnsupportedType:

    @pytest.mark.parametrize("bad_ext", [".zip", ".exe", ".mp3", ".iso"])
    def test_unsupported_ext_raises_system_exit(self, tmp_path, bad_ext):
        source = tmp_path / "roms"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        with pytest.raises(SystemExit):
            rs.compress_roms(str(source), bad_ext, str(dest))

    def test_zip_ext_cli_exits(self, tmp_path):
        """-t zip (without dot) also fails because the app normalises the dot."""
        source = tmp_path / "roms"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        rc, output = _run_cli("-s", str(source), "-t", "zip", "-d", str(dest))
        assert rc != 0
        assert "not a recognised" in output.lower() or "error" in output.lower()

    def test_supported_ext_does_not_exit(self, tmp_path):
        """A supported extension (with no files present) must NOT cause sys.exit."""
        source = tmp_path / "roms"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        # .gb is supported; no files → returns normally without SystemExit
        rs.compress_roms(str(source), ".gb", str(dest))


# ---------------------------------------------------------------------------
# 5. describe_error
# ---------------------------------------------------------------------------

class TestDescribeError:

    def test_oserror_with_strerror_and_windows_path(self):
        """OSError with a strerror and a Windows-style filename uses single backslashes."""
        e = OSError(2, "Permission denied")
        e.filename = "C:\\Games\\roms\\Sonic.bin"
        result = rs.describe_error(e)
        # Must contain the raw filename (single backslash) not the repr'd version
        assert result == "Permission denied: C:\\Games\\roms\\Sonic.bin"
        # Doubled backslashes (from repr) must be absent
        assert "\\\\" not in result

    def test_oserror_with_strerror_no_filename(self):
        """OSError with strerror but no filename returns just the strerror."""
        e = OSError(13, "Permission denied")
        # e.filename is None by default when constructed this way
        result = rs.describe_error(e)
        assert result == "Permission denied"

    def test_message_style_oserror(self):
        """OSError constructed with a plain string falls back to str()."""
        e = OSError("custom error message")
        result = rs.describe_error(e)
        assert "custom error message" in result

    def test_non_oserror_exception(self):
        """Non-OSError exceptions fall back to str()."""
        e = ValueError("bad value")
        result = rs.describe_error(e)
        assert "bad value" in result

    def test_oserror_with_posix_path(self, tmp_path):
        """A POSIX-style path in e.filename is preserved verbatim."""
        e = OSError(2, "No such file or directory")
        e.filename = str(tmp_path / "missing.bin")
        result = rs.describe_error(e)
        assert "No such file or directory" in result
        assert str(tmp_path / "missing.bin") in result

    def test_keyboard_interrupt_falls_back_to_str(self):
        """Non-OSError BaseException subclasses also use str()."""
        # describe_error receives an Exception (not BaseException) in practice,
        # but the function signature takes Exception and KeyboardInterrupt is a
        # BaseException — guard against widening.
        e = RuntimeError("interrupted")
        result = rs.describe_error(e)
        assert "interrupted" in result
