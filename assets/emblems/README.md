# Theme emblems (drop-in art)

Drop a file named `<theme>.txt` here (e.g. `kirby.txt`, `tetris.txt`) and that
theme's header emblem is replaced by your art automatically — no code changes.
If no file is present for a theme, the built-in fallback emblem is used.

## Format

A `<theme>.txt` file is **Rich console markup** rendering block-art. Each line is
one row of the emblem. The simplest, most reliable way to make one is the
converter, which emits half-block art where every character carries two pixel rows:

```bash
# Convert your OWN rights-cleared pixel art into an emblem file:
python tools/img_to_emblem.py path/to/your_art.png --name kirby --width 22
# -> writes assets/emblems/kirby.txt, used next time you launch that theme
```

Keep the width small (~14–26 characters) so the emblem fits the header panel.

You can also hand-write markup, e.g. `[#ff77bb]██[/]` for two pink pixels; keep every
row the same visible width (no leading/trailing spaces) so it centres cleanly.

## What you own

Only add art you have the right to use. The converter is a generic tool — it does
not ship any character or brand artwork, and neither does this repo.
