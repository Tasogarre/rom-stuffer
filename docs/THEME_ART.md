# Supplying your own theme art

ROM Stuffer's themes (`kirby`, `tetris`, `zelda`, `metroid`) ship with simple
built-in emblems. You can replace the art for any theme with your own pixel art —
art **you have the right to use** — without touching code. Three things make up a
theme's look; each is drop-in.

## 1. The header emblem (in the TUI)

The emblem is terminal block-art. To use your own:

1. Take a small pixel image (a PNG works well; keep it low-res, e.g. 16–24 px wide).
2. Convert it:
   ```bash
   python tools/img_to_emblem.py your_art.png --name kirby --width 22
   ```
   This writes `assets/emblems/kirby.txt`.
3. Launch that theme — the emblem is loaded automatically:
   ```bash
   python rom-stuffer.py --theme kirby
   ```

The converter maps two pixel rows per character (half-blocks) so the art stays
roughly square, and fills transparent pixels with `--bg` (default a near-black that
blends with the panel). Details and the markup format: `assets/emblems/README.md`.

To revert to the built-in emblem, delete the `.txt`.

## 2. The README hero banner

The banner shown at the top of `README.md` is `assets/banner.png`. Replace that file
with your own banner image (an `assets/banner.svg` source is optional). It renders on
GitHub as-is.

## 3. The theme palette

Colours (panels, text, progress bars, borders) come from each theme's `styles` block
in `rom_stuffer/themes.py`. Tweak the hex values there to match your art. Emblem art
loaded from a `.txt` uses its own literal colours; the palette still styles the rest
of the UI.

## Regenerating the README screenshots

After changing an emblem or palette, refresh the theme screenshots used in the README
so they match (any terminal-to-image method works). The images live at
`assets/screenshot-<theme>.png`.

## Ownership

The repository ships only original, generic emblems. This workflow lets you plug in
artwork you control; please only add art you have the right to use and distribute.
