#!/usr/bin/env python3
"""Trustworthy TrueType glyph rasterizer for self-inspection.

Rasterizes through real FreeType (PIL.ImageFont.truetype) — the same fill
rule browsers use. (The old hand-rolled compositor XORed all contours, so
every overlapping stroke knocked a white hole out of the render; every
earlier PNG has those white-gap artifacts.) Usage:

    .venv/bin/python tools/render_glyph.py out.png 宋家安王主天常 --size 420
    .venv/bin/python tools/render_glyph.py out.png 宋 --size 800
"""
from __future__ import annotations

import sys
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from font_config import SOURCE_FONT_PATH

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FONTS = [
    ('src', str(SOURCE_FONT_PATH)),
    ('edit', str(REPO / 'build/font-edited.ttf')),
]


def main():
    args = sys.argv[1:]
    out = args[0]
    text = args[1]
    size = 420
    fonts = DEFAULT_FONTS
    i = 2
    while i < len(args):
        if args[i] == '--size':
            size = int(args[i + 1]); i += 2; continue
        if args[i] == '--fonts':
            fonts = [(a.split(':', 1)[0], a.split(':', 1)[1])
                     for a in args[i + 1].split(';')]
            i += 2; continue
        i += 1
    loaded = [(lab, TTFont(p), ImageFont.truetype(p, size))
              for lab, p in fonts]
    chars = list(text)
    rows, cols = len(loaded), len(chars)
    cell = size + 40
    W = cols * cell
    H = rows * cell + 46
    img = Image.new('RGBA', (W, H), (255, 255, 255, 255))
    dr = ImageDraw.Draw(img)
    pad = 10
    for r, (label, font, pimg) in enumerate(loaded):
        cmap = font.getBestCmap()
        for ci, ch in enumerate(chars):
            if not cmap.get(ord(ch)):
                continue
            l, t, rr, b = pimg.getbbox(ch)
            Wg, Hg = rr - l + 2 * pad, b - t + 2 * pad
            mask = Image.new('L', (Wg, Hg), 0)
            ImageDraw.Draw(mask).text((pad - l, pad - t), ch,
                                      font=pimg, fill=255)
            tile = Image.new('RGBA', (Wg, Hg), (0, 0, 0, 255))
            tile.putalpha(mask)
            img.paste(tile, (ci * cell + (cell - Wg) // 2,
                             46 + r * cell + (cell - Hg) // 2), tile)
            dr.text((ci * cell + 6, 46 + r * cell + 2),
                    f'{label} {ch}', fill=(160, 0, 0, 255))
    img.save(out)
    print('saved', out)


if __name__ == '__main__':
    main()
