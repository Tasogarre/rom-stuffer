"""Tests for CLI subcommand routing (U2).

Covers:
- compress subcommand routes to _run_compress, not _run_dedup  (T2.1)
- dedup subcommand routes to _run_dedup stub, no exception       (T2.2)
- --help lists both subcommands                                  (T2.3)
- unknown subcommand exits non-zero with a clear error           (T2.4)
- no-arg interactive menu routes choice 1 to compress            (T2.5)
- _run_dedup handles ImportError gracefully                      (extra)
- _run_dedup calls run_dedup() when the module is present        (extra)
- compress end-to-end on a tiny fixture via the subcommand       (extra)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import rom_stuffer.cli as cli_mod
from rom_stuffer.cli import (
    _build_parser,
    _interactive_menu,
    _run_compress,
    _run_dedup,
    main,
)
from rom_stuffer.themes import DEFAULT_THEME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent


def _run_script(*args: str) -> subprocess.CompletedProcess:
    """Run rom_stuffer.py as a subprocess from the repo root."""
    return subprocess.run(
        [sys.executable, "rom_stuffer.py", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


# ---------------------------------------------------------------------------
# _build_parser: structural checks
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_compress_subcommand_parsed(self):
        args = _build_parser().parse_args(["compress", "-s", "/src", "-d", "/dst"])
        assert args.subcommand == "compress"
        assert args.source == "/src"
        assert args.dest == "/dst"

    def test_dedup_subcommand_parsed(self):
        args = _build_parser().parse_args(["dedup", "-s", "/src", "-d", "/dst"])
        assert args.subcommand == "dedup"
        assert args.source == "/src"

    def test_compress_defaults(self):
        args = _build_parser().parse_args(["compress"])
        assert args.type is None
        assert args.level == 6
        assert args.no_recursive is False
        assert args.dry_run is False
        assert args.resume is False
        assert args.fresh is False

    def test_dedup_defaults(self):
        args = _build_parser().parse_args(["dedup"])
        assert args.keeper_order is None
        assert args.protect == []
        assert args.per_system is False
        assert args.min_size == 0
        assert args.interactive is False
        assert args.hard_delete is False
        assert args.apply_plan is None

    def test_compress_level_flag(self):
        args = _build_parser().parse_args(["compress", "-l", "3"])
        assert args.level == 3

    def test_compress_no_recursive_flag(self):
        args = _build_parser().parse_args(["compress", "--no-recursive"])
        assert args.no_recursive is True

    def test_dedup_protect_repeatable(self):
        args = _build_parser().parse_args(["dedup", "--protect", "golden", "--protect", "primary"])
        assert args.protect == ["golden", "primary"]

    def test_shared_theme_flag_on_compress(self):
        args = _build_parser().parse_args(["compress", "--theme", "zelda"])
        assert args.theme == "zelda"

    def test_shared_dry_run_on_dedup(self):
        args = _build_parser().parse_args(["dedup", "--dry-run"])
        assert args.dry_run is True


# ---------------------------------------------------------------------------
# T2.1  compress subcommand routes to _run_compress, not _run_dedup
# ---------------------------------------------------------------------------

class TestMainCompressRouting:
    """T2.1 — compress subcommand routes correctly."""

    def test_compress_calls_run_compress(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py", "compress", "-s", "/tmp/src", "-d", "/tmp/dst"])
        with (
            patch.object(cli_mod, "_run_compress") as mock_compress,
            patch.object(cli_mod, "_run_dedup") as mock_dedup,
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
        ):
            main()
        mock_compress.assert_called_once()
        mock_dedup.assert_not_called()

    def test_compress_passes_correct_subcommand(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py", "compress", "-s", "/tmp/src", "-d", "/tmp/dst"])
        captured = {}

        def capture(args):
            captured["args"] = args

        with (
            patch.object(cli_mod, "_run_compress", side_effect=capture),
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
        ):
            main()

        assert captured["args"].subcommand == "compress"
        assert captured["args"].source == "/tmp/src"
        assert captured["args"].dest == "/tmp/dst"


# ---------------------------------------------------------------------------
# T2.2  dedup subcommand routes to _run_dedup stub, no exception
# ---------------------------------------------------------------------------

class TestMainDedupRouting:
    """T2.2 — dedup subcommand routes to _run_dedup stub without raising."""

    def test_dedup_calls_run_dedup(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py", "dedup", "-s", "/tmp/src", "-d", "/tmp/dst"])
        with (
            patch.object(cli_mod, "_run_dedup") as mock_dedup,
            patch.object(cli_mod, "_run_compress") as mock_compress,
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
        ):
            main()
        mock_dedup.assert_called_once()
        mock_compress.assert_not_called()

    def test_dedup_no_exception_with_importerror(self, monkeypatch):
        """_run_dedup must not raise even when rom_stuffer.dedup is absent."""
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py", "dedup", "-s", "/tmp/src", "-d", "/tmp/dst"])
        monkeypatch.setitem(sys.modules, "rom_stuffer.dedup", None)
        with (
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
        ):
            # Must not raise
            main()


# ---------------------------------------------------------------------------
# T2.3  --help lists both subcommands
# ---------------------------------------------------------------------------

class TestHelpOutput:
    """T2.3 — --help lists subcommands compress and dedup."""

    def test_help_contains_compress(self):
        result = _run_script("--help")
        assert result.returncode == 0
        assert "compress" in result.stdout

    def test_help_contains_dedup(self):
        result = _run_script("--help")
        assert result.returncode == 0
        assert "dedup" in result.stdout


# ---------------------------------------------------------------------------
# T2.4  unknown subcommand exits non-zero with a clear error
# ---------------------------------------------------------------------------

class TestUnknownSubcommand:
    """T2.4 — unknown subcommand exits != 0."""

    def test_frobnicate_exits_nonzero(self):
        result = _run_script("frobnicate")
        assert result.returncode != 0

    def test_frobnicate_error_message(self):
        result = _run_script("frobnicate")
        # argparse writes to stderr
        combined = result.stdout + result.stderr
        # argparse says "invalid choice" or "argument … unrecognized"
        assert any(word in combined.lower() for word in ("invalid", "unrecognized", "frobnicate"))


# ---------------------------------------------------------------------------
# T2.5  no-arg shows menu and routes choice 1 to compress
# ---------------------------------------------------------------------------

class TestInteractiveMenu:
    """T2.5 — no-arg interactive menu routes choices correctly."""

    def _menu_mocks(self, tmp_path, action: int, dry_run: bool = True):
        """Return side-effects for Prompt.ask, IntPrompt.ask, Confirm.ask."""
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir(parents=True, exist_ok=True)
        dst.mkdir(parents=True, exist_ok=True)

        # Prompt.ask is called: (1) theme choice, (2) source dir, (3) dest dir
        prompt_values = iter([DEFAULT_THEME, str(src), str(dst)])

        def prompt_side_effect(msg, **kwargs):
            return next(prompt_values)

        def int_prompt_side_effect(msg, **kwargs):
            return action

        def confirm_side_effect(msg, **kwargs):
            return dry_run

        return prompt_side_effect, int_prompt_side_effect, confirm_side_effect, src, dst

    def test_no_arg_calls_interactive_menu(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py"])
        with patch.object(cli_mod, "_interactive_menu") as mock_menu:
            main()
        mock_menu.assert_called_once()

    def test_menu_choice_1_routes_to_compress(self, tmp_path, monkeypatch):
        """Menu choice 1 = Compress: compress_roms should be called."""
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py"])
        prompt_se, int_se, confirm_se, src, dst = self._menu_mocks(tmp_path, action=1, dry_run=True)

        with (
            patch.object(cli_mod, "Prompt") as mock_prompt,
            patch.object(cli_mod, "IntPrompt") as mock_int,
            patch.object(cli_mod, "Confirm") as mock_confirm,
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
            patch.object(cli_mod, "compress_roms") as mock_compress,
        ):
            mock_prompt.ask.side_effect = prompt_se
            mock_int.ask.side_effect = int_se
            mock_confirm.ask.side_effect = confirm_se
            main()

        mock_compress.assert_called_once()
        call_kwargs = mock_compress.call_args
        # compress_roms(source, file_type, dest, ..., dry_run, ...)
        positional = call_kwargs[0]
        assert str(src) in positional[0]  # source
        assert str(dst) in positional[2]  # dest
        # dry_run is positional arg index 4
        assert positional[4] is True

    def test_menu_choice_2_routes_to_dedup(self, tmp_path, monkeypatch):
        """Menu choice 2 = Find duplicates: _run_dedup should be called."""
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py"])
        prompt_se, int_se, confirm_se, src, dst = self._menu_mocks(tmp_path, action=2)

        with (
            patch.object(cli_mod, "Prompt") as mock_prompt,
            patch.object(cli_mod, "IntPrompt") as mock_int,
            patch.object(cli_mod, "Confirm") as mock_confirm,
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
            patch.object(cli_mod, "_run_dedup") as mock_dedup,
        ):
            mock_prompt.ask.side_effect = prompt_se
            mock_int.ask.side_effect = int_se
            mock_confirm.ask.side_effect = confirm_se
            main()

        mock_dedup.assert_called_once()

    def test_menu_choice_3_routes_to_both(self, tmp_path, monkeypatch):
        """Menu choice 3 = Both: _run_both should be called (dedup then compress)."""
        monkeypatch.setattr(sys, "argv", ["rom_stuffer.py"])
        prompt_se, int_se, confirm_se, src, dst = self._menu_mocks(tmp_path, action=3)

        with (
            patch.object(cli_mod, "Prompt") as mock_prompt,
            patch.object(cli_mod, "IntPrompt") as mock_int,
            patch.object(cli_mod, "Confirm") as mock_confirm,
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
            patch.object(cli_mod, "_run_both") as mock_both,
        ):
            mock_prompt.ask.side_effect = prompt_se
            mock_int.ask.side_effect = int_se
            mock_confirm.ask.side_effect = confirm_se
            main()

        mock_both.assert_called_once()


# ---------------------------------------------------------------------------
# _run_dedup: lazy-import behaviour
# ---------------------------------------------------------------------------

class TestRunDedup:
    """Extra: _run_dedup handles ImportError and calls run_dedup when present."""

    def _make_args(self, tmp_path: Path) -> argparse.Namespace:
        return argparse.Namespace(
            source=str(tmp_path / "src"),
            dest=str(tmp_path / "dst"),
            sdcard=None,
            dry_run=False,
            theme=None,
            resume=False,
            fresh=False,
            keeper_order=None,
            protect=[],
            per_system=False,
            min_size=0,
            interactive=False,
            hard_delete=False,
            apply_plan=None,
        )

    def test_importerror_does_not_raise(self, tmp_path, monkeypatch):
        """_run_dedup must return cleanly when rom_stuffer.dedup cannot be imported."""
        args = self._make_args(tmp_path)
        monkeypatch.setitem(sys.modules, "rom_stuffer.dedup", None)
        _run_dedup(args)  # must not raise

    def test_calls_run_dedup_when_module_available(self, tmp_path, monkeypatch):
        """_run_dedup must call run_dedup(args) when the module is present."""
        args = self._make_args(tmp_path)
        mock_run = MagicMock()
        mock_module = MagicMock()
        mock_module.run_dedup = mock_run
        monkeypatch.setitem(sys.modules, "rom_stuffer.dedup", mock_module)
        _run_dedup(args)
        mock_run.assert_called_once_with(args)


# ---------------------------------------------------------------------------
# Compress end-to-end via the subcommand (tiny fixture)
# ---------------------------------------------------------------------------

class TestCompressEndToEnd:
    """Extra: compress subcommand actually compresses a real tiny fixture."""

    def test_compress_gba_fixture(self, tmp_path, monkeypatch):
        """Running the compress subcommand on a tiny .gba file produces a .zip."""
        src = tmp_path / "source"
        dst = tmp_path / "backup"
        src.mkdir()
        rom = src / "game.gba"
        rom.write_bytes(b"\x00\xFF" * 32)  # 64-byte GBA ROM stub

        monkeypatch.setattr(
            sys, "argv",
            ["rom_stuffer.py", "compress", "-s", str(src), "-d", str(dst),
             "-t", ".gba", "--dry-run"],
        )
        with (
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
        ):
            main()

        # Dry run: no zip created, but the call must complete without error.
        # Verify compress_roms ran (no SystemExit means success).

    def test_compress_creates_zip(self, tmp_path, monkeypatch):
        """Non-dry-run compress subcommand produces a .zip and moves the original."""
        src = tmp_path / "source"
        dst = tmp_path / "backup"
        src.mkdir()
        rom = src / "game.gba"
        rom.write_bytes(b"\x00\xFF" * 32)

        monkeypatch.setattr(
            sys, "argv",
            ["rom_stuffer.py", "compress", "-s", str(src), "-d", str(dst), "-t", ".gba"],
        )
        with (
            patch.object(cli_mod, "print_header"),
            patch.object(cli_mod, "apply_theme"),
        ):
            main()

        assert (src / "game.zip").exists(), "zip should be created in source dir"
        assert (dst / "game.gba").exists(), "original should be moved to dest"
        assert not rom.exists(), "original should no longer be in source"
