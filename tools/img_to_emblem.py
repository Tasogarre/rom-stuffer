#!/usr/bin/env python3
"""Generic pixel-image -> terminal block-art converter for ROM Stuffer theme emblems.

Downscales any image to a small grid and emits Rich-markup half-block art: each
character is the upper-half block "▀" coloured with the top pixel as foreground and
the bottom pixel as background, so one character row carries two pixel rows (keeping
the art roughly square in a 2:1 terminal cell). Every cell is coloured (transparent
pixels are filled with --bg), so rows are equal width with no edge whitespace and the
emblem centres cleanly in the header panel.

Output is a .txt you drop at assets/emblems/<theme>.txt; the theme loads it
automatically (no code changes). Run this ONLY on artwork you have the rights to use.

Examples:
    python tools/img_to_emblem.py my_art.png --name kirby            # -> assets/emblems/kirby.txt
    python tools/img_to_emblem.py my_art.png -w 24 -o out.txt
    python tools/img_to_emblem.py my_art.png                         # print to stdout
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("This tool needs Pillow.  Install it with:  pip install pillow")


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % (rgb[0], rgb[1], rgb[2])


def convert(img: "Image.Image", width: int, bg: str) -> str:
    img = img.convert("RGBA")
    w0, h0 = img.size
    height = max(2, round(width * h0 / w0))
    if height % 2:
        height += 1
    img = img.resize((width, height), Image.NEAREST)
    px = img.load()
    bg_rgb = (int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16))

    def blend(p):
        r, g, b, a = p
        if a == 0:
            return bg_rgb
        if a < 255:
            return tuple(round(c * a / 255 + bc * (255 - a) / 255) for c, bc in zip((r, g, b), bg_rgb))
        return (r, g, b)

    lines = []
    for y in range(0, height, 2):
        cells = []
        for x in range(width):
            top = blend(px[x, y])
            bot = blend(px[x, y + 1])
            cells.append(f"[{_hex(top)} on {_hex(bot)}]▀[/]")
        lines.append("".join(cells))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", help="input pixel image (png/gif/…) you have rights to use")
    ap.add_argument("--name", help="theme name -> write assets/emblems/<name>.txt")
    ap.add_argument("-o", "--out", help="explicit output .txt path")
    ap.add_argument("-w", "--width", type=int, default=20, help="emblem width in characters (default 20; keep it small, ~14-26)")
    ap.add_argument("--bg", default="#14141a", help="fill colour for transparent pixels; match your panel background (default #14141a)")
    args = ap.parse_args()

    art = convert(Image.open(args.image), args.width, args.bg)
    out = args.out or (str(Path("assets/emblems") / f"{args.name}.txt") if args.name else None)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(art + "\n", encoding="utf-8")
        print(f"wrote {out}  ({args.width} chars wide)")
    else:
        print(art)


if __name__ == "__main__":
    main()
