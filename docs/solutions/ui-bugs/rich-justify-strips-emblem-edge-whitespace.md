---
title: Rich strips edge whitespace when justifying, shearing padded ASCII emblems
module: rom_stuffer/tui
date: 2026-07-18
problem_type: ui_bug
component: tooling
severity: medium
symptoms:
  - "Themed ASCII/pixel-art emblems render sheared or lopsided instead of centered"
  - "A symmetric shape (Triforce, star, block stack) looks tilted, e.g. 'three trees falling over'"
  - "Leading/indent spaces used to position art rows have no visible effect"
root_cause: wrong_api
resolution_type: code_fix
tags:
  - rich
  - terminal-ui
  - ascii-art
  - emblem
  - justify
  - whitespace
related_components:
  - rom_stuffer/themes
---

# Rich strips edge whitespace when justifying, shearing padded ASCII emblems

## Problem

Multi-line ASCII/pixel-art emblems in the themed terminal UI rendered sheared or
lopsided instead of centered, even though each art string was hand-aligned with
leading/trailing spaces. Positioning rows by padding them with spaces does not
survive Rich's justification.

## Symptoms

- A shape that is symmetric in the source string (the `zelda` Triforce, the `kirby`
  star, the `tetris` block stack) displays tilted or offset. In this session the
  Triforce "looked more like 3 falling over trees"; the Kirby and Tetris emblems
  looked "awful."
- Indentation added to art rows to nudge them into place appeared to do nothing.
- The distortion changed depending on which justify mode was in effect, but never
  matched the padded source layout.

## What Didn't Work

- **Hand-padding each row with leading spaces to center the shape.** Rich's `Text`
  justification strips leading whitespace on left-justify and trailing whitespace on
  center-justify, so the very spaces doing the positioning are discarded at render
  time. Each row then re-aligns on its own trimmed content, shearing the shape.
- **Tweaking the padding amounts.** Because the whitespace is removed entirely,
  no amount of edge padding produces stable positioning — the fix is structural, not
  a matter of getting the counts right.

## Solution

Build every emblem row so it contains **only symmetric content — no leading or
trailing padding** — and let a single `Align.center` (with per-line `justify="center"`)
place the whole block. Positioning is delegated to Rich, never encoded as edge
whitespace. The rule is enforced and documented at the render site:

```python
# rom_stuffer/tui.py — print_header()
# Each emblem row holds only symmetric content (no leading/trailing padding), so
# centring every row lands them on one axis. (Rich strips edge whitespace when it
# justifies, so padding-based positioning would shear the shape.)
art = Text.from_markup(theme["art"], justify="center")
...
console.print(Panel(
    Align.center(Group(art, Text(), title, caption, Text(), tagline)),
    box=box.DOUBLE,
    border_style=theme["border"],
    padding=(1, 4),
))
```

See `rom_stuffer/tui.py:38-51`. Emblems can be overridden per theme via
`assets/emblems/<theme>.txt` (loaded by `_load_emblem` at `rom_stuffer/themes.py:24`);
those override files must follow the same symmetric-content rule.

For art that genuinely needs asymmetric placement, express the geometry another way —
e.g. render pixel cells to an SVG on a fixed grid (as the banner and divider
generators do) rather than trying to position characters with spaces inside a
Rich-justified `Text`.

## Why This Works

Rich treats a `Text` as content to be laid out, not as a pre-formatted block: when it
justifies, edge whitespace is meaningless padding to be discarded, so only the
non-space glyphs remain to be aligned. If each row carries a different amount of edge
padding, the rows trim to different widths and center independently, tilting a shape
that was symmetric only because of that padding. Remove the padding and every row is
its own true width, centered on one shared axis — the shape holds.

## Prevention

- **Never position ASCII art with edge whitespace inside a Rich `Text`/justify.**
  Make each row symmetric and center the block with `Align.center`. The comment at
  `rom_stuffer/tui.py:38-40` is the canonical statement of this rule — keep it there.
- **When authoring a new theme emblem** (inline in `THEMES` or as an
  `assets/emblems/<theme>.txt` override), verify the shape is symmetric with no
  leading/trailing spaces on any row, and eyeball it in a real terminal render rather
  than trusting the source string's appearance in an editor.
- **Reach for a grid-based generator (SVG → PNG) when the design is inherently
  asymmetric.** The repo's `tools/img_to_emblem.py` and the banner/divider generators
  place cells on an absolute grid, which sidesteps text-justification entirely.
