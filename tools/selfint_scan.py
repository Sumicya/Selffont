#!/usr/bin/env python3
"""Scan a TTF for self-intersecting contours (acceptance test for the
smooth/round ops). Counts contours whose flattened outline crosses
itself (non-adjacent segment intersections)."""
import sys
import edit_font as ef  # noqa: F401
import math
from fontTools.ttLib import TTFont


def _seg_intersect(p1, p2, p3, p4):
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def flatten_contour(pts):
    """pts: [(x, y, on)] -> dense polyline (quadratics subdivided x4)."""
    out = []
    n = len(pts)
    # fontTools simple glyph: points alternate on/off; find the structure
    # by walking: start at first on-curve
    idxs = list(range(n))
    # build segments (on-curve, off-curve, on-curve) or line
    segs = []
    i = 0
    # find first on-curve
    while not pts[i][2]:
        i += 1
    start = i
    cur = (pts[i][0], pts[i][1])
    i = (i + 1) % n
    count = 0
    while i != start:
        on = pts[i][2]
        if on:
            segs.append((cur, (pts[i][0], pts[i][1]), None))
            cur = (pts[i][0], pts[i][1])
        else:
            j = (i + 1) % n
            nxt = (pts[j][0], pts[j][1])
            segs.append((cur, nxt, (pts[i][0], pts[i][1])))
            cur = nxt
            i = j
        i = (i + 1) % n
        count += 1
        if count > n * 2:
            break
    poly = []
    for a, b, c in segs:
        if c is None:
            if not poly or poly[-1] != a:
                poly.append(a)
            poly.append(b)
        else:
            if not poly or poly[-1] != a:
                poly.append(a)
            for k in range(1, 5):
                t = k / 5
                u = 1 - t
                x = u * u * a[0] + 2 * u * t * c[0] + t * t * b[0]
                y = u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]
                poly.append((x, y))
    return poly


def contour_self_intersects(poly):
    """Exact self-intersection count (same semantics as the old O(n^2)
    pass): non-adjacent segment crossings, degenerate (<0.5) segments
    skipped, pairs with touching-but-not-crossing rejected, cap at 4.
    Uses a uniform grid so only pairs with overlapping bboxes are
    tested (every such pair shares a cell, so nothing is missed)."""
    n = len(poly)
    if n < 4:
        return 0
    minx = miny = float("inf")
    maxx = maxy = -float("inf")
    for p in poly:
        if p[0] < minx: minx = p[0]
        if p[0] > maxx: maxx = p[0]
        if p[1] < miny: miny = p[1]
        if p[1] > maxy: maxy = p[1]
    CELL = 32.0
    nx = max(1, int((maxx - minx) / CELL) + 1)
    ny = max(1, int((maxy - miny) / CELL) + 1)
    grid = {}
    seg_cells = []
    for i in range(n):
        p1 = poly[i]
        p2 = poly[(i + 1) % n]
        if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) < 0.5:
            continue
        x0 = max(0, int((min(p1[0], p2[0]) - minx) / CELL))
        x1 = min(nx - 1, int((max(p1[0], p2[0]) - minx) / CELL))
        y0 = max(0, int((min(p1[1], p2[1]) - miny) / CELL))
        y1 = min(ny - 1, int((max(p1[1], p2[1]) - miny) / CELL))
        cells = []
        for cy in range(y0, y1 + 1):
            for cx in range(x0, x1 + 1):
                cells.append((cx, cy))
                grid.setdefault((cx, cy), []).append(i)
        seg_cells.append((i, cells))
    hits = 0
    for i, cells in seg_cells:
        p1 = poly[i]
        p2 = poly[(i + 1) % n]
        seen = set()
        for cell in cells:
            for j in grid[cell]:
                if j <= i or j in seen:
                    continue
                seen.add(j)
                if j == i + 1:
                    continue
                if i == 0 and j == n - 1:
                    continue
                p3 = poly[j]
                p4 = poly[(j + 1) % n]
                # quick bbox reject
                if max(p1[0], p2[0]) + 1 < min(p3[0], p4[0]) or \
                   max(p3[0], p4[0]) + 1 < min(p1[0], p2[0]) or \
                   max(p1[1], p2[1]) + 1 < min(p3[1], p4[1]) or \
                   max(p3[1], p4[1]) + 1 < min(p1[1], p2[1]):
                    continue
                if _seg_intersect(p1, p2, p3, p4):
                    hits += 1
                    if hits > 3:
                        return hits
    return hits


def main(path):
    font = TTFont(path)
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    bad = {}
    total_bad = 0
    for ch in sorted(cmap.keys()):
        gname = cmap[ch]
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        _ = glyph.coordinates  # force lazy expand (same as edit_font)
        spans = list(ef.split_contours(glyph))
        for (s, e) in spans:
            pts = ef.contour_points(glyph, s, e)
            poly = flatten_contour(pts)
            h = contour_self_intersects(poly)
            if h:
                chc = chr(ch) if 32 <= ch < 0xFFFF else "?"
                bad[chc] = bad.get(chc, 0) + h
                total_bad += 1
    print(f"self-intersecting contours: {total_bad}")
    for ch, h in list(bad.items())[:60]:
        print(f"  {ch}: {h}")
    if len(bad) > 60:
        print(f"  ... and {len(bad) - 60} more")


if __name__ == "__main__":
    sys.path.insert(0, "tools")
    main(sys.argv[1] if len(sys.argv) > 1
         else "build/font-edited.ttf")
