#!/usr/bin/env python3
"""Universal wobble detector: sliding circle-fit residual over outlines.

A clean straight edge or a clean arc (any radius) fits a circle with
~0 residual; wobble at any wavelength shorter than the window span shows
up as radial deviation. Compares ORIGINAL vs EDITED per contour and
reports the worst stations (font-unit coords) for zoomed inspection.
Usage: .venv/bin/python tools/scan_wobble.py '题兔免' [--span 64] [--thr 4]
"""
import math
import sys

sys.path.insert(0, "tools")
from fontTools.ttLib import TTFont  # noqa: E402

import overlay_contours as ov  # noqa: E402


def resample(poly, step=8.0):
    cum = [0.0]
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    total = cum[-1]
    n = max(16, int(total / step))
    out = []
    j = 0
    for k in range(n):
        t = total * k / n
        while j < len(poly) - 1 and cum[j + 1] < t:
            j += 1
        s = cum[j + 1] - cum[j]
        u = (t - cum[j]) / s if s > 1e-9 else 0
        x0, y0 = poly[j]
        x1, y1 = poly[(j + 1) % len(poly)]
        out.append((x0 + u * (x1 - x0), y0 + u * (y1 - y0)))
    return out


def circle_residual(pts):
    """Max radial deviation from the best-fit circle (Kasa algebraic
    fit). Returns (dev, radius)."""
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    mx, my = sx / n, sy / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    syy = sum((p[1] - my) ** 2 for p in pts)
    szx = sum(((p[0] - mx) ** 2 + (p[1] - my) ** 2) * (p[0] - mx)
              for p in pts) / 2
    szy = sum(((p[0] - mx) ** 2 + (p[1] - my) ** 2) * (p[1] - my)
              for p in pts) / 2
    det = sxx * syy - sxy * sxy
    if abs(det) < 1e-9:
        # collinear: deviation from the best-fit line
        if sxx >= syy:
            t = [(p[0], p[1]) for p in pts]
            a = sxy / sxx if sxx > 1e-9 else 0.0
            dev = max(abs((p[1] - my) - a * (p[0] - mx)) for p in t)
        else:
            a = sxy / syy if syy > 1e-9 else 0.0
            dev = max(abs((p[0] - mx) - a * (p[1] - my)) for p in pts)
        return dev, 1e18
    xc = mx + (szy * sxy - szx * syy) / -det
    yc = my + (szx * sxy - szy * sxx) / -det
    r = math.hypot(pts[0][0] - xc, pts[0][1] - yc)
    dev = 0.0
    for x, y in pts:
        dev = max(dev, abs(math.hypot(x - xc, y - yc) - r))
    return dev, r


def scan_ring(pts, span=64.0, step=8.0):
    """Worst window per station: returns list of (dev, radius, x, y)."""
    n = len(pts)
    half = max(2, int(span / 2 / step))
    out = []
    for i in range(n):
        win = [pts[(i + k) % n] for k in range(-half, half + 1)]
        dev, r = circle_residual(win)
        out.append((dev, r, pts[i][0], pts[i][1]))
    return out


def top_flags(sc, thr=4.0, k=3, sep=40.0):
    """Top-k stations above thr, mutually separated by >= sep."""
    cands = sorted([s for s in sc if s[0] > thr], reverse=True)
    picks = []
    for dev, r, x, y in cands:
        if all(math.hypot(x - qx, y - qy) >= sep for _, _, qx, qy in picks):
            picks.append((dev, r, x, y))
        if len(picks) >= k:
            break
    return picks


def main():
    args = sys.argv[1:]
    text = args[0]
    span, thr = 64.0, 4.0
    i = 1
    while i < len(args):
        if args[i] == "--span":
            span = float(args[i + 1])
            i += 2
            continue
        if args[i] == "--thr":
            thr = float(args[i + 1])
            i += 2
            continue
        i += 1
    fo = TTFont(str(ov.SOURCE_FONT_PATH))
    fe = TTFont("build/font-edited.ttf")
    for ch in text:
        ro = [resample(ov.expand(r)) for r in ov.rings(fo, ch)]
        re = [resample(ov.expand(r)) for r in ov.rings(fe, ch)]
        print(f"== {ch}")
        for j, (a, b) in enumerate(zip(ro, re)):
            fa = top_flags(scan_ring(a, span), thr)
            fb = top_flags(scan_ring(b, span), thr)
            wa = max((s[0] for s in scan_ring(a, span)), default=0)
            wb = max((s[0] for s in scan_ring(b, span)), default=0)
            st = f"  c{j} worst {wa:.1f}->{wb:.1f}"
            if fb:
                st += "  EDIT flags: " + "; ".join(
                    f"{d:.1f}u@( {x:.0f},{y:.0f}) r{d2:.0f}"[:24]
                    for d, d2, x, y in fb)
            elif fa:
                st += "  (fixed; orig was " + "; ".join(
                    f"{d:.1f}u" for d, _, _, _ in fa[:2]) + ")"
            else:
                st += "  clean"
            print(st)


if __name__ == "__main__":
    main()
