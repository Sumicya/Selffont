#!/usr/bin/env python3
"""Overlay original (red, wide) vs edited (black, thin) glyph OUTLINES.

Coincident edges read as a black hairline centered on red; anywhere the
two separate, the red fringe shows. Usage:
  .venv/bin/python tools/overlay_contours.py out.png '题兔免' --size 500
"""
import sys

sys.path.insert(0, "tools")
from PIL import Image, ImageDraw  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402


def sample_quad(p0, c, p1, steps=10):
    out = []
    for t in range(steps + 1):
        u = t / steps
        a = (1 - u) ** 2
        b = 2 * (1 - u) * u
        d = u * u
        out.append((a * p0[0] + b * c[0] + d * p1[0],
                    a * p0[1] + b * c[1] + d * p1[1]))
    return out


from font_config import SOURCE_FONT_PATH


def expand(pts):

    """[(x, y, on)] closed ring -> dense polyline sampling the quads."""
    n = len(pts)
    on_idx = [i for i in range(n) if pts[i][2]]
    if not on_idx:
        imp = [((pts[i][0] + pts[(i + 1) % n][0]) / 2,
                (pts[i][1] + pts[(i + 1) % n][1]) / 2) for i in range(n)]
        out = [imp[0]]
        for i in range(n):
            q = (pts[(i + 1) % n][0], pts[(i + 1) % n][1])
            out += sample_quad(imp[i], q, imp[(i + 1) % n])[1:]
        return out
    out = [(pts[on_idx[0]][0], pts[on_idx[0]][1])]
    start = on_idx[0]
    i = start
    while True:
        x0, y0, _ = pts[i % n]
        j = i + 1
        off = []
        while not pts[j % n][2]:
            off.append((pts[j % n][0], pts[j % n][1]))
            j += 1
        x1, y1, _ = pts[j % n]
        if not off:
            out.append((x1, y1))
        else:
            prev = (x0, y0)
            for k, (ox, oy) in enumerate(off):
                if k + 1 < len(off):
                    mx = (ox + off[k + 1][0]) / 2
                    my = (oy + off[k + 1][1]) / 2
                    out += sample_quad(prev, (ox, oy), (mx, my))[1:]
                    prev = (mx, my)
                else:
                    out += sample_quad(prev, (ox, oy), (x1, y1))[1:]
        i = j
        if i % n == start:
            break
    return out


def rings(font, ch):
    gname = font.getBestCmap().get(ord(ch))
    if not gname:
        return []
    g = font["glyf"][gname]
    if g.numberOfContours < 0:
        return []
    out = []
    s = 0
    for e in g.endPtsOfContours:
        pts = [(g.coordinates[i][0], g.coordinates[i][1], g.flags[i] & 1)
               for i in range(s, e + 1)]
        out.append(pts)
        s = e + 1
    return out


def main():
    args = sys.argv[1:]
    out = args[0]
    text = args[1]
    size = 500
    fo = str(SOURCE_FONT_PATH)
    fe = "build/font-edited.ttf"
    crop = None
    i = 2
    while i < len(args):
        if args[i] == "--size":
            size = int(args[i + 1])
            i += 2
            continue
        if args[i] == "--crop":
            crop = [float(v) for v in args[i + 1].split(",")]
            i += 2
            continue
        if args[i] == "--orig":
            fo = args[i + 1]
            i += 2
            continue
        if args[i] == "--edit":
            fe = args[i + 1]
            i += 2
            continue
        i += 1
    font_o = TTFont(fo)
    font_e = TTFont(fe)
    chars = list(text)
    cell = size + 40
    img = Image.new("RGB", (len(chars) * cell, cell + 46), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    for ci, ch in enumerate(chars):
        ro = [expand(r) for r in rings(font_o, ch)]
        re = [expand(r) for r in rings(font_e, ch)]
        allx = [p[0] for r in ro + re for p in r]
        ally = [p[1] for r in ro + re for p in r]
        if not allx:
            continue
        if crop:
            x0, y0, x1, y1 = crop
        else:
            x0, x1, y0, y1 = min(allx), max(allx), min(ally), max(ally)
        sc = size / max(x1 - x0, y1 - y0, 1)
        ox = ci * cell + (cell - (x1 - x0) * sc) / 2
        oy = 46 + (cell - (y1 - y0) * sc) / 2

        def mp(p):
            return (ox + (p[0] - x0) * sc, oy + (y1 - p[1]) * sc)

        for r in ro:
            dr.line([mp(p) for p in r] + [mp(r[0])], fill=(255, 60, 60),
                    width=4, joint="curve")
        for r in re:
            dr.line([mp(p) for p in r] + [mp(r[0])], fill=(0, 0, 0),
                    width=2, joint="curve")
        dr.text((ci * cell + 6, 4), ch, fill=(160, 0, 0))
    dr.text((6, cell + 30), "red=orig black=edit", fill=(120, 120, 120))
    img.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
