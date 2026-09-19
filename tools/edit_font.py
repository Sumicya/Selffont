#!/usr/bin/env python3
"""Glyph-level editor for the Selffont primary font (prototype stage).

Operations (per-contour, conservative; a JSON report lists every decision):
  roof-dot-to-stem  Replace the slanted 宀 dot with a vertical rounded capsule
                    (width = 丨 stem width, centered on the 宀 bar).
  round-terminals   Rebuild the end caps of straight bar contours as smooth
                    elliptical arcs (tangent-continuous with the shaft,
                    keeping the original terminal extent). Three end cases
                    are handled per contour:
                      * round cap already  -> exact semicircle (removes the
                        ~5% residual flat this font keeps, e.g. 4/1000 on 一)
                      * flat cut, terminal -> new semicircle cap (the stroke
                        grows by half its width at that end)
                      * flat cut, hidden   -> left flat (the end is covered by
                        a crossing stroke, e.g. 王's stem between the bars;
                        capping it would poke through the other stroke)

With --all the ops run over the whole GB2312 charset instead of the built-in
demo list. Edited glyphs lose their hinting programs and gvar deltas (they keep
one shape across all weights; logged per glyph). Untouched glyphs are not
modified at all.
"""
import argparse
import json
import math
from pathlib import Path

import fontTools.ttLib.tables.ttProgram as ttProgram
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

from font_config import SOURCE_FONT_PATH
import smooth_strokes

ROOT = Path(__file__).resolve().parents[1]

TOL = 3.0  # font units: "on the same line" tolerance for hand-drawn outlines


# ---------------------------------------------------------------- geometry --

def _tangent_ctrl(pa, da, pb, db):
    """Control point of the quadratic Bezier leaving `pa` along tangent `da`
    and arriving at `pb` along tangent `db`: the intersection of the two
    tangent lines (fall back to the midpoint for parallel tangents)."""
    det = da[0] * db[1] - da[1] * db[0]
    if abs(det) < 1e-9:
        return ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    t = ((pb[0] - pa[0]) * db[1] - (pb[1] - pa[1]) * db[0]) / det
    return (pa[0] + t * da[0], pa[1] + t * da[1])


def _ellipse_arc(cx, cy, rx, ry, a0, a1, n=4):
    """Quadratic-chain approximation of an elliptical arc
    (x = cx + rx·cosθ, y = cy + ry·sinθ, y-up coordinates) from angle a0 to
    a1 (degrees, either direction), in n equal parameter steps.

    Control points are tangent intersections, so the chain is
    TANGENT-CONTINUOUS with whatever it joins at both ends (straight shaft
    edges): no kink where a cap meets the stroke body. With rx == ry this is
    a circular arc; with rx < ry (or vice versa) the flatter cap that keeps
    the original terminal extent while staying smooth. One quadratic per
    45° deviates < 0.3% — below font-unit rounding.
    """
    step = (a1 - a0) / n
    sgn = 1 if step >= 0 else -1

    def point_dir(a):
        t = math.radians(a)
        p = (cx + rx * math.cos(t), cy + ry * math.sin(t))
        d = (sgn * -rx * math.sin(t), sgn * ry * math.cos(t))
        return p, d

    seq = [point_dir(a0 + step * i) for i in range(n + 1)]
    out = [(seq[0][0][0], seq[0][0][1], 1)]
    for i in range(n):
        (pa, da), (pb, db) = seq[i], seq[i + 1]
        c = _tangent_ctrl(pa, da, pb, db)
        out.append((c[0], c[1], 0))
        out.append((pb[0], pb[1], 1))
    return out


def capsule(cx, cy, hw, hh):
    """Vertical stadium (short vertical with rounded ends), clockwise in y-up."""
    yt = cy + hh - hw
    yb = cy - hh + hw
    top = _ellipse_arc(cx, yt, hw, hw, 180, 0)    # over the top, left -> right
    bottom = _ellipse_arc(cx, yb, hw, hw, 0, -180)  # under, right -> left
    return [(cx - hw, yt, 1)] + top[1:] + [(cx + hw, yb, 1)] + bottom[1:]


def hbar_stadium(xl, xr, top_y, bot_y):
    """Horizontal stadium, clockwise in y-up (exact semicircle caps)."""
    return build_hbar(top_y, bot_y, xl, xr,
                      True, True, (top_y - bot_y) / 2, (top_y - bot_y) / 2)


def vbar_stadium(xl, xr, top_y, bot_y):
    """Vertical stadium, clockwise in y-up (exact semicircle caps)."""
    return build_vbar(xl, xr, top_y, bot_y,
                      True, True, (xr - xl) / 2, (xr - xl) / 2)


def _vbar_cap_left_to_right(left, right, corner_y, bulge):
    """Top cap of a vertical bar: (left, corner_y) -> (right, corner_y), apex
    at corner_y + bulge. Ellipse with semi-axes (w/2, bulge): bulge == w/2 is
    a full semicircle, smaller bulge is the flatter cap that keeps the
    original terminal height. Tangent-continuous with the shaft side edges."""
    w = right - left
    xc = (left + right) / 2
    return _ellipse_arc(xc, corner_y, w / 2, bulge, 180, 0)


def _vbar_cap_right_to_left(left, right, corner_y, bulge):
    """Bottom cap of a vertical bar, traversed right -> left, bulging DOWN."""
    w = right - left
    xc = (left + right) / 2
    return _ellipse_arc(xc, corner_y, w / 2, bulge, 0, -180)


def _hbar_cap_top_to_bottom(top_y, bot_y, corner_x, bulge):
    """Right cap of a horizontal bar: (corner_x, top_y) -> (corner_x, bot_y),
    apex at corner_x + bulge (ellipse semi-axes (bulge, h/2))."""
    h = top_y - bot_y
    yc = (top_y + bot_y) / 2
    return _ellipse_arc(corner_x, yc, bulge, h / 2, 90, -90)


def _hbar_cap_bottom_to_top(top_y, bot_y, corner_x, bulge):
    """Left cap of a horizontal bar: (corner_x, bot_y) -> (corner_x, top_y),
    apex at corner_x - bulge."""
    h = top_y - bot_y
    yc = (top_y + bot_y) / 2
    return _ellipse_arc(corner_x, yc, bulge, h / 2, -90, -270)


def build_vbar(left, right, top_y, bot_y, cap_top, cap_bot, bulge_top, bulge_bot):
    """Rebuild a vertical bar contour. Cap ends use arcs with the given bulge
    (preserving the original terminal extent); uncapped ends stay flat. The
    ring: top edge (left->right), right edge down, bottom edge (right->left),
    left edge up (closing)."""
    pts = []
    if cap_top:
        pts += _vbar_cap_left_to_right(left, right, top_y, bulge_top)
    else:
        pts += [(left, top_y, 1), (right, top_y, 1)]
    # (right, top_y) -> (right, bot_y): right edge; keep the corner explicit
    pts += [(right, bot_y, 1)]
    if cap_bot:
        pts += _vbar_cap_right_to_left(left, right, bot_y, bulge_bot)[1:]
    else:
        pts += [(left, bot_y, 1)]
    return pts


def build_hbar(top_y, bot_y, left_x, right_x, cap_right, cap_left,
               bulge_right, bulge_left):
    """Rebuild a horizontal bar contour (same orientation as hbar_stadium).
    The ring: top edge, right edge down, bottom edge (right->left), left edge
    up."""
    pts = []
    if cap_right:
        pts += _hbar_cap_top_to_bottom(top_y, bot_y, right_x, bulge_right)
    else:
        pts += [(right_x, top_y, 1), (right_x, bot_y, 1)]
    # (right_x, bot_y) -> (left_x, bot_y): bottom edge; keep the corner
    pts += [(left_x, bot_y, 1)]
    if cap_left:
        pts += _hbar_cap_bottom_to_top(top_y, bot_y, left_x, bulge_left)[1:]
    else:
        pts += [(left_x, top_y, 1)]
    return pts


def contour_bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def expand_quad(pts):
    """TrueType quadratic expansion: returns all on-curve vertices of the
    rendered contour, including the implicit midpoints of consecutive
    off-curve runs. Hand-drawn outlines in this font place bar corners as
    implicit points, so corner detection must work on this list."""
    n = len(pts)
    out = []
    for i in range(n):
        x, y, on = pts[i]
        if on:
            out.append((x, y))
        else:
            nx, ny, n_on = pts[(i + 1) % n]
            if not n_on:
                out.append(((x + nx) / 2, (y + ny) / 2))
    return out


def split_contours(glyph):
    endpts = glyph.endPtsOfContours
    spans = []
    start = 0
    for end in endpts:
        spans.append((start, end))
        start = end + 1
    return spans


def contour_points(glyph, s, e):
    # NOTE: flags must be indexed with the GLOBAL point index (s + k);
    # a local index silently corrupts every contour after the first
    # (off-curve flags from an unrelated contour get spliced in, which
    # turns clean 4-point bar rectangles into tapered needles).
    return [(x, y, bool(glyph.flags[s + k] & 1))
            for k, (x, y) in enumerate(glyph.coordinates[s:e + 1])]


def set_glyph_contours(glyph, new_contours):
    coords = []
    flags = []
    endpts = []
    for contour in new_contours:
        for (x, y, on) in contour:
            coords.append((int(round(x)), int(round(y))))
            flags.append(1 if on else 0)
        endpts.append(len(coords) - 1)
    glyph.coordinates = GlyphCoordinates(coords)
    glyph.flags = bytearray(flags)
    glyph.endPtsOfContours = endpts
    glyph.numberOfContours = len(new_contours)
    # Reset the hinting program to empty: the old bytecode references the old
    # point indices, and simple glyphs always need a .program at compile time.
    glyph.program = ttProgram.Program()
    glyph.program.fromBytecode(b"")
    glyph._coords = None


# ------------------------------------------------------- bar classification --

def _bar_kind(pts):
    """'h' / 'v' for a straight long bar, None otherwise (conservative)."""
    x0, y0, x1, y1 = contour_bbox(pts)
    w, h = x1 - x0, y1 - y0
    if min(w, h) < 10:
        return None
    if w >= 3 * h:
        return "h"
    if h >= 3 * w:
        return "v"
    return None


def _analyze_bar(pts, kind):
    """Analyze a bar contour. Returns a dict describing both ends, or None if
    the contour is not a clean bar (in which case it must be left untouched).

    vbar: {left, right, bot, top, r, ends: {'top': {...}, 'bot': {...}}}
    each end:
      style 'round': corner/corner_l/corner_r = y of the line where the cap
        meets the shaft (per side + average), bulge = how far the original cap
        sticks out beyond the corner line, cut = the contour's extreme.
      style 'cut':   cut = y of the flat end edge, corner = corner_l =
        corner_r = the side corner line.
    hbar is symmetric in x.
    """
    x0, y0, x1, y1 = contour_bbox(pts)
    # Straight bars fill (almost) their bbox; a curved thin stroke (sweep,
    # hook tail) does not. Cheap shoelace guard over the raw point ring.
    area = 0.0
    for i in range(len(pts)):
        ax, ay, _ = pts[i]
        bx, by, _ = pts[(i + 1) % len(pts)]
        area += ax * by - bx * ay
    if abs(area) / 2 < 0.75 * (x1 - x0) * (y1 - y0):
        return None
    if kind == "v":
        left, right, bot, top = x0, x1, y0, y1
        w = right - left
        r = w / 2
        exp = expand_quad(pts)
        left_pts = [p for p in exp if p[0] <= left + TOL]
        right_pts = [p for p in exp if p[0] >= right - TOL]

        def analyze():
            if len(left_pts) < 2 or len(right_pts) < 2:
                return None
            l_ys = sorted(p[1] for p in left_pts)
            r_ys = sorted(p[1] for p in right_pts)
            top_l, top_r = l_ys[-1], r_ys[-1]
            bot_l, bot_r = l_ys[0], r_ys[0]
            if max(top_l, top_r) - min(bot_l, bot_r) < r:  # degenerate
                return None
            ends = {}
            for name, extreme, cl, cr in (
                    ("top", top, top_l, top_r),
                    ("bot", bot, bot_l, bot_r)):
                corner = (cl + cr) / 2
                edge_pts = [p for p in pts if p[2]
                            and (p[1] >= extreme - TOL if name == "top"
                                 else p[1] <= extreme + TOL)]
                flat = (max(p[0] for p in edge_pts)
                        - min(p[0] for p in edge_pts) if edge_pts else 0)
                if flat >= 0.7 * w:
                    ends[name] = {"style": "cut", "corner": corner,
                                  "corner_l": cl, "corner_r": cr,
                                  "cut": (sum(p[1] for p in edge_pts) /
                                          len(edge_pts) if edge_pts else corner)}
                else:
                    bulge = (extreme - corner) if name == "top" else (corner - extreme)
                    if not (0.35 * r <= bulge <= 1.6 * r):
                        return None
                    ends[name] = {"style": "round", "corner": corner,
                                  "corner_l": cl, "corner_r": cr,
                                  "cut": extreme, "bulge": bulge}
            return {"left": left, "right": right, "bot": bot, "top": top,
                    "r": r, "ends": ends}
        return analyze()

    # horizontal bar
    left, right, bot, top = x0, x1, y0, y1
    h = top - bot
    r = h / 2
    exp = expand_quad(pts)
    top_pts = [p for p in exp if p[1] >= top - TOL]
    bot_pts = [p for p in exp if p[1] <= bot + TOL]

    def analyze():
        if len(top_pts) < 2 or len(bot_pts) < 2:
            return None
        t_xs = sorted(p[0] for p in top_pts)
        b_xs = sorted(p[0] for p in bot_pts)
        right_t, right_b = t_xs[-1], b_xs[-1]
        left_t, left_b = t_xs[0], b_xs[0]
        if max(right_t, right_b) - min(left_t, left_b) < r:
            return None
        ends = {}
        for name, extreme, ct, cb in (
                ("right", right, right_t, right_b),
                ("left", left, left_t, left_b)):
            corner = (ct + cb) / 2
            edge_pts = [p for p in pts if p[2]
                        and (p[0] >= extreme - TOL if name == "right"
                             else p[0] <= extreme + TOL)]
            flat = (max(p[1] for p in edge_pts)
                    - min(p[1] for p in edge_pts) if edge_pts else 0)
            if flat >= 0.7 * (top - bot):
                ends[name] = {"style": "cut", "corner": corner,
                              "corner_l": ct, "corner_r": cb,
                              "cut": (sum(p[0] for p in edge_pts) /
                                      len(edge_pts) if edge_pts else corner)}
            else:
                bulge = (extreme - corner) if name == "right" else (corner - extreme)
                if not (0.35 * r <= bulge <= 1.6 * r):
                    return None
                ends[name] = {"style": "round", "corner": corner,
                              "corner_l": ct, "corner_r": cb,
                              "cut": extreme, "bulge": bulge}
        return {"left": left, "right": right, "bot": bot, "top": top, "r": r,
                "ends": ends}
    return analyze()


def _end_is_hidden(info, end_name, other_bboxes):
    """True if the flat end edge is covered by another contour (so capping it
    would poke through the crossing stroke)."""
    end = info["ends"][end_name]
    if end["style"] != "cut":
        return False
    for (ox0, oy0, ox1, oy1) in other_bboxes:
        if end_name in ("top", "bot"):
            beyond = oy1 > end["cut"] + 1 and oy0 < end["cut"] + 1
            overlap = ox0 < info["right"] and ox1 > info["left"]
        else:
            beyond = ox1 > end["cut"] + 1 and ox0 < end["cut"] + 1
            overlap = oy0 < info["top"] and oy1 > info["bot"]
        if beyond and overlap:
            return True
    return False


def rebuild_bar(info, kind, decision):
    """New contour for the bar. decision: end name -> ('cap', bulge) or
    ('flat', edge_y). Returns None when nothing changes (both ends flat)."""
    cap = {n: d[0] == "cap" for n, d in decision.items()}
    if not any(cap.values()):
        return None
    if kind == "v":
        t = decision["top"]
        b = decision["bot"]
        top_y = t[1] if t[0] == "flat" else info["ends"]["top"]["corner"]
        bot_y = b[1] if b[0] == "flat" else info["ends"]["bot"]["corner"]
        bulge_t = t[1] if t[0] == "cap" else 0
        bulge_b = b[1] if b[0] == "cap" else 0
        return build_vbar(info["left"], info["right"], top_y, bot_y,
                          t[0] == "cap", b[0] == "cap", bulge_t, bulge_b)
    t = decision["right"]
    b = decision["left"]
    right_x = t[1] if t[0] == "flat" else info["ends"]["right"]["corner"]
    left_x = b[1] if b[0] == "flat" else info["ends"]["left"]["corner"]
    bulge_r = t[1] if t[0] == "cap" else 0
    bulge_l = b[1] if b[0] == "cap" else 0
    return build_hbar(info["top"], info["bot"], left_x, right_x,
                      t[0] == "cap", b[0] == "cap", bulge_r, bulge_l)


# ------------------------------------------------------------ the operations --

def measure_stem_width(font, upm):
    """Width of the font's 丨 vertical stroke (fallback 0.081 * upm)."""
    cmap = font.getBestCmap()
    try:
        g = font["glyf"][cmap[ord("丨")]]
        if g.numberOfContours >= 0:
            return g.xMax - g.xMin
    except Exception:
        pass
    return int(0.081 * upm)


def find_roof_dot(glyph):
    """Index of the small, high, centered teardrop contour (the 宀/冖 dot),
    or None."""
    gw = glyph.xMax - glyph.xMin
    gh = glyph.yMax - glyph.yMin
    gcx = (glyph.xMin + glyph.xMax) / 2
    best = None
    best_y = -1
    for i, (s, e) in enumerate(split_contours(glyph)):
        pts = list(glyph.coordinates[s:e + 1])
        x0, y0, x1, y1 = contour_bbox(pts)
        w, h = x1 - x0, y1 - y0
        cx = (x0 + x1) / 2
        if w < 0.05 * gw or w > 0.22 * gw:
            continue
        # (max with 150: the standalone 宀 radical glyph is short, its dot
        # would otherwise fail the relative-height test)
        if h < 0.10 * gh or h > max(0.30 * gh, 150.0):
            continue
        if not (0.35 <= w / max(h, 1) <= 1.45):
            continue
        # (max with 20000: same short-glyph issue as the height test above)
        if w * h >= max(0.05 * gw * gh, 20000):
            continue
        if abs(cx - gcx) > 0.10 * gw:
            continue
        if y1 < glyph.yMax - 0.08 * gh:  # must touch the glyph top region
            continue
        if y1 > best_y:
            best, best_y = i, y1
    return best


def _bar_carries_drop(bar_pts, bar_top, bar_bot, edge_x, gw, gh, is_left):
    """Rule A: the drop is drawn as part of the bar contour itself (this
    font draws 宀 as one contour: bar + both drops). Only the bar's own
    points are examined, so unrelated ink of lower components can never
    leak in. The bar's TOP edge is the reference (its bbox bottom already
    includes the drop)."""
    lo = edge_x - 0.05 * gw if is_left else edge_x - 0.14 * gw
    hi = edge_x + 0.14 * gw if is_left else edge_x + 0.05 * gw
    ys = sorted((y for (x, y) in bar_pts if lo <= x <= hi and y < bar_top - 35),
                reverse=True)
    if not ys or ys[0] < bar_top - 155:
        return False
    gap_max = max(120.0, 0.12 * gh)
    drop_min = ys[0]
    for y in ys[1:]:
        if drop_min - y > gap_max:
            break
        drop_min = y
    length = bar_top - 35 - drop_min
    return 30 <= length <= max(0.26 * gh, 230.0)


def _separate_drop(glyph, spans, dot_idx, bar, gw, gh):
    """Rule B: the bar is a plain stroke and a separate narrow stroke hugs
    one of its ends (the 冖 pattern, e.g. 哀 宪)."""
    bx0, by0, bx1, by1 = bar
    for i, (ss, ee) in enumerate(spans):
        if i == dot_idx:
            continue
        pts = list(glyph.coordinates[ss:ee + 1])
        x0, y0, x1, y1 = contour_bbox(pts)
        w = x1 - x0
        if w > 0.15 * gw or w < 20:
            continue
        if not (by1 - 130 <= y1 <= by1 - 25):
            continue
        length = y1 - y0
        if not (60 <= length <= 0.22 * gh):
            continue
        cx = (x0 + x1) / 2
        if abs(cx - bx0) <= 0.06 * gw or abs(cx - bx1) <= 0.06 * gw:
            return True
    return False


def find_roof_bar(glyph, dot_idx):
    """(bar_idx, (x0, y0, x1, y1)) of the wide centered 宀/冖 bar just below
    the dot, or (None, None)."""
    spans = split_contours(glyph)
    s, e = spans[dot_idx]
    dx0, dy0, dx1, dy1 = contour_bbox(glyph.coordinates[s:e + 1])
    gw = glyph.xMax - glyph.xMin
    gcx = (glyph.xMin + glyph.xMax) / 2
    bar = None
    bar_idx = None
    for i, (ss, ee) in enumerate(spans):
        if i == dot_idx:
            continue
        pts = list(glyph.coordinates[ss:ee + 1])
        if _bar_kind([(x, y, True) for x, y in pts]) != "h":
            continue
        x0, y0, x1, y1 = contour_bbox(pts)
        if x1 - x0 < 0.60 * gw:
            continue
        if abs((x0 + x1) / 2 - gcx) > 0.10 * gw:
            continue
        if not (dy0 - 25 <= y1 <= dy0 + 55):
            continue
        if bar is None or y1 > bar[3]:
            bar, bar_idx = (x0, y0, x1, y1), i
    return bar_idx, bar


def has_roof_structure(glyph, dot_idx):
    """The dot must sit just above a wide, centered horizontal bar that has
    a short side drop at at least one end (the 宀/冖 pattern). Excludes 亠
    glyphs (主 产 立: dot + bar, no drops) and 冂-based false matches (the
    box stroke is a separate long stroke, not a drop)."""
    gw = glyph.xMax - glyph.xMin
    gh = glyph.yMax - glyph.yMin
    spans = split_contours(glyph)
    bar_idx, bar = find_roof_bar(glyph, dot_idx)
    if bar is None:
        return False
    bx0, by0, bx1, by1 = bar
    if by1 - by0 >= 100:  # bar contour already carries the drops
        bar_pts = [tuple(p) for p in glyph.coordinates[spans[bar_idx][0]:
                         spans[bar_idx][1] + 1]]
        return (_bar_carries_drop(bar_pts, by1, by0, bx0, gw, gh, True)
                or _bar_carries_drop(bar_pts, by1, by0, bx1, gw, gh, False))
    return _separate_drop(glyph, spans, dot_idx, bar, gw, gh)


def op_roof_dot_to_stem(font, chars, stem_width=None, require_roof=True):
    upm = font["head"].unitsPerEm
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    if stem_width is None:
        stem_width = measure_stem_width(font, upm)
    report = {}
    for ch in chars:
        gname = cmap.get(ord(ch))
        if not gname:
            report[ch] = "skipped: no glyph"
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 0:
            report[ch] = "skipped: composite"
            continue
        idx = find_roof_dot(glyph)
        if idx is None:
            report[ch] = "skipped: no 宀 dot found"
            continue
        if require_roof and not has_roof_structure(glyph, idx):
            report[ch] = "skipped: dot not in a 宀 structure"
            continue
        # Drop the gvar data BEFORE touching the outlines: the lazy decompile
        # reads the current point count, which the edit would invalidate.
        had_variation = _drop_variations(font, gname)
        spans = split_contours(glyph)
        s, e = spans[idx]
        x0, y0, x1, y1 = contour_bbox(glyph.coordinates[s:e + 1])
        cy = (y0 + y1) / 2
        dot_cx = (x0 + x1) / 2
        # The slanted dot's bbox is usually a bit left of the 宀 bar's
        # center; the replacement stem is centered on the BAR so it reads
        # as centered over the roof.
        bar_idx, bar = find_roof_bar(glyph, idx)
        cx = (bar[0] + bar[2]) / 2 if bar else dot_cx
        # Sink the stem's bottom INTO the bar (the handwritten dots often
        # float a few units above the bar; a floating capsule reads as
        # detached). Top stays at the dot's top; bottom reaches at least
        # 25u below the bar's top edge when it currently sits above it.
        top_apex = y1
        bot_apex = min(y0, bar[3] - 25) if bar else y0
        hh = max((top_apex - bot_apex) / 2, stem_width * 0.85)
        cy = top_apex - hh
        new_contours = []
        for j, (ss, ee) in enumerate(spans):
            if j == idx:
                new_contours.append(capsule(cx, cy, stem_width / 2, hh))
            else:
                new_contours.append(contour_points(glyph, ss, ee))
        set_glyph_contours(glyph, new_contours)
        report[ch] = {
            "dot_bbox": [x0, y0, x1, y1],
            "stem": {"width": stem_width, "height": int(2 * hh),
                     "center": [round(cx, 1), round(cy, 1)],
                     "dot_cx": round(dot_cx, 1),
                     "shift": round(cx - dot_cx, 1)},
        }
    return report


# ------------------------------------------------- roof bar (宀横) round ends --

def _analyze_roof_bar(ring, gw, gh):
    """Analyze a 宀/冖 bar+drop contour (one contour: bar + side drops).
    Returns a geometry dict or None."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    if w < 0.5 * gw or not (40 <= h <= 0.32 * gh) or w < 2.2 * h:
        return None
    bar_top = y1
    top_edge = [p for p in ring if p[1] >= bar_top - 6]
    if len(top_edge) < 4:
        return None
    t0 = min(p[0] for p in top_edge)
    t1 = max(p[0] for p in top_edge)
    if (t1 - t0) < 0.5 * w:
        return None
    left_x, right_x = x0, x1
    cx_lo, cx_hi = x0 + 0.25 * w, x1 - 0.25 * w
    mid = [p for p in ring if cx_lo <= p[0] <= cx_hi]
    if not mid:
        return None
    bar_bot = min(p[1] for p in mid)
    bar_h = bar_top - bar_bot
    if not (40 <= bar_h <= 110):
        return None
    if (right_x - left_x) - bar_h < 50:  # top edge too short for two fillets
        return None
    legs = {}
    for side in ('left', 'right'):
        lo, hi = (x0 - 5, x0 + 0.25 * w) if side == 'left' \
            else (x1 - 0.25 * w, x1 + 5)
        pts = [p for p in ring if lo <= p[0] <= hi and p[1] < bar_bot - 20]
        if len(pts) < 6:
            continue
        leg_bot = min(p[1] for p in pts)
        drop = bar_bot - leg_bot
        if not (60 <= drop <= 260):
            continue
        deep = [p for p in pts if p[1] < bar_bot - 40]
        if not deep:
            continue
        if side == 'left':
            outer = min(p[0] for p in deep)
            inner = max(p[0] for p in deep)
        else:
            outer = max(p[0] for p in deep)
            inner = min(p[0] for p in deep)
        leg_w = abs(inner - outer)
        if not (25 <= leg_w <= 130):
            continue
        # outer edge must align with the bar outer edge
        if abs(outer - (left_x if side == 'left' else right_x)) > 10:
            continue
        legs[side] = {'bot': leg_bot, 'inner': inner, 'outer': outer,
                      'w': leg_w}
    if not legs:
        return None
    return {'left_x': left_x, 'right_x': right_x, 'bar_top': bar_top,
            'bar_bot': bar_bot, 'bar_h': bar_h, 'legs': legs}


def _signed_area(ring):
    s = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2


def _rebuild_roof_bar(a):
    """Clean 宀/冖 bar: straight shaft, full semicircle shoulders at both
    bar ends (全端半圆), full semicircle caps on the drop bottoms. The
    handwritten wobble of a 70u straight bar is not worth keeping."""
    lt, lb = a['bar_top'], a['bar_bot']
    lx, rx = a['left_x'], a['right_x']
    r_top = a['bar_h'] / 2
    L, R = a['legs'].get('left'), a['legs'].get('right')
    capL_y = L['bot'] + L['w'] / 2 if L else None
    capR_y = R['bot'] + R['w'] / 2 if R else None
    if L and capL_y >= lt - r_top - 10:
        L = None
    if R and capR_y >= lt - r_top - 10:
        R = None
    pts = []
    pts.append((rx, lt - r_top, 1))
    if R:
        pts.append((rx, capR_y, 1))
        pts += _ellipse_arc((R['inner'] + R['outer']) / 2, capR_y,
                            R['w'] / 2, R['w'] / 2, 0, -180, n=4)[1:]
        pts.append((R['inner'], lb, 1))
    else:
        pts.append((rx, lb, 1))
    endL = L['inner'] if L else lx
    pts.append((endL, lb, 1))
    if L:
        pts.append((L['inner'], capL_y, 1))
        pts += _ellipse_arc((L['inner'] + L['outer']) / 2, capL_y,
                            L['w'] / 2, L['w'] / 2, 0, -180, n=4)[1:]
        pts.append((lx, lt - r_top, 1))
    else:
        pts.append((lx, lb, 1))
        pts.append((lx, lt - r_top, 1))
    pts += _ellipse_arc(lx + r_top, lt - r_top, r_top, r_top, 180, 90, n=2)[1:]
    pts.append((rx - r_top, lt, 1))
    pts += _ellipse_arc(rx - r_top, lt - r_top, r_top, r_top, 90, 0, n=2)[1:]
    return pts


def op_roof_bar_round(font, chars):
    """全端半圆 for 宀/冖 bars: the bar's left/right ends become full
    semicircle shoulders and the drops (垂脚) get full semicircle bottoms.
    Runs over all chars; the analyzer self-guards (wide centered bar with
    real drops; plain bars and 冂 boxes are rejected)."""
    import smooth_strokes as ss
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    report = {}
    for ch in chars:
        gname = cmap.get(ord(ch))
        if not gname:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 0:
            continue
        spans = split_contours(glyph)
        gw = glyph.xMax - glyph.xMin
        gh = glyph.yMax - glyph.yMin
        new_contours, touched = [], []
        for (s, e) in spans:
            pts = contour_points(glyph, s, e)
            ring = [(x, y) for (x, y, on) in pts]
            dense = ss.resample_ring(ring, 5.0)
            info = _analyze_roof_bar(dense, gw, gh)
            if info is None:
                new_contours.append(pts)
                continue
            contour = _rebuild_roof_bar(info)
            ring2 = [(x, y) for (x, y, on) in contour]
            ob = (min(p[0] for p in ring), min(p[1] for p in ring),
                  max(p[0] for p in ring), max(p[1] for p in ring))
            nb = (min(p[0] for p in ring2), min(p[1] for p in ring2),
                  max(p[0] for p in ring2), max(p[1] for p in ring2))
            if (nb[0] < ob[0] - 3 or nb[2] > ob[2] + 3 or
                    nb[1] < ob[1] - 3 or nb[3] > ob[3] + 3):
                new_contours.append(pts)
                continue
            if (_signed_area(ring2) * _signed_area(dense) <= 0 or
                    abs(_signed_area(ring2)) < 0.5 * abs(_signed_area(dense))):
                new_contours.append(pts)
                continue
            new_contours.append(contour)
            touched.append(s)
        if not touched:
            continue
        had_variation = _drop_variations(font, gname)
        set_glyph_contours(glyph, new_contours)
        report[ch] = {"contours": touched,
                      "weight_variation_dropped": bool(had_variation)}
    return report


# ------------------------------------------------------- 提手 (扌) shorten --

def find_tishou_vertical(glyph):
    """Index of the 扌 (hand radical) vertical contour, or None.

    扌 = a tall (full-height) slightly slanted vertical at the left side,
    plus a short 横 crossing it in the upper half, plus a rising 提 stroke
    starting near the vertical. 林/根 (left 木, full-height vertical but no
    横/提) and 犭 (no 横) are rejected by the 横+提 requirements."""
    gw = glyph.xMax - glyph.xMin
    gh = glyph.yMax - glyph.yMin
    x0, y0 = glyph.xMin, glyph.yMin
    spans = split_contours(glyph)
    bboxes = [contour_bbox(glyph.coordinates[s:e + 1]) for s, e in spans]
    import smooth_strokes as ss
    vidx, vb, vdense = None, None, None
    for i, b in enumerate(bboxes):
        w, h = b[2] - b[0], b[3] - b[1]
        cx = (b[0] + b[2]) / 2 - x0
        if not (h >= 0.72 * gh and 130 <= w <= 0.36 * gw
                and 0.08 <= cx / gw <= 0.42):
            continue
        if b[1] > y0 + 0.15 * gh:  # must reach the bottom region
            continue
        # a single STROKE: the transverse span at any height stays thin.
        # A 月 frame (撇+横折 in one contour) spans 200-300u at mid
        # height and is rejected here.
        s, e = spans[i]
        ring = [(p[0], p[1]) for p in glyph.coordinates[s:e + 1]]
        dense = ss.resample_ring(ring, 8.0)
        bad = False
        for f_ in (0.1, 0.3, 0.5, 0.7, 0.9):
            y = b[1] + f_ * h
            xs = [p[0] for p in dense if abs(p[1] - y) < 12]
            if xs and max(xs) - min(xs) > 150:
                bad = True
                break
        if bad:
            continue
        vidx, vb, vdense = i, b, dense
        break
    if vidx is None:
        return None
    hbar = None
    for i, b in enumerate(bboxes):
        if i == vidx:
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        if not (0.10 * gw <= w <= 0.5 * gw and h <= 0.12 * gh
                and w >= 2.5 * h):
            continue
        cx = (b[0] + b[2]) / 2 - x0
        if not (vb[0] - 0.05 * gw <= cx <= vb[2] + 0.05 * gw):
            continue
        if (b[1] + b[3]) / 2 < y0 + 0.45 * gh:  # upper half only
            continue
        hbar = i
        break
    if hbar is None:
        return None
    # the 提 must START ON the vertical (its left end touches the shaft):
    # rising 横s of right-side components (土 in 肚, 羽 in 翔, 生 in 胜)
    # sit next to the vertical, not on it. dmin is measured against the
    # DENSE resampled shaft (raw contour points are too sparse).
    ti = None
    for i, b in enumerate(bboxes):
        if i in (vidx, hbar):
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        if not (w >= 0.08 * gw and 0.15 <= h / max(w, 1) <= 1.2):
            continue
        if b[0] < vb[0] - 0.08 * gw or b[2] > vb[2] + 0.45 * gw:
            continue
        cy = (b[1] + b[3]) / 2
        if cy < y0 + 0.15 * gh or cy > y0 + 0.6 * gh:
            continue
        s, e = spans[i]
        pts = [(p[0], p[1]) for p in glyph.coordinates[s:e + 1]]
        left_y = min(y for x, y in pts if x <= b[0] + 0.25 * w)
        right_y = max(y for x, y in pts if x >= b[2] - 0.25 * w)
        if right_y - left_y < max(0.35 * h, 30):
            continue
        # contact: some part of the 提 must sit on/near the shaft (the
        # left END can overhang past the shaft — handwritten 提s start
        # with a leftward entry, so the contour's leftmost point is not
        # a reliable contact anchor)
        tspan = ss.resample_ring(pts, 8.0)
        hit = False
        lim2 = 60 * 60
        for tx, ty in tspan:
            for vx, vy in vdense:
                dx = tx - vx
                if dx > 60 or dx < -60:
                    continue
                if dx * dx + (ty - vy) ** 2 <= lim2:
                    hit = True
                    break
            if hit:
                break
        if not hit:
            continue
        ti = i
        break
    if ti is None:
        return None
    return vidx


def round_ti_tip(pts):
    """Full-width semicircle round head for the 提 stroke terminal."""
    n = len(pts)
    i_max_x = max(range(n), key=lambda i: pts[i][0])
    i_top = i_max_x
    while True:
        i_top = (i_top - 1) % n
        if pts[i_top][2]:
            break
    i_bot = i_max_x
    while True:
        i_bot = (i_bot + 1) % n
        if pts[i_bot][2]:
            break
    p1 = (pts[i_top][0], pts[i_top][1])
    p2 = (pts[i_bot][0], pts[i_bot][1])
    w = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if not (40 <= w <= 110):
        return pts
    r = w / 2
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    nx, ny = -dy / w, dx / w
    if nx < 0:
        nx, ny = -nx, -ny
    a1 = math.atan2(p1[1] - my, p1[0] - mx)
    a2 = math.atan2(p2[1] - my, p2[0] - mx)
    d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    if d == 0:
        d = math.pi
    a_out = math.atan2(ny, nx)
    if math.cos(a1 + d / 2 - a_out) < 0:
        d = -d
    n_seg = 4
    cap_pts = []
    for i in range(n_seg):
        ang0 = a1 + d * i / n_seg
        ang1 = a1 + d * (i + 1) / n_seg
        ang_mid = (ang0 + ang1) / 2
        r_ctrl = r / math.cos(d / (2 * n_seg))
        cx = mx + r_ctrl * math.cos(ang_mid)
        cy = my + r_ctrl * math.sin(ang_mid)
        px1 = mx + r * math.cos(ang1)
        py1 = my + r * math.sin(ang1)
        cap_pts.append((cx, cy, 0))
        cap_pts.append((px1, py1, 1))
    if i_top < i_bot:
        return pts[:i_top + 1] + cap_pts + pts[i_bot + 1:]
    else:
        return pts[i_bot:i_top + 1] + cap_pts


def round_pingna_tail(pts):
    """Full-width semicircle round head for 走之底/平捺 tail in 题/提."""
    n = len(pts)
    top_candidates = [i for i in range(n) if pts[i][2] and pts[i][0] > 880 and pts[i][1] >= -10]
    bot_candidates = [i for i in range(n) if pts[i][2] and pts[i][0] > 880 and pts[i][1] <= -50]
    if not top_candidates or not bot_candidates:
        return pts
    i_top = max(top_candidates, key=lambda i: pts[i][0])
    i_bot = min(bot_candidates, key=lambda i: pts[i][1])
    top_y = pts[i_top][1]
    bot_y = pts[i_bot][1]
    w = top_y - bot_y
    if not (45 <= w <= 95):
        return pts
    r = w / 2
    x_cut = min(pts[i_top][0], pts[i_bot][0])
    cap = _hbar_cap_top_to_bottom(top_y, bot_y, x_cut, r)
    if i_bot < i_top:
        return pts[i_bot:i_top + 1] + cap[1:]
    else:
        return pts[i_bot:] + pts[:i_top + 1] + cap[1:]


def op_tishou_shorten(font, chars):
    """割短: the 扌 radical's vertical is too long in this font. Cut its
    bottom up by ~10% of the glyph height and give the new bottom a clean
    full semicircle cap (全端半圆). The 横/提 of the radical are untouched."""
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    report = {}
    for ch in chars:
        gname = cmap.get(ord(ch))
        if not gname:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 0:
            continue
        vidx = find_tishou_vertical(glyph)
        if vidx is None:
            continue
        spans = split_contours(glyph)
        gh = glyph.yMax - glyph.yMin
        s, e = spans[vidx]
        pts = contour_points(glyph, s, e)
        top_pts = [p for p in pts if p[1] > glyph.yMin + 0.7 * gh]
        if not top_pts:
            continue
        left = min(p[0] for p in top_pts)
        right = max(p[0] for p in top_pts)
        w = right - left
        r = w / 2
        top_y = max(p[1] for p in top_pts) - r
        ymin = min(p[1] for p in pts)
        cut = 0.0  # 竖不要缩短：保持原有落脚深度，缩小曲度直立，底部与右侧自然对齐
        bot_y = ymin + cut + r
        new_bar = build_vbar(left, right, top_y, bot_y, True, True, r, r)
        new_contours = []
        for pi, (s2, e2) in enumerate(spans):
            pts2 = contour_points(glyph, s2, e2)
            if pi == vidx:
                new_contours.append(new_bar)
            else:
                b = contour_bbox(pts2)
                if b[0] < 100 and 200 <= b[1] <= 300 and 350 <= b[3] <= 450:
                    new_contours.append(round_ti_tip(pts2))
                else:
                    new_contours.append(pts2)
        had_variation = _drop_variations(font, gname)
        set_glyph_contours(glyph, new_contours)
        report[ch] = {"contour": vidx, "cut": round(cut),
                      "new_bottom": round(bot_y - r),
                      "weight_variation_dropped": bool(had_variation)}
    return report


def op_round_terminals(font, chars):
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    report = {}
    for ch in chars:
        gname = cmap.get(ord(ch))
        if not gname:
            report[ch] = "skipped: no glyph"
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 0:
            report[ch] = "skipped: composite"
            continue
        spans = split_contours(glyph)
        bboxes = [contour_bbox(glyph.coordinates[s:e + 1]) for s, e in spans]
        new_contours = []
        touched = []
        for j, (s, e) in enumerate(spans):
            pts = contour_points(glyph, s, e)
            kind = _bar_kind(pts)
            info = _analyze_bar(pts, kind) if kind else None
            if info is None:
                new_contours.append(pts)
                continue
            others = [b for k, b in enumerate(bboxes) if k != j]
            decision = {}
            for end_name, end in info["ends"].items():
                if _end_is_hidden(info, end_name, others):
                    decision[end_name] = ("flat", end["cut"])
                else:
                    # Every VISIBLE terminal becomes a full semicircle
                    # (bulge = r): the 圆头化 request — handwritten ends get
                    # true round heads, regardless of the original flatness.
                    decision[end_name] = ("cap", info["r"])
            contour = rebuild_bar(info, kind, decision)
            if contour is None:
                new_contours.append(pts)
                continue
            new_contours.append(contour)
            ends_rep = {}
            for n, d in decision.items():
                ends_rep[n] = "cap-full" if d[0] == "cap" else "flat-hidden"
            touched.append({
                "kind": kind,
                "ends": ends_rep,
                "points_before": e - s + 1,
                "points_after": len(contour),
            })
        if not touched:
            report[ch] = "skipped: no bar contours"
            continue
        had_variation = _drop_variations(font, gname)
        set_glyph_contours(glyph, new_contours)
        report[ch] = {"contours": touched,
                      "weight_variation_dropped": bool(had_variation)}
    return report


def op_remove_hooks(font, chars=("九", "刀", "丸", "兔", "免", "北", "儿")):
    """去钩平转（无挑钩）：去除九、刀、丸、兔、免、北、儿等底部的尖硬挑钩，替换为水平延伸的标准饱满半圆胶囊头（stadium cap），
    采用 _ellipse_arc 严格生成与『一/王』一致的 TrueType 二次贝塞尔全圆弧。"""
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    report = {}

    for ch in chars:
        if ord(ch) not in cmap:
            continue
        gname = cmap[ord(ch)]
        g = glyf[gname]
        spans = split_contours(g)
        if ch == '九':
            c0 = contour_points(g, spans[0][0], spans[0][1])
            c1 = contour_points(g, spans[1][0], spans[1][1])
            cap = _ellipse_arc(903.5, -28.5, 36.5, 36.5, 90, -90)
            new_c1 = c1[:25] + cap[1:-1]
            _drop_variations(font, gname)
            set_glyph_contours(g, [c0, new_c1])
            report[ch] = {"status": "hook-removed"}
        elif ch == '丸':
            c0 = contour_points(g, spans[0][0], spans[0][1])
            c1 = contour_points(g, spans[1][0], spans[1][1])
            c2 = contour_points(g, spans[2][0], spans[2][1])
            cap = _ellipse_arc(908.0, -28.0, 37.0, 37.0, 90, -90)
            new_c2 = c2[:25] + cap[1:-1]
            _drop_variations(font, gname)
            set_glyph_contours(g, [c0, c1, new_c2])
            report[ch] = {"status": "hook-removed"}
        elif ch == '刀':
            c0 = contour_points(g, spans[0][0], spans[0][1])
            c1 = contour_points(g, spans[1][0], spans[1][1])
            c2 = contour_points(g, spans[2][0], spans[2][1])
            cap = _ellipse_arc(569.5, -28.5, 39.5, 39.5, -90, -270)
            new_c1 = c1[4:36] + cap[1:-1]
            _drop_variations(font, gname)
            set_glyph_contours(g, [c0, new_c1, c2])
            report[ch] = {"status": "hook-removed"}
        elif ch == '兔':
            cap = _ellipse_arc(911.0, -41.0, 34.0, 34.0, 90, -90)
            new_contours = []
            for idx, (s, e) in enumerate(spans):
                pts = contour_points(g, s, e)
                if idx == 5:
                    new_contours.append(pts[:22] + cap[1:-1])
                else:
                    new_contours.append(pts)
            _drop_variations(font, gname)
            set_glyph_contours(g, new_contours)
            report[ch] = {"status": "hook-removed"}
        elif ch == '免':
            cap = _ellipse_arc(906.0, -26.0, 34.0, 34.0, 90, -90)
            new_contours = []
            for idx, (s, e) in enumerate(spans):
                pts = contour_points(g, s, e)
                if idx == 0:
                    new_contours.append(pts[:22] + cap[1:-1])
                else:
                    new_contours.append(pts)
            _drop_variations(font, gname)
            set_glyph_contours(g, new_contours)
            report[ch] = {"status": "hook-removed"}
        elif ch == '北':
            cap = _ellipse_arc(903.5, -20.5, 36.5, 36.5, 90, -90)
            new_contours = []
            for idx, (s, e) in enumerate(spans):
                pts = contour_points(g, s, e)
                if idx == 1:
                    new_contours.append(pts[:26] + cap[1:-1])
                else:
                    new_contours.append(pts)
            _drop_variations(font, gname)
            set_glyph_contours(g, new_contours)
            report[ch] = {"status": "hook-removed"}
        elif ch == '儿':
            cap = _ellipse_arc(904.0, -34.0, 36.0, 36.0, 90, -90)
            new_contours = []
            for idx, (s, e) in enumerate(spans):
                pts = contour_points(g, s, e)
                if idx == 1:
                    new_contours.append(pts[:26] + cap[1:-1])
                else:
                    new_contours.append(pts)
            _drop_variations(font, gname)
            set_glyph_contours(g, new_contours)
            report[ch] = {"status": "hook-removed"}
    return report


def op_flat_na(font, chars=("题", "提")):
    """平捺平展托举与标准半圆收头：
    将题、提的底捺（走之底/是之底捺）水平充分平展延伸，稳定托举右侧部首（如题之页），
    并以标准半圆胶囊头（_ellipse_arc）饱满收笔，杜绝切短悬空。"""
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    report = {}

    for ch in chars:
        if ord(ch) not in cmap:
            continue
        gname = cmap[ord(ch)]
        g = glyf[gname]
        spans = split_contours(g)
        if ch == '题':
            cap = _ellipse_arc(943.5, -26.5, 31.5, 31.5, 90, -90)
            new_contours = []
            for idx, (s, e) in enumerate(spans):
                pts = contour_points(g, s, e)
                if idx == 8:
                    new_contours.append(pts[5:24] + cap[1:-1])
                else:
                    new_contours.append(pts)
            _drop_variations(font, gname)
            set_glyph_contours(g, new_contours)
            report[ch] = {"status": "flat-na-applied"}
        elif ch == '提':
            cap = _ellipse_arc(941.5, -31.5, 33.5, 33.5, 90, -90)
            new_contours = []
            for idx, (s, e) in enumerate(spans):
                pts = contour_points(g, s, e)
                if idx == 5:
                    new_contours.append(pts[5:22] + cap[1:-1])
                else:
                    new_contours.append(pts)
            _drop_variations(font, gname)
            set_glyph_contours(g, new_contours)
            report[ch] = {"status": "flat-na-applied"}
    return report


def op_square_ri_ti(font, chars=("题",)):
    """题字左上部：重构为规范、工整的 1:1 正方形日字（正方形日字），
    且五条笔画（左右竖、顶中底三横）统一保持严格的 66u 粗细，彻底消除粗细不均。"""
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    report = {}

    def make_true_rounded_rect(x0, y0, x1, y1, r, ccw=False):
        c_tr = _ellipse_arc(x1 - r, y1 - r, r, r, 90, 0)
        c_br = _ellipse_arc(x1 - r, y0 + r, r, r, 0, -90)
        c_bl = _ellipse_arc(x0 + r, y0 + r, r, r, -90, -180)
        c_tl = _ellipse_arc(x0 + r, y1 - r, r, r, 180, 90)
        pts = c_tr + c_br[1:] + c_bl[1:] + c_tl[1:]
        if pts[-1][:2] == pts[0][:2]:
            pts.pop()
        if ccw:
            pts = list(reversed(pts))
        return pts

    for ch in chars:
        if ch != '题' or ord('题') not in cmap:
            continue
        gname = cmap[ord('题')]
        g = glyf[gname]
        spans = split_contours(g)
        # 外框 330x330, 边宽统一 66u:
        # 左竖 [114, 180], 右竖 [378, 444] (宽 66u)
        # 底横 [476, 542], 中横 [608, 674], 顶横 [740, 806] (高 66u)
        # 上下内腔均为 198u x 66u
        c2 = make_true_rounded_rect(114, 476, 444, 806, 24, ccw=False)
        c0 = make_true_rounded_rect(180, 542, 378, 608, 10, ccw=True)
        c1 = make_true_rounded_rect(180, 674, 378, 740, 10, ccw=True)
        other = [contour_points(g, spans[i][0], spans[i][1]) for i in range(3, len(spans))]
        _drop_variations(font, gname)
        set_glyph_contours(g, [c0, c1, c2] + other)
        report[ch] = {"status": "square-ri-applied"}
    return report


def op_smooth_strokes(font, chars):
    """Smooth wobbly curved strokes and round their terminals (收笔圆角化).

    Each contour that is a clean thin stroke (撇 捺 钩, tapered stems, dots)
    is rebuilt as smoothed centerline + original width profile, with round
    heads at visible terminals and flat ends kept flat where they hide under
    a crossing stroke. Straight bars and protected contours (handled by specialized
    geometric ops) are left untouched."""
    glyf = font["glyf"]
    cmap = font.getBestCmap()
    report = {}

    PROTECTED_CONTOURS = {
        '九': {1},
        '丸': {2},
        '刀': {1},
        '兔': {5},
        '免': {0},
        '北': {1},
        '儿': {1},
        '题': {0, 1, 2, 8},
        '提': {5, 10},
        '打': {2},
        '找': {2},
        '指': {7},
        '卯': set(range(100)),
        '员': set(range(100)),
        '哭': set(range(100)),
    }

    for ch in chars:
        if ch in ('卯', '员', '哭'):
            report[ch] = "skipped: intact-plump-feet"
            continue
        gname = cmap.get(ord(ch))
        if not gname:
            report[ch] = "skipped: no glyph"
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 0:
            report[ch] = "skipped: composite"
            continue
        spans = split_contours(glyph)
        bboxes = [contour_bbox(glyph.coordinates[s:e + 1]) for s, e in spans]
        new_contours = []
        touched = []
        for j, (s, e) in enumerate(spans):
            pts = contour_points(glyph, s, e)
            if ch in PROTECTED_CONTOURS and j in PROTECTED_CONTOURS[ch]:
                new_contours.append(pts)
                continue
            others = [b for k, b in enumerate(bboxes) if k != j]
            other_polys = [contour_points(glyph, s2, e2)
                           for k2, (s2, e2) in enumerate(spans) if k2 != j]
            new = smooth_strokes.smooth_contour(pts, others, other_polys)
            if new is None:
                new_contours.append(pts)
                continue
            new_contours.append(new)
            touched.append({"contour": j,
                            "points_before": e - s + 1,
                            "points_after": len(new)})
        if not touched:
            report[ch] = "skipped: no smoothable contours"
            continue
        had_variation = _drop_variations(font, gname)
        set_glyph_contours(glyph, new_contours)
        report[ch] = {"contours": touched,
                      "weight_variation_dropped": bool(had_variation)}
    return report


def _drop_variations(font, gname):
    """Edited glyphs keep one shape across all weights in this prototype:
    their gvar delta data references the old point list and must go.

    Must be called BEFORE the outline edit (the lazy gvar decompile reads the
    current point count). Returns whether the glyph had variation data.
    """
    gvar = font.get("gvar")
    if gvar is None:
        return False
    had = False
    try:
        data = gvar.variations.get(gname, None)
        if data:
            had = True
    except Exception:
        return False
    if had:
        gvar.variations.pop(gname, None)
    return had


def gb2312_chars():
    chars = []
    for b1 in range(0xB0, 0xD8):
        for b2 in range(0xA1, 0xFF):
            try:
                chars.append(bytes([b1, b2]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return chars


# ---------------------------------------------------------------------- main --

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=SOURCE_FONT_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "build/font-edited.ttf")
    parser.add_argument("--ops", nargs="*",
                        choices=["roof-dot-to-stem", "roof-bar-round",
                                 "round-terminals", "tishou-shorten",
                                 "remove-hooks", "square-ri", "flat-na",
                                 "smooth-strokes"],
                        default=[])
    parser.add_argument("--all", action="store_true",
                        help="run over the whole GB2312 charset")
    parser.add_argument("--roof-chars",
                        default="宀家安宋宁宫宝寒容宏定宜宗官实宵宾审空窄突窗")
    parser.add_argument("--round-chars", default="一丨二三十王")
    parser.add_argument("--smooth-chars", default="王天丸九刀买卖员哭题兔免提北打找指")
    parser.add_argument("--stem-width", type=int,
                        help="short-stem width in font units (default: width of 丨)")
    parser.add_argument("--report", type=Path, default=None,
                        help="write the JSON report here (default: stdout)")
    args = parser.parse_args()

    if not args.ops:
        parser.error("no --ops given (or use --all)")

    font = TTFont(args.input)
    report = {}
    if "roof-dot-to-stem" in args.ops:
        r = op_roof_dot_to_stem(font, list(args.roof_chars), args.stem_width)
        report["roof-dot-to-stem"] = _summarize(r)
    if "roof-bar-round" in args.ops:
        r = op_roof_bar_round(font, gb2312_chars() if args.all
                              else list(args.roof_chars))
        report["roof-bar-round"] = _summarize(r)
    if "smooth-strokes" in args.ops:
        r = op_smooth_strokes(font, gb2312_chars() if args.all else list(args.smooth_chars))
        report["smooth-strokes"] = _summarize(r)
    if "round-terminals" in args.ops:
        r = op_round_terminals(
            font, gb2312_chars() if args.all else list(args.round_chars))
        report["round-terminals"] = _summarize(r)
    if "tishou-shorten" in args.ops:
        r = op_tishou_shorten(
            font, gb2312_chars() if args.all else ["打", "提", "找", "指"])
        report["tishou-shorten"] = _summarize(r)
    if "remove-hooks" in args.ops:
        r = op_remove_hooks(
            font, gb2312_chars() if args.all else ["九", "刀", "丸", "兔", "免", "北", "儿"])
        report["remove-hooks"] = _summarize(r)
    if "square-ri" in args.ops:
        r = op_square_ri_ti(
            font, ["题"])
        report["square-ri"] = _summarize(r)
    if "flat-na" in args.ops:
        r = op_flat_na(
            font, ["题", "提"])
        report["flat-na"] = _summarize(r)
    font.save(args.output)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(text + "\n")
        print(f"Edited font: {args.output}\nReport: {args.report}")
    else:
        print(text)


def _summarize(r):
    changed = {k: v for k, v in r.items() if isinstance(v, dict)}
    skipped = {k: v for k, v in r.items() if isinstance(v, str)}
    reasons = {}
    for v in skipped.values():
        reasons[v] = reasons.get(v, 0) + 1
    out = {"changed_count": len(changed), "changed": changed}
    if reasons:
        out["skipped_reasons"] = reasons
    return out


if __name__ == "__main__":
    main()
