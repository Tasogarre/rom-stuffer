from __future__ import annotations

import sys

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.markup import escape
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.progress import (
        Progress, SpinnerColumn, TextColumn, BarColumn,
        TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn,
        MofNCompleteColumn,
    )
    from rich.prompt import Confirm, IntPrompt, Prompt
    from rich.theme import Theme
    from rich import print as rprint
except ImportError:
    print("Error: The 'rich' library is required. Please install it using: pip install -r requirements.txt")
    sys.exit(1)


console = Console()


# --------------------------------------------------------------------------- #
# TUI presentation helpers — keep all styling in one place for a cohesive look.
# --------------------------------------------------------------------------- #

def print_header() -> None:
    """Render the themed banner: emblem + the app name (ROM STUFFER) + theme caption."""
    # Imported lazily to avoid a themes<->tui import cycle (themes needs `console`).
    from rom_stuffer.themes import THEMES, _active_theme
    theme = THEMES[_active_theme["name"]]
    # Each emblem row holds only symmetric content (no leading/trailing padding), so
    # centring every row lands them on one axis. (Rich strips edge whitespace when it
    # justifies, so padding-based positioning would shear the shape.)
    art = Text.from_markup(theme["art"], justify="center")
    title = Text("R O M   S T U F F E R", style="brand", justify="center")
    caption = Text(f"‹ {theme['label']} ›", style="muted", justify="center")
    tagline = Text(theme["tagline"], style="muted", justify="center")
    console.print()
    console.print(Panel(
        Align.center(Group(art, Text(), title, caption, Text(), tagline)),
        box=box.DOUBLE,
        border_style=theme["border"],
        padding=(1, 4),
    ))


def print_warning_banner() -> None:
    """The cartridge-only safety warning, styled as a caution panel."""
    console.print(Panel(
        Text.from_markup(
            "[warn]⚠  Cartridge-based systems only.[/warn]\n"
            "Do [danger]not[/danger] use this for CD-based games (PS1, Saturn, Sega CD) — "
            "convert those to [info].chd[/info] instead.\n"
            "N64, NDS and MAME are intentionally excluded too."
        ),
        title="[warn]Please read[/warn]",
        box=box.ROUNDED,
        border_style="warn",
        padding=(0, 2),
    ))


def section(title: str) -> None:
    """A titled horizontal rule that separates the phases of a run."""
    console.print()
    console.rule(f"[accent]{title}[/accent]", style="accent", align="left")
