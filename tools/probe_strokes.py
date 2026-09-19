#!/usr/bin/env python3
"""Diagnose smooth-strokes coverage per contour for given chars.

Mirrors the production pipeline order (round-terminals first, then the
smooth pass) on an in-memory copy of the ORIGINAL font, and attributes
every contour: REBUILT (with end models) or skipped-by-<guard tag>.
Usage: .venv/bin/python tools/probe_strokes.py '题兔免提北打找指'
"""
import sys

sys.path.insert(0, "tools")
from font_config import SOURCE_FONT_PATH  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

import edit_font as E  # noqa: E402
import smooth_strokes as ss  # noqa: E402

CHARS = list(sys.argv[1]) if len(sys.argv) > 1 else list(
    "题兔免提北打找指王天丸九刀买卖卯员哭")


def diagnose(pts, others, other_polys):
    ring = [(x, y) for (x, y, on) in pts]
    dense = ss.resample_ring(ring, 8.0)
    rs = []
    model = ss.extract_stroke(dense, reason=rs)
    if model is None:
        return "extract:None(" + (rs[0] if rs else "?") + ")"
    sm = ss.smooth_centerline(model["center"], model["widths"])
    if sm is None:
        return "centerline:None(turn-radius)"
    ring2 = ss.rebuild_stroke(model, sm[0], sm[1], others, other_polys)
    if ring2 is None:
        return "rebuild:None(self-intersect)"
    if len(ring2) < 12:
        return "rebuild:len<12"
    ob = ss._bbox(ring)
    nb = ss._bbox(ring2)
    if (nb[0] < ob[0] - 200 or nb[1] < ob[1] - 200 or
            nb[2] > ob[2] + 200 or nb[3] > ob[3] + 200 or
            nb[0] > ob[0] + 200 or nb[1] > ob[1] + 200 or
            nb[2] < ob[2] - 200 or nb[3] < ob[3] - 200):
        return "guard:bbox200"
    if (nb[0] > ob[0] + 40 or nb[1] > ob[1] + 40 or
            nb[2] < ob[2] - 40 or nb[3] < ob[3] - 40):
        return "guard:retreat40"
    for (ox0, oy0, ox1, oy1) in others:
        if abs(ob[1] - oy1) <= 6 and nb[1] > ob[1] + 6:
            return "guard:contact"
        if abs(ob[3] - oy0) <= 6 and nb[3] < ob[3] - 6:
            return "guard:contact"
        if abs(ob[2] - ox0) <= 6 and nb[2] < ob[2] - 6:
            return "guard:contact"
        if abs(ob[0] - ox1) <= 6 and nb[0] > ob[0] + 6:
            return "guard:contact"
    a1, a2 = ss._area(ring), ss._area(ring2)
    if a1 < 1 or not (0.4 <= a2 / a1 <= 2.5):
        return "guard:area"
    ea, eb = model["end_a"][0], model["end_b"][0]
    return f"REBUILT ends={ea}/{eb} med={model['med']:.0f}"


def main():
    font = TTFont(str(SOURCE_FONT_PATH))
    E.op_round_terminals(font, CHARS)  # production order: round first
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    for ch in CHARS:
        gname = cmap.get(ord(ch))
        glyph = glyf[gname]
        spans = E.split_contours(glyph)
        print(f"== {ch} ({glyph.numberOfContours}c "
              f"bbox={glyph.xMin},{glyph.yMin},{glyph.xMax},{glyph.yMax})")
        bboxes = [E.contour_bbox(glyph.coordinates[s:e + 1]) for s, e in spans]
        for j, (s, e) in enumerate(spans):
            pts = E.contour_points(glyph, s, e)
            x0, y0, x1, y1 = bboxes[j]
            others = [b for k, b in enumerate(bboxes) if k != j]
            other_polys = [E.contour_points(glyph, s2, e2)
                           for k2, (s2, e2) in enumerate(spans) if k2 != j]
            area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] -
                           pts[(i + 1) % len(pts)][0] * pts[i][1]
                           for i in range(len(pts)))) / 2
            print(f"  c{j} xy=({x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}) "
                  f"w={x1 - x0:.0f} h={y1 - y0:.0f} n={e - s + 1} "
                  f"area={area:.0f} -> {diagnose(pts, others, other_polys)}")


if __name__ == "__main__":
    main()
