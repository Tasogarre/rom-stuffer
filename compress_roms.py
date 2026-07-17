"""Deprecation shim for the former single-file ``compress_roms.py``.

The implementation now lives in the :mod:`rom_stuffer` package. This module remains
so that existing code and tests doing ``import compress_roms`` keep working: it
re-exports the full public API and forwards ``python compress_roms.py`` to the CLI.

Prefer ``python rom_stuffer.py`` (or ``python -m rom_stuffer``) going forward.
"""
from __future__ import annotations

import sys

# Re-export the full public API. Star imports pull every non-underscore name from
# each module (including the stdlib/rich names they import), mirroring the original
# flat module namespace so `compress_roms.<anything>` resolves as before.
from rom_stuffer.metrics import *          # noqa: F401,F403
from rom_stuffer.guards import *           # noqa: F401,F403
from rom_stuffer.state import *            # noqa: F401,F403
from rom_stuffer.tui import *              # noqa: F401,F403
from rom_stuffer.themes import *           # noqa: F401,F403
from rom_stuffer.scan import *             # noqa: F401,F403
from rom_stuffer.compress import *         # noqa: F401,F403
from rom_stuffer.report import *           # noqa: F401,F403
from rom_stuffer.cli import *              # noqa: F401,F403

# Underscore-prefixed module-level names are not carried by `import *`, so re-export
# the ones that were part of the original module's surface explicitly.
from rom_stuffer.metrics import (  # noqa: F401
    FAST_COPY_BUFFER_BYTES, SCAN_FOLDER_SAMPLE, CONSOLE_TABLE_ROW_CAP,
    DRY_RUN_COMPRESSION_ESTIMATE, CARTRIDGE_BIN_MAX_BYTES, SessionMetrics, format_size,
)
from rom_stuffer.guards import _disc_dir_cache, _dir_has_disc_descriptor  # noqa: F401
from rom_stuffer.state import (  # noqa: F401
    STATE_VERSION, STATE_FILENAME, JOURNAL_FILENAME, JOURNAL_FSYNC_INTERVAL,
    _state_paths, ResumeState,
)
from rom_stuffer.themes import (  # noqa: F401
    THEMES, ZELDA_ART, METROID_ART, DEFAULT_THEME, APP_TAGLINE, _active_theme, apply_theme,
)
from rom_stuffer.scan import _build_worklist_interactive  # noqa: F401
from rom_stuffer.cli import _finalise_session, compress_roms, main  # noqa: F401


if __name__ == "__main__":
    print(
        "note: compress_roms.py is deprecated; use 'python rom_stuffer.py' "
        "or 'python -m rom_stuffer'.",
        file=sys.stderr,
    )
    main()
