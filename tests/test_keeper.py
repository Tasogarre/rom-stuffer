"""U5 tests: keeper selection heuristic (ordered rules, deterministic)."""
from __future__ import annotations

from pathlib import Path

from rom_stuffer.dedup import (
    DedupOptions,
    select_keeper,
    _has_no_intro_region,
    _is_junk_name,
    _is_junk_folder,
)


def _opts(**kw) -> DedupOptions:
    return DedupOptions(source=Path("/src"), dest=Path("/dst"), **kw)


# --------------------------------------------------------------------------- #
# T5.1 -- compressed preferred over raw
# --------------------------------------------------------------------------- #

def test_zip_preferred_over_raw():
    paths = [Path("/src/game.gba"), Path("/src/game.zip")]
    assert select_keeper(paths, _opts()) == Path("/src/game.zip")


# --------------------------------------------------------------------------- #
# T5.2 -- protected folder always wins
# --------------------------------------------------------------------------- #

def test_protected_folder_wins():
    paths = [Path("/src/game.zip"), Path("/src/golden/game.zip")]
    opts = _opts(protect=["golden"])
    assert select_keeper(paths, opts) == Path("/src/golden/game.zip")


def test_protected_beats_zip_preference():
    # Protected raw file beats an unprotected zip (Rule 0 dominates Rule 5).
    paths = [Path("/src/game.zip"), Path("/src/golden/game.gba")]
    opts = _opts(protect=["golden"])
    assert select_keeper(paths, opts) == Path("/src/golden/game.gba")


# --------------------------------------------------------------------------- #
# T5.3 -- keeper-order overrides default
# --------------------------------------------------------------------------- #

def test_keeper_order_overrides():
    paths = [Path("/src/gba/game.gba"), Path("/src/priority/game.gba")]
    opts = _opts(keeper_order=["priority"])
    assert select_keeper(paths, opts) == Path("/src/priority/game.gba")


# --------------------------------------------------------------------------- #
# T5.4 -- junk folder de-prioritised
# --------------------------------------------------------------------------- #

def test_junk_folder_deprioritised():
    paths = [Path("/src/dupes/game.gba"), Path("/src/gba/game.gba")]
    assert select_keeper(paths, _opts()) == Path("/src/gba/game.gba")


# --------------------------------------------------------------------------- #
# T5.5 -- junk name de-prioritised
# --------------------------------------------------------------------------- #

def test_junk_name_deprioritised():
    paths = [Path("/src/game (1).gba"), Path("/src/game.gba")]
    assert select_keeper(paths, _opts()) == Path("/src/game.gba")


# --------------------------------------------------------------------------- #
# T5.6 -- No-Intro name preferred
# --------------------------------------------------------------------------- #

def test_no_intro_name_preferred():
    paths = [Path("/src/sonic.gba"), Path("/src/Sonic the Hedgehog (USA).gba")]
    assert select_keeper(paths, _opts()) == Path("/src/Sonic the Hedgehog (USA).gba")


# --------------------------------------------------------------------------- #
# T5.7 -- shallower path preferred
# --------------------------------------------------------------------------- #

def test_shallower_path_preferred():
    paths = [Path("/src/a/b/game.gba"), Path("/src/a/game.gba")]
    assert select_keeper(paths, _opts()) == Path("/src/a/game.gba")


# --------------------------------------------------------------------------- #
# T5.8 -- alphabetical tie-break is deterministic
# --------------------------------------------------------------------------- #

def test_alphabetical_tiebreak():
    paths = [Path("/src/z/game.gba"), Path("/src/a/game.gba")]
    result1 = select_keeper(paths, _opts())
    result2 = select_keeper(list(reversed(paths)), _opts())
    assert result1 == Path("/src/a/game.gba")
    assert result2 == Path("/src/a/game.gba")  # order-independent


# --------------------------------------------------------------------------- #
# T5.9 -- deterministic / stable sort at depth 1
# --------------------------------------------------------------------------- #

def test_depth_one_alphabetical_deterministic():
    paths = [Path("/src/mgame.gba"), Path("/src/agame.gba"), Path("/src/zgame.gba")]
    for _ in range(5):
        assert select_keeper(paths, _opts()) == Path("/src/agame.gba")


# --------------------------------------------------------------------------- #
# Rule-ordering precedence: protect beats keeper-order beats junk-folder
# --------------------------------------------------------------------------- #

def test_protect_beats_keeper_order():
    paths = [Path("/src/priority/game.gba"), Path("/src/safe/game.gba")]
    opts = _opts(keeper_order=["priority"], protect=["safe"])
    assert select_keeper(paths, opts) == Path("/src/safe/game.gba")


# --------------------------------------------------------------------------- #
# Predicate helpers
# --------------------------------------------------------------------------- #

def test_has_no_intro_region():
    assert _has_no_intro_region("Sonic (USA)")
    assert _has_no_intro_region("Zelda (Europe) (En,Fr,De)")
    assert _has_no_intro_region("Game (Japan)")
    assert not _has_no_intro_region("Sonic the Hedgehog")
    assert not _has_no_intro_region("Game (Proto)")


def test_is_junk_name():
    assert _is_junk_name("game (1)")
    assert _is_junk_name("game (27)")
    assert _is_junk_name("game copy")
    assert _is_junk_name("game-copy")
    assert _is_junk_name("game_copy")
    assert _is_junk_name("game - copy")
    assert not _is_junk_name("game")
    assert not _is_junk_name("Sonic (USA)")


def test_is_junk_folder():
    src = Path("/src")
    assert _is_junk_folder(Path("/src/dupes/game.gba"), src)
    assert _is_junk_folder(Path("/src/gba/backup/game.gba"), src)
    assert _is_junk_folder(Path("/src/Copies/game.gba"), src)
    assert not _is_junk_folder(Path("/src/gba/game.gba"), src)
