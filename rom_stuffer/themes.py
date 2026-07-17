from __future__ import annotations

from rich.theme import Theme

from rom_stuffer.tui import console

# --------------------------------------------------------------------------- #
# Themes. Each is a full NES-era skin: a semantic colour palette (so the whole
# TUI reads as one design) plus a pixel-art emblem and title drawn in that
# palette. Styles are referenced everywhere by semantic name (brand/accent/...),
# so switching the theme re-skins the entire interface.
# --------------------------------------------------------------------------- #

# "zelda" theme emblem — a gold Triforce (half-block pixel art). Three solid
# triangles; the empty middle is an inverted triangle tapering to a point at the
# base, so it reads as one Triforce. (Theme name only — the app is ROM STUFFER.)
ZELDA_ART = (
    "[brand]██[/brand]\n"
    "[brand]████[/brand]\n"
    "[brand]██████[/brand]\n"
    "[brand]██    ██[/brand]\n"
    "[brand]████  ████[/brand]\n"
    "[brand]████████████[/brand]"
)

# "metroid" theme emblem — bio-cyan membrane dome, three red nuclei, orange mandibles.
METROID_ART = (
    "[accent]▁▄▄▄▄▄▁[/accent]\n"
    "[accent]◢█████████◣[/accent]\n"
    "[accent]██[/accent] [danger]◉[/danger] [danger]◉[/danger] [danger]◉[/danger] [accent]██[/accent]\n"
    "[accent]◥█████████◤[/accent]\n"
    "[brand]▜█▙ ▜█▙ ▜█▙[/brand]\n"
    "[brand]▚   ▚   ▚[/brand]"
)

THEMES: dict[str, dict] = {
    "zelda": {
        "styles": {
            "brand": "bold #f8c000",     # gold
            "accent": "#38c020",         # green
            "info": "#80d010",           # bright leaf green
            "success": "bold #38c020",
            "warn": "#f8c000",           # gold caution
            "danger": "bold #d82800",    # red
            "muted": "dim #b08040",      # aged parchment
            "value": "bold #f8c000",
            "path": "#80d010",
        },
        "art": ZELDA_ART,
        "label": "zelda theme",
        "tagline": "It's dangerous to go alone!  Compress your cartridges first.",
        "border": "#f8c000",
    },
    "metroid": {
        "styles": {
            "brand": "bold #f85000",     # armour orange
            "accent": "#38c0f8",         # bio-cyan
            "info": "#40e0a0",           # membrane green
            "success": "bold #40e0a0",
            "warn": "#f8d000",           # visor yellow
            "danger": "bold #f8005c",    # nuclei magenta-red
            "muted": "dim #7088a0",      # cavern steel
            "value": "bold #f8d000",
            "path": "#38c0f8",
        },
        "art": METROID_ART,
        "label": "metroid theme",
        "tagline": "The last cartridge is in captivity.  The galaxy is at peace.",
        "border": "#f85000",
    },
}
DEFAULT_THEME = "zelda"

_active_theme = {"name": DEFAULT_THEME}


def apply_theme(name: str) -> None:
    """Activate a theme by name, re-skinning every semantic style."""
    if name not in THEMES:
        name = DEFAULT_THEME
    _active_theme["name"] = name
    console.push_theme(Theme(THEMES[name]["styles"]))


APP_TAGLINE = "Compress cartridge ROMs into RetroArch-ready .zip archives"

# Ensure semantic styles always resolve, even when compress_roms() is called
# directly (e.g. from tests) without the CLI selecting a theme first.
apply_theme(DEFAULT_THEME)
