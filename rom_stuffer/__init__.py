"""ROM Stuffer — compress cartridge ROMs into RetroArch-ready .zip archives.

The former single-file ``compress_roms.py`` now lives here as a package. The CLI
entry point is :func:`rom_stuffer.cli.main`; ``compress_roms.py`` remains as a thin
compatibility shim that re-exports the full public API.
"""
from __future__ import annotations

from rom_stuffer.cli import main

__all__ = ["main"]
