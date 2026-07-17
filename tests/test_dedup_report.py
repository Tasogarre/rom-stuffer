"""U9 tests: the dedup report (console summary + appended report file section)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console
from rich.theme import Theme

import rom_stuffer.report as report
from rom_stuffer.dedup import DedupMetrics
from rom_stuffer.planfile import DedupGroup, DedupPlan
from rom_stuffer.themes import DEFAULT_THEME, THEMES


def _themed_console(buf):
    return Console(file=buf, width=200, force_terminal=False,
                   theme=Theme(THEMES[DEFAULT_THEME]["styles"]))


def _wide_console(monkeypatch):
    """Redirect the report module's console to a wide, themed StringIO console."""
    buf = io.StringIO()
    monkeypatch.setattr(report, "console", _themed_console(buf))
    return buf


def _group(keeper, removals, sha="a" * 64, reclaimed=0, skipped=False):
    return DedupGroup(sha256=sha, keeper=Path(keeper),
                      removals=[Path(r) for r in removals],
                      reclaimed_bytes=reclaimed, skipped=skipped)


def _plan(source, groups):
    return DedupPlan(version=1, source=Path(source),
                     created_at="2026-07-17T00:00:00Z", groups=groups)


# --------------------------------------------------------------------------- #
# T9.1 -- report lists each group's keeper and removals
# --------------------------------------------------------------------------- #

def test_report_lists_keepers_and_removals(tmp_path, monkeypatch):
    _wide_console(monkeypatch)
    plan = _plan("/src", [
        _group("/src/gba/g1.gba", ["/src/gba/dupes/g1.gba", "/src/gba/backup/g1.gba"],
               sha="1" * 64, reclaimed=2048),
        _group("/src/nes/g2.nes", ["/src/nes/dupes/g2.nes", "/src/nes/backup/g2.nes"],
               sha="2" * 64, reclaimed=4096),
    ])
    metrics = DedupMetrics(groups_found=2, files_removed=4, bytes_reclaimed=6144)

    report.generate_dedup_report(plan, metrics, tmp_path)

    text = (tmp_path / "rom_stuffer_report.txt").read_text(encoding="utf-8")
    assert "--- DEDUP ---" in text
    assert "gba/g1.gba" in text
    assert "nes/g2.nes" in text
    assert "gba/dupes/g1.gba" in text
    assert "gba/backup/g1.gba" in text
    assert "nes/dupes/g2.nes" in text
    assert "nes/backup/g2.nes" in text


# --------------------------------------------------------------------------- #
# T9.2 -- dry-run is labelled in both file and console
# --------------------------------------------------------------------------- #

def test_dry_run_labelled(tmp_path, monkeypatch):
    buf = _wide_console(monkeypatch)
    plan = _plan("/src", [_group("/src/a.gba", ["/src/dupes/a.gba"], reclaimed=512)])
    metrics = DedupMetrics(groups_found=1, files_removed=1, bytes_reclaimed=512,
                           dry_run=True)

    report.generate_dedup_report(plan, metrics, tmp_path)

    text = (tmp_path / "rom_stuffer_report.txt").read_text(encoding="utf-8")
    assert "DRY RUN" in text
    assert "DRY RUN" in buf.getvalue()


# --------------------------------------------------------------------------- #
# T9.3 -- paths written via str() -> single backslash, no repr artefacts
# --------------------------------------------------------------------------- #

def test_no_double_backslash(tmp_path, monkeypatch):
    _wide_console(monkeypatch)
    # A backslash is a legal filename byte on POSIX; str(Path) keeps it single,
    # whereas repr()/OSError-str would double it. Assert we used str().
    keeper = "/src/gba\\game.gba"
    removal = "/src/gba\\backup\\game.gba"
    plan = _plan("/src", [_group(keeper, [removal], reclaimed=100)])
    metrics = DedupMetrics(groups_found=1, files_removed=1, bytes_reclaimed=100)

    report.generate_dedup_report(plan, metrics, tmp_path)

    text = (tmp_path / "rom_stuffer_report.txt").read_text(encoding="utf-8")
    assert "\\\\" not in text           # never doubled
    assert "gba\\game.gba" in text      # single backslash preserved
    assert "PosixPath(" not in text     # not repr'd


# --------------------------------------------------------------------------- #
# T9.4 -- totals match the apply metrics
# --------------------------------------------------------------------------- #

def test_totals_match_metrics(tmp_path, monkeypatch):
    _wide_console(monkeypatch)
    plan = _plan("/src", [_group("/src/a.gba", ["/src/dupes/a.gba"], reclaimed=12 * 1024 * 1024)])
    metrics = DedupMetrics(groups_found=1, files_removed=3, bytes_reclaimed=12 * 1024 * 1024)

    report.generate_dedup_report(plan, metrics, tmp_path)

    text = (tmp_path / "rom_stuffer_report.txt").read_text(encoding="utf-8")
    assert "Files Removed: 3" in text
    assert "12.00 MB" in text


# --------------------------------------------------------------------------- #
# T9.5 -- console keeper table caps at CONSOLE_TABLE_ROW_CAP; file has all rows
# --------------------------------------------------------------------------- #

def test_console_caps_file_uncapped(tmp_path, monkeypatch):
    from rom_stuffer.metrics import CONSOLE_TABLE_ROW_CAP

    _wide_console(monkeypatch)
    groups = [
        _group(f"/src/s{i}/game.gba", [f"/src/s{i}/backup/game.gba"],
               sha=f"{i:064d}", reclaimed=1)
        for i in range(25)
    ]
    plan = _plan("/src", groups)
    metrics = DedupMetrics(groups_found=25, files_removed=25, bytes_reclaimed=25)

    report.generate_dedup_report(plan, metrics, tmp_path)

    # File: every one of the 25 removals is present.
    text = (tmp_path / "rom_stuffer_report.txt").read_text(encoding="utf-8")
    for i in range(25):
        assert f"s{i}/backup/game.gba" in text

    # Console table: capped, with an overflow notice.
    rendered = io.StringIO()
    _themed_console(rendered).print(report._format_keeper_table(plan))
    out = rendered.getvalue()
    assert "more" in out
    assert str(25 - CONSOLE_TABLE_ROW_CAP) in out


# --------------------------------------------------------------------------- #
# Skipped groups are excluded from the removed listing
# --------------------------------------------------------------------------- #

def test_skipped_group_not_in_removed_listing(tmp_path, monkeypatch):
    _wide_console(monkeypatch)
    plan = _plan("/src", [
        _group("/src/keep_a.gba", ["/src/dupes/keep_a.gba"], sha="a" * 64,
               reclaimed=10, skipped=True),
        _group("/src/keep_b.gba", ["/src/dupes/keep_b.gba"], sha="b" * 64, reclaimed=20),
    ])
    metrics = DedupMetrics(groups_found=1, files_removed=1, bytes_reclaimed=20)

    report.generate_dedup_report(plan, metrics, tmp_path)
    text = (tmp_path / "rom_stuffer_report.txt").read_text(encoding="utf-8")
    assert "dupes/keep_b.gba" in text
    assert "dupes/keep_a.gba" not in text  # skipped group omitted


# --------------------------------------------------------------------------- #
# Errors are surfaced in the report file
# --------------------------------------------------------------------------- #

def test_errors_in_report(tmp_path, monkeypatch):
    _wide_console(monkeypatch)
    plan = _plan("/src", [_group("/src/a.gba", ["/src/dupes/a.gba"], reclaimed=1)])
    metrics = DedupMetrics(groups_found=1, files_removed=0, bytes_reclaimed=0,
                           errors=[{"file": "a.gba", "error": "Permission denied"}])

    report.generate_dedup_report(plan, metrics, tmp_path)
    text = (tmp_path / "rom_stuffer_report.txt").read_text(encoding="utf-8")
    assert "a.gba: Permission denied" in text
