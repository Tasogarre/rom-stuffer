"""Crash-simulation helpers for testing compress_roms resume behaviour.

Two interfaces are provided:

1. ``CrashAfterN`` — a plain context manager (no pytest needed).
2. ``install_crashing_move(monkeypatch, n, error)`` — pytest monkeypatch helper.

Both patch ``shutil.move`` on the *shutil module object* itself.  compress_roms
does ``import shutil`` then ``shutil.move(...)``, so the attribute lookup at
call time picks up the patch transparently.

``KeyboardInterrupt`` is a BaseException, not Exception, so it bypasses the
``except Exception`` handler in ``compress_batch`` and propagates all the way
out of ``compress_roms``.  The ``finally`` block still closes the journal, so
the state files survive the crash and ``--resume`` can pick up from there.

``OSError`` IS caught by ``except Exception`` in ``compress_batch``, so it is
recorded as a per-file error, processing continues for remaining files, and
``compress_roms`` returns normally — but ``_finalise_session`` keeps the state
files intact when ``error_count > 0``, enabling ``--resume`` to retry.
"""
from __future__ import annotations

import shutil


class CrashAfterN:
    """Patch ``shutil.move`` to raise after *n_successes* successful calls.

    *error* may be an exception class (raised with no constructor arguments)
    or an already-constructed exception instance.

    Example::

        with CrashAfterN(1, KeyboardInterrupt):
            rs.compress_roms(...)   # crashes after 1 successful move
    """

    def __init__(
        self,
        n_successes: int,
        error: type | BaseException = KeyboardInterrupt,
    ) -> None:
        self.n_successes = n_successes
        self.error = error
        self._count = 0
        self._real_move = None

    def __enter__(self) -> "CrashAfterN":
        self._real_move = shutil.move
        shutil.move = self._patched  # type: ignore[assignment]
        return self

    def __exit__(self, *_: object) -> None:
        shutil.move = self._real_move  # type: ignore[assignment]

    def _patched(self, src: object, dst: object) -> object:
        self._count += 1
        if self._count > self.n_successes:
            if isinstance(self.error, type):
                raise self.error()
            raise self.error
        return self._real_move(src, dst)  # type: ignore[operator]

    @property
    def call_count(self) -> int:
        """Total number of move calls attempted (including the failing one)."""
        return self._count


def install_crashing_move(
    monkeypatch,
    n_successes: int,
    error: type | BaseException = KeyboardInterrupt,
) -> list[int]:
    """Register a crashing ``shutil.move`` via pytest *monkeypatch*.

    Returns a mutable ``[call_count]`` list so callers can assert on the
    number of move attempts.  monkeypatch will restore the original on
    test teardown (or when ``monkeypatch.undo()`` is called explicitly).

    Example::

        def test_crash(tmp_path, monkeypatch):
            count = install_crashing_move(monkeypatch, n_successes=1)
            with pytest.raises(KeyboardInterrupt):
                rs.compress_roms(...)
            assert count[0] == 2  # 1 success + 1 failed attempt
    """
    call_count: list[int] = [0]
    real_move = shutil.move

    def patched_move(src: object, dst: object) -> object:
        call_count[0] += 1
        if call_count[0] > n_successes:
            if isinstance(error, type):
                raise error()
            raise error
        return real_move(src, dst)

    monkeypatch.setattr(shutil, "move", patched_move)
    return call_count
