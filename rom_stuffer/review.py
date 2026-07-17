"""Interactive review of a dedup plan (U7).

This is the primary interface for the dedup feature: the user browses the
duplicate groups, may change which copy is kept, may skip a group entirely, then
applies. The executor (``rom_stuffer.dedup.apply_plan``) does the actual file
moves/deletes -- this module only presents and edits the plan.

Two modes:

- **Default (non-interactive-per-group):** a paginated summary of every group
  followed by a single ``[a]ccept / [e]dit / [q]uit`` prompt. Editing lets the
  user pick individual groups to change a keeper or skip.
- ``--interactive``: walk every group one at a time with a per-group prompt.
  Intended for small runs only.

All edits mutate the plan in place; the (possibly changed) plan is saved via
``save_plan`` before returning, so it persists for audit / headless re-apply.
Filenames are escaped with ``rich.markup.escape`` so a ROM named ``Game [USA]``
never trips Rich markup parsing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rom_stuffer.metrics import CONSOLE_TABLE_ROW_CAP, format_size
from rom_stuffer.tui import (
    Panel,
    Prompt,
    Table,
    Text,
    box,
    console,
    escape,
)

if TYPE_CHECKING:  # pragma: no cover
    from rom_stuffer.dedup import DedupOptions
    from rom_stuffer.planfile import DedupGroup, DedupPlan


def review_plan(plan: "DedupPlan", options: "DedupOptions") -> "DedupPlan":
    """Present the plan for review; return the (possibly modified) plan.

    Non-interactive (default): show a summary, then ``[a]ccept / [e]dit / [q]uit``.
    Interactive (``options.interactive``): prompt for every group in turn. The
    returned plan is saved before returning. ``[q]uit`` raises ``SystemExit(0)``
    so nothing is applied; ``KeyboardInterrupt`` is treated the same way.
    """
    from rom_stuffer.planfile import save_plan  # noqa: PLC0415 - avoids import cycle

    try:
        _show_summary(plan)
        if not options.interactive:
            while True:
                action = Prompt.ask(
                    "  [accent][a][/accent]ccept all  "
                    "[accent][e][/accent]dit a group  "
                    "[accent][q][/accent]uit",
                    choices=["a", "e", "q"],
                    default="a",
                )
                if action == "a":
                    break
                if action == "q":
                    console.print("[muted]Aborted -- nothing was removed.[/muted]")
                    raise SystemExit(0)
                if action == "e":
                    plan = _edit_group_loop(plan, options)
                    break
        else:
            for i, group in enumerate(plan.groups):
                plan.groups[i] = _prompt_group(
                    group, i + 1, len(plan.groups), options
                )
    except KeyboardInterrupt:
        console.print("\n[muted]Aborted -- nothing was removed.[/muted]")
        raise SystemExit(0)

    save_plan(plan, options.dest)
    return plan


def _show_summary(plan: "DedupPlan") -> None:
    """Print a themed summary panel: group count + total reclaimable bytes."""
    active = [g for g in plan.groups if not g.skipped]
    total_reclaim = sum(g.reclaimed_bytes for g in active)

    grid = Table.grid(padding=(0, 3))
    grid.add_column(justify="right", style="muted")
    grid.add_column(justify="left", style="value")
    grid.add_row("Duplicate groups", str(len(active)))
    if len(plan.groups) != len(active):
        grid.add_row("Skipped groups", str(len(plan.groups) - len(active)))
    grid.add_row("Total reclaimable", format_size(total_reclaim))

    console.print()
    console.print(
        Panel(
            grid,
            title="[accent]Duplicate ROMs found[/accent]",
            box=box.ROUNDED,
            border_style="accent",
            padding=(1, 2),
        )
    )
    _show_all_groups(plan)


def _show_all_groups(plan: "DedupPlan") -> None:
    """Paginated listing of every group's keeper + removals + reclaimed space."""
    total = len(plan.groups)
    for i, group in enumerate(plan.groups, start=1):
        _show_group(group, i, total)


def _show_group(group: "DedupGroup", index: int, total: int) -> None:
    """Display one duplicate group: numbered keeper (KEEP) + removals (REMOVE)."""
    skip_tag = "  [warn](skipped)[/warn]" if group.skipped else ""
    title = (
        f"[accent]Group {index}/{total}[/accent]  "
        f"[muted]{escape(group.sha256[:12])}[/muted]"
        f"  [muted]reclaims {format_size(group.reclaimed_bytes)}[/muted]{skip_tag}"
    )

    table = Table(box=box.SIMPLE_HEAD, show_lines=False, title=title, title_justify="left")
    table.add_column("#", justify="right", style="muted", no_wrap=True)
    table.add_column("Action", no_wrap=True)
    table.add_column("File", overflow="fold")

    table.add_row("1", "[success]KEEP[/success]", f"[path]{escape(str(group.keeper))}[/path]")
    for n, removal in enumerate(group.removals, start=2):
        table.add_row(str(n), "[muted]REMOVE[/muted]", f"[muted]{escape(str(removal))}[/muted]")

    console.print(table)


def _edit_group_loop(plan: "DedupPlan", options: "DedupOptions") -> "DedupPlan":
    """Let the user pick group numbers to edit until they are done.

    A blank entry, ``done``/``d``, or ``a`` (accept the rest) leaves the loop.
    Editing a group routes to ``_prompt_group``; an out-of-range or non-numeric
    entry re-prompts.
    """
    while True:
        total = len(plan.groups)
        raw = Prompt.ask(
            "  Group [accent]number[/accent] to edit "
            "([muted]a[/muted]ccept the rest / [muted]done[/muted])",
            default="a",
        )
        token = raw.strip().lower()
        if token in ("", "a", "d", "done"):
            break
        try:
            n = int(token)
        except ValueError:
            console.print("  [warn]Enter a group number, or 'a' to accept.[/warn]")
            continue
        if not 1 <= n <= total:
            console.print(f"  [warn]No group {n}. Pick 1..{total}.[/warn]")
            continue
        plan.groups[n - 1] = _prompt_group(plan.groups[n - 1], n, total, options)
    return plan


def _prompt_group(
    group: "DedupGroup",
    index: int,
    total: int,
    options: "DedupOptions",
) -> "DedupGroup":
    """Prompt to accept, change the keeper by number, or skip one group.

    The paths are shown numbered (1 = current keeper, 2.. = removals). Choosing a
    number promotes that path to keeper and demotes the rest to removals. ``s``
    skips the group; ``q`` quits (``SystemExit(0)``); ``a``/blank accepts as-is.
    Invalid input re-prompts.
    """
    _show_group(group, index, total)
    all_paths = [group.keeper] + list(group.removals)

    while True:
        raw = Prompt.ask(
            "    [accent][a][/accent]ccept  "
            "[accent]#[/accent] set keeper  "
            "[accent][s][/accent]kip  "
            "[accent][q][/accent]uit",
            default="a",
        )
        token = raw.strip().lower()
        if token in ("", "a", "accept"):
            return group
        if token in ("s", "skip"):
            group.skipped = True
            return group
        if token in ("q", "quit"):
            console.print("[muted]Aborted -- nothing was removed.[/muted]")
            raise SystemExit(0)
        try:
            n = int(token)
        except ValueError:
            console.print("    [warn]Enter a number, or a/s/q.[/warn]")
            continue
        if not 1 <= n <= len(all_paths):
            console.print(f"    [warn]Pick 1..{len(all_paths)}.[/warn]")
            continue
        new_keeper = all_paths[n - 1]
        if new_keeper != group.keeper:
            group.keeper = new_keeper
            group.removals = [p for p in all_paths if p != new_keeper]
        return group
