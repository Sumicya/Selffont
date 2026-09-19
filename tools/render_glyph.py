#!/usr/bin/env python3
"""Trustworthy TrueType glyph rasterizer for self-inspection.

Evaluates the quadratic Bezier segments properly (the old ad-hoc renderer
only used on-curve points + midpoints and produced bowties, so every
earlier PNG is untrustworthy). Contours are composited with the even-odd
rule. Usage:

    .venv/bin/python tools/render_glyph.py out.png 宋家安王主天常 --size 420
    .venv/bin/python tools/render_glyph.py out.png 宋 --size 800
"""
from __future__ import annotations

import sys
from pathlib import Path

import PIL.ImageChops as IC
from PIL import Image, ImageDraw
from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FONTS = [
    ('src', str(REPO / 'build/font/WenYuanRoundedSCVF.ttf')),
    ('edit', str(REPO / 'build/font-edited.ttf')),
]


def split(glyph):
    prev = 0
    for e in glyph.endPtsOfContours:
        yield (prev, e + 1)
        prev = e + 1


def glyph_contours(glyph, glyf):
    """Rings as lists of (x, y, onCurve) in font space (y up)."""
    if glyph.numberOfContours < 0:
        c = glyph.getCoordinates(glyf)
        return [( (c[i][0], c[i][1], 1) for i in range(len(c)))]
    coords = glyph.coordinates
    flags = glyph.flags
    for s, e in split(glyph):
        yield [(coords[i][0], coords[i][1], flags[i]) for i in range(s, e)]


def expanded_segments(ring):
    """Expand TrueType quad runs into ('line', p0, p1) / ('quad', p0, c, p1)."""
    n = len(ring)
    on = [i for i in range(n) if ring[i][2]]
    if not on:
        return []
    segs = []
    start = on[0]
    i = start
    while True:
        x0, y0, _ = ring[i % n]
        j = i + 1
        off = []
        while not ring[j % n][2]:
            off.append((ring[j % n][0], ring[j % n][1]))
            j += 1
        x1, y1, _ = ring[j % n]
        if not off:
            segs.append(('line', (x0, y0), (x1, y1)))
        else:
            m = len(off)
            px, py = x0, y0
            for k, (ox, oy) in enumerate(off):
                if k + 1 < m:
                    mx = (ox + off[k + 1][0]) / 2
                    my = (oy + off[k + 1][1]) / 2
                    segs.append(('quad', (px, py), (ox, oy), (mx, my)))
                    px, py = mx, my
                else:
                    segs.append(('quad', (px, py), (ox, oy), (x1, y1)))
                    px, py = x1, y1
        i = j
        if i % n == start:
            break
    return segs


def sample_segs(segs, steps=12):
    pts = []
    for seg in segs:
        if seg[0] == 'line':
            pts.append(seg[2])
        else:
            _, p0, c, p1 = seg
            for t in range(1, steps + 1):
                u = t / steps
                a = (1 - u) ** 2
                b = 2 * (1 - u) * u
                d = u * u
                pts.append((a * p0[0] + b * c[0] + d * p1[0],
                            a * p0[1] + b * c[1] + d * p1[1]))
    return pts


def glyph_mask(font, gname, size, pad=12):
    """Even-odd raster of one glyph; (W, H, mask, x_min, y_min, scale)."""
    glyph = font['glyf'][gname]
    if glyph.numberOfContours <= 0:
        return None
    x_min, y_min = glyph.xMin, glyph.yMin
    x_max, y_max = glyph.xMax, glyph.yMax
    w = max(x_max - x_min, 1)
    h = max(y_max - y_min, 1)
    scale = size / max(w, h)
    Wg = int(w * scale) + 2 * pad
    Hg = int(h * scale) + 2 * pad
    acc = None
    for ring in glyph_contours(glyph, font['glyf']):
        if len(ring) < 3:
            continue
        poly = sample_segs(expanded_segments(ring))
        if len(poly) < 3:
            continue
        px = [pad + (p[0] - x_min) * scale for p in poly]
        py = [Hg - pad - (p[1] - y_min) * scale for p in poly]
        mask = Image.new('L', (Wg, Hg), 0)
        ImageDraw.Draw(mask).polygon(list(zip(px, py)), fill=255)
        if acc is None:
            acc = mask
        else:
            # even-odd: XOR(mask, acc)
            acc = IC.composite(IC.invert(acc), acc, mask)
    return Wg, Hg, acc, x_min, y_min, scale


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
    loaded = [(lab, TTFont(p)) for lab, p in fonts]
    chars = list(text)
    rows, cols = len(loaded), len(chars)
    cell = size + 40
    W = cols * cell
    H = rows * cell + 46
    img = Image.new('RGBA', (W, H), (255, 255, 255, 255))
    dr = ImageDraw.Draw(img)
    for r, (label, font) in enumerate(loaded):
        cmap = font.getBestCmap()
        for ci, ch in enumerate(chars):
            gname = cmap.get(ord(ch))
            if not gname:
                continue
            gm = glyph_mask(font, gname, size)
            if gm is None:
                continue
            Wg, Hg, acc, *_ = gm
            tile = Image.new('RGBA', (Wg, Hg), (0, 0, 0, 255))
            tile.putalpha(acc)
            img.paste(tile, (ci * cell + (cell - Wg) // 2,
                             46 + r * cell + (cell - Hg) // 2), tile)
            dr.text((ci * cell + 6, 46 + r * cell + 2),
                    f'{label} {ch}', fill=(160, 0, 0, 255))
    img.save(out)
    print('saved', out)


if __name__ == '__main__':
    main()
