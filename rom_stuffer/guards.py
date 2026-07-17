from __future__ import annotations

from pathlib import Path

from rom_stuffer.metrics import CARTRIDGE_BIN_MAX_BYTES, format_size


SUPPORTED_EXTENSIONS: set = {
    # Nintendo
    '.nes', '.sfc', '.smc', '.fig', '.swc', '.gb', '.gbc', '.gba', '.fds',
    '.vb', '.vboy', '.min', '.mgw',
    # Sega
    '.bin', '.gen', '.md', '.smd', '.sms', '.gg', '.sg', '.32x',
    # NEC
    '.pce', '.sgx',
    # Atari
    '.a26', '.a52', '.a78', '.j64', '.lnx', '.atr', '.atx', '.xfd', '.xex', '.cas', '.st',
    # Commodore
    '.crt', '.d64', '.t64', '.prg', '.tap', '.d81', '.g64',
    # Amiga
    '.adf', '.dms', '.fdi', '.ipf', '.hdf', '.hdz',
    # Home Computers
    '.msx', '.rom', '.dsk', '.z80', '.tzx', '.cdt',
    # Other Consoles / Handhelds
    '.ws', '.wsc', '.ngp', '.ngc', '.col', '.int', '.vec', '.chf', '.o2',
    # Note: CD-based systems (PSX, Sega CD, Saturn) are EXCLUDED. Emulators stream
    # audio tracks from CD images, and zip extraction overhead causes massive stuttering.
    # Note: N64 and NDS are EXCLUDED due to size and performance overhead on low-end devices.
    # Note: MAME arcade ROMs are already zipped by default, so they are excluded.
}


def describe_error(e: Exception) -> str:
    """Human-readable error text. An OSError's str() embeds repr(filename), which
    doubles backslashes on Windows paths (C:\\\\Games); when the OS gives us a
    strerror, build the message from strerror + the raw filename (single backslash)
    instead. Otherwise fall back to str() (which carries the message and, for
    non-OS/message-style errors, no repr'd path)."""
    if isinstance(e, OSError) and e.strerror:
        return f"{e.strerror}: {e.filename}" if e.filename else e.strerror
    return str(e)


# --------------------------------------------------------------------------- #
# Disc-image / BIOS guard.
#
# '.bin' is dangerously ambiguous: Sega Genesis and Atari 2600 CARTRIDGE dumps use
# it (tiny — Genesis tops out ~8 MB), but so do CD/GD-ROM disc images (PS1, Saturn,
# Sega CD, Dreamcast, PC Engine CD — hundreds of MB, usually beside a .cue/.gdi) and
# BIOS files. Compressing a disc image breaks it, and moving a BIOS out of place
# breaks the emulator. These checks keep genuine cartridge .bin files while refusing
# disc images and BIOS. BIOS folders are off-limits for every extension.
# --------------------------------------------------------------------------- #
DISC_DESCRIPTOR_SUFFIXES: set = {'.cue', '.gdi', '.ccd', '.mds', '.toc', '.m3u'}
# Folders whose contents are NOT cartridge ROMs — optical-disc, UMD, HDD, or arcade
# systems (and their common RetroArch/EmulationStation aliases). A '.bin' in any of
# these is a disc image / data blob, never a Genesis cartridge, so it must never be
# compressed or moved. Matched case-insensitively against each path component.
DISC_SYSTEM_FOLDERS: set = {
    # Sony — all disc / UMD / HDD
    'psx', 'ps1', 'psone', 'playstation', 'ps2', 'playstation2', 'ps3', 'playstation3',
    'psp', 'playstationportable', 'psvita', 'vita',
    # Sega — optical
    'dreamcast', 'dc', 'saturn', 'saturnjp', 'segacd', 'sega-cd', 'megacd', 'mega-cd',
    'mcd', 'naomi', 'atomiswave',
    # NEC and other optical
    'pcecd', 'pce-cd', 'pcenginecd', 'tgcd', 'turbografxcd', 'pcfx', 'neogeocd',
    'neo-geo-cd', 'amigacd32', 'cd32', '3do', 'jaguarcd', 'cdi', 'cdimono1',
    'philipscdi', 'fmtowns', 'fmtownsmarty',
    # Nintendo — disc / HDD-scale
    'gamecube', 'gc', 'ngc', 'wii', 'wiiu', 'switch',
    # Microsoft
    'xbox', 'xbox360', 'xboxone',
    # Arcade (ROM sets ship zipped) and BIOS
    'mame', 'fbneo', 'fba', 'arcade', 'cps1', 'cps2', 'cps3', 'model2', 'model3', 'bios',
}
_disc_dir_cache: dict = {}


def _dir_has_disc_descriptor(directory: Path) -> bool:
    """True if a .cue/.gdi/... descriptor sits in this folder (cached per directory)."""
    key = str(directory)
    if key not in _disc_dir_cache:
        found = False
        try:
            for entry in directory.iterdir():
                if entry.suffix.lower() in DISC_DESCRIPTOR_SUFFIXES:
                    found = True
                    break
        except OSError:
            found = False
        _disc_dir_cache[key] = found
    return _disc_dir_cache[key]


def exclusion_reason(path: Path, ext: str, size: int | None, source: Path | None = None) -> str | None:
    """Return why a supported-extension file must be refused (disc image or BIOS),
    or None if it is a genuine cartridge ROM safe to compress and move.

    Only folder names *inside* the source tree are considered (the system-organisation
    folders), never parent directories above the source, so a source path that happens
    to sit under a folder like 'psp' or 'bios' does not exclude everything.
    """
    relevant = path.parent
    if source is not None:
        try:
            relevant = path.relative_to(source).parent
        except ValueError:
            relevant = path.parent
    parts = {p.lower() for p in relevant.parts}
    # BIOS files must never be moved or compressed, whatever their extension.
    if 'bios' in parts:
        return "BIOS folder — must stay in place"
    # '.bin' is the ambiguous one: disambiguate cartridge dumps from disc images.
    if ext == '.bin':
        disc_folder = parts & DISC_SYSTEM_FOLDERS
        if disc_folder:
            return f"disc-based system folder ('{sorted(disc_folder)[0]}')"
        if _dir_has_disc_descriptor(path.parent):
            return "disc image — a .cue/.gdi descriptor is present in the folder"
        if size is not None and size > CARTRIDGE_BIN_MAX_BYTES:
            return f"disc image — .bin is {format_size(size)}, too large for a cartridge"
    return None
