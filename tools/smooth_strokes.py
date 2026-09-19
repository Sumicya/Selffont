#!/usr/bin/env python3
"""Curve-stroke smoothing + round stroke endings (收笔圆角化).

Rebuilds a thin stroke contour as:

    box-smoothed centerline (wobble removed, shape kept)
    + original width profile (calligraphic tapers preserved)
    + tip rounding: a small TANGENT arc (fillet) at tapered tips — the
      taper itself is kept all the way to the tip, only the very point is
      rounded and it may grow ~10-14u (the 圆角收笔)
    + flat cut ends: kept flat when hidden under a crossing stroke,
      full semicircle head when visible
    + wide-blunt (teardrop) tips: the original tip arc is preserved —
      the source 撇/捺 feet are already clean 圆头, and the pairing
      degenerates there (a synthetic tip would move the foot and notch
      the outline), so only the body is smoothed

Contours that are not clean thin strokes (boxes, 冂, thick blobs, clean
stadium bars already handled by round-terminals) are left untouched.

Pure geometry library; wired into edit_font.py as the smooth-strokes op.
"""
import math


# ------------------------------------------------------------ rail pairing --

def resample_ring(pts, step):
    """Resample a closed ring (list of (x, y)) at ~step spacing."""
    n = len(pts)
    cum = [0.0]
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    total = cum[-1]
    count = max(8, int(total / step))
    out = []
    j = 0
    for k in range(count):
        target = min(total * k / count, total)
        while j < n - 1 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        t = (target - cum[j]) / seg if seg > 1e-9 else 0.0
        x = pts[j][0] + t * (pts[(j + 1) % n][0] - pts[j][0])
        y = pts[j][1] + t * (pts[(j + 1) % n][1] - pts[j][1])
        out.append((x, y))
    return out


def _farthest_pair(pts):
    """(i, j): the ring endpoints of the stroke's diameter (its two tips)."""
    n = len(pts)
    best = 0
    best_d = -1
    for j in range(n):
        d = (pts[0][0] - pts[j][0]) ** 2 + (pts[0][1] - pts[j][1]) ** 2
        if d > best_d:
            best_d, best = d, j
    a = best
    best = 0
    best_d = -1
    for j in range(n):
        d = (pts[a][0] - pts[j][0]) ** 2 + (pts[a][1] - pts[j][1]) ** 2
        if d > best_d:
            best_d, best = d, j
    return a, best


def _cut_run(ring, i, ux, uy):
    """Detect a flat cut end at ring index i.

    A flat cut: the two ring edges at i are strongly asymmetric in
    axialness — one is the rail (nearly parallel to the stroke axis), the
    other is the cut edge (nearly across it). A rounded cap has two
    similar, moderately transverse edges; a tapered tip has two axial
    ones. Returns (corner1, corner2, cut_len, run_count, idx1, idx2) —
    the run occupies the contiguous ring indices idx1..idx2 — or None."""
    n = len(ring)

    def axiality(p, q):
        """|dot(edge, axis)|: 0 = transverse, 1 = along the axis."""
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            return None
        return abs(dx * ux + dy * uy) / L

    d_in = axiality(ring[(i - 1) % n], ring[i % n])
    d_out = axiality(ring[i % n], ring[(i + 1) % n])
    if d_in is None or d_out is None:
        return None
    # asymmetry + a genuinely transverse-ish cut edge. Cap edges near the
    # apex differ by <~0.27, so 0.40 excludes rounded tips.
    if max(d_in, d_out) - min(d_in, d_out) < 0.40:
        return None
    if min(d_in, d_out) > 0.60:
        return None
    e_in = d_in < d_out
    e_out = d_out < d_in
    if e_in:
        c1 = i
        j = i
        while True:
            v = axiality(ring[(j - 1) % n], ring[j % n])
            if v is None or v > 0.60:
                break
            c1 = (j - 1) % n
            j -= 1
        C1 = ring[c1]
        C2 = ring[i % n]
        iC1, iC2 = c1, i % n
    else:
        C1 = ring[i % n]
        c2 = i
        j = i
        while True:
            v = axiality(ring[j % n], ring[(j + 1) % n])
            if v is None or v > 0.60:
                break
            c2 = (j + 1) % n
            j += 1
        C2 = ring[c2]
        iC1, iC2 = i % n, c2
    L = math.hypot(C2[0] - C1[0], C2[1] - C1[1])
    if L < 12:
        return None
    # run count in traversal order (iC1 -> iC2, contiguous)
    cnt = (iC2 - iC1) % n + 1
    return C1, C2, L, cnt, iC1, iC2


def _dense_chain(chain):
    """Resample an open chain (~8u spacing)."""
    cum = [0.0]
    for i in range(len(chain) - 1):
        x0, y0 = chain[i]
        x1, y1 = chain[i + 1]
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    total = cum[-1]
    if total < 1:
        return None
    count = int(total / 8)
    out = []
    j = 0
    for k in range(count + 1):
        target = min(total * k / count, total)
        while j < len(chain) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        t = (target - cum[j]) / seg if seg > 1e-9 else 0.0
        out.append((chain[j][0] + t * (chain[j + 1][0] - chain[j][0]),
                    chain[j][1] + t * (chain[j + 1][1] - chain[j][1])))
    return out


# ------------------------------------------------------------------ core --

def extract_stroke(ring):
    """Decompose a thin-stroke outline ring into a stroke model.

    Returns a dict (center/widths over the FULL stroke, end styles) or None
    when the contour is not a clean thin stroke."""
    a, b = _farthest_pair(ring)
    if b > a:
        chain1 = ring[a:b + 1]
        chain2 = ring[b:] + ring[:a + 1]
    else:
        chain1 = ring[b:a + 1]
        chain2 = ring[a:] + ring[:b + 1]
    d1 = _dense_chain(chain1)
    d2 = _dense_chain(chain2)
    if d1 is None or d2 is None or len(d1) < 12 or len(d2) < 12:
        return None
    # axis from tip A (d1[0]) to tip B (d1[-1])
    ax = d1[-1][0] - d1[0][0]
    ay = d1[-1][1] - d1[0][1]
    alen = math.hypot(ax, ay)
    if alen < 1:
        return None
    ux, uy = ax / alen, ay / alen

    # ---- flat-cut re-anchoring ----
    # The farthest-pair split point of a flat cut end is a corner of the
    # cut; both chains share that corner and the pairing degenerates there
    # (width -> 0), so a hidden cut is misread as a tapered tip. Trim each
    # chain at its own cut corner so the two corners pair naturally
    # (center = cut midpoint, width = cut width), and force the end to
    # 'flat' with the true corners.
    ilo = min(a, b)
    ihi = max(a, b)
    ch1 = list(ring[ilo:ihi + 1])                # ilo -> ihi
    ch2 = list(ring[ihi:]) + list(ring[:ilo + 1])  # ihi -> ilo
    cut_at_start = None   # corners of the cut at d1[0] (end_a)
    cut_at_end = None     # corners of the cut at d1[-1] (end_b)
    any_cut = False
    for cut in (_cut_run(ring, a, ux, uy), _cut_run(ring, b, ux, uy)):
        if not cut:
            continue
        any_cut = True
        C1, C2, Lc, cnt, iC1, iC2 = cut
        # the run occupies the contiguous ring indices iC1..iC2; one of
        # its ends is ihi and the other chain's end sits at ilo, so the
        # run always sits at the END of exactly one chain:
        if iC2 == ihi:      # run at the end of ch1  (ch1 ends at ihi)
            if cnt > len(ch1):
                return None
            ch1 = ch1[:len(ch1) - cnt + 1]
            cut_at_end = (C1, C2)
        elif iC1 == ihi:    # run at the start of ch2 (ch2 starts at ihi)
            if cnt > len(ch2):
                return None
            ch2 = ch2[cnt - 1:]
            cut_at_end = (C1, C2)
        elif iC2 == ilo:    # run at the end of ch2 (ch2 ends at ilo)
            if cnt > len(ch2):
                return None
            ch2 = ch2[:len(ch2) - cnt + 1]
            cut_at_start = (C1, C2)
        else:               # iC1 == ilo: run at the start of ch1
            if cnt > len(ch1):
                return None
            ch1 = ch1[cnt - 1:]
            cut_at_start = (C1, C2)
    if any_cut:
        d1 = _dense_chain(ch1)
        d2 = _dense_chain(ch2)
        if d1 is None or d2 is None or len(d1) < 12 or len(d2) < 12:
            return None
        ax = d1[-1][0] - d1[0][0]
        ay = d1[-1][1] - d1[0][1]
        alen = math.hypot(ax, ay)
        if alen < 1:
            return None
        ux, uy = ax / alen, ay / alen

    o = d1[0]

    def tval(p):
        return (p[0] - o[0]) * ux + (p[1] - o[1]) * uy

    t1 = [tval(p) for p in d1]
    t2 = [tval(p) for p in d2]

    # ---- full-length pairing by axis projection ----
    tol = max(15.0, 0.04 * alen)
    center = []
    widths = []
    rail_p = []   # original chain1 point per sample (left-rail side)
    rail_q = []   # original chain2 point per sample (right-rail side)
    for k in range(len(d1)):
        p = d1[k]
        best = None
        best_dd = None
        for j in range(len(d2)):
            if abs(t2[j] - t1[k]) > tol:
                continue
            dd = math.hypot(p[0] - d2[j][0], p[1] - d2[j][1])
            if best_dd is None or dd < best_dd:
                best, best_dd = j, dd
        if best is None:
            return None
        q = d2[best]
        center.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
        widths.append(best_dd)
        rail_p.append(p)
        rail_q.append(q)

    # trim to where the rails are still distinct (very tip can degenerate)
    lo = 0
    while lo < len(widths) - 5 and widths[lo] < 4:
        lo += 1
    hi = len(widths) - 1
    while hi > lo + 4 and widths[hi] < 4:
        hi -= 1

    # ---- guards on the BODY (central 60%) ----
    n = len(widths)
    bs, be = int(n * 0.2), int(n * 0.8)
    body = widths[bs:be]
    med = sorted(body)[len(body) // 2]
    if not (24 <= med <= 150):
        return None
    wmax, wmin = max(body), min(body)
    if wmax > 2.4 * med or wmin < 0.12 * med:
        return None
    cb = center[bs:be + 1]
    length = sum(math.hypot(cb[k + 1][0] - cb[k][0],
                            cb[k + 1][1] - cb[k][1])
                 for k in range(len(cb) - 1))
    if length < 2.0 * med:
        return None
    # straight + constant = clean bar (round-terminals' job) -> skip.
    # dev is measured over the central 60% only: the pairing near the tips
    # is contaminated by corner artifacts when the diameter axis runs
    # diagonally across a flat cut end (e.g. 王's stem). The ends must
    # also be bar-like. The WIDTH profile near the tip is NOT a reliable
    # discriminator: the pairing degenerates at a cap apex (both chains
    # share the apex point, the "width" ramps 8, 16, 24, ... instead of
    # the true 48, 64, 74 of a semicircle), so a stadium cap read as a
    # slow taper and some bars were rebuilt — destroying the cap the
    # round-terminals op had just placed (the 一/王 teardrop ends).
    # Instead measure the END SPREAD geometrically: the max pairwise
    # distance of the ring points within 0.55*med of the tip. A cap or
    # flat cut spans ~full width there (the chord, ~0.9-1.05*med); a
    # true taper (a leaf, e.g. the 艹 short stems) spans <= ~0.6*med.
    def end_spread(tip_t):
        sel = [p for p in ring if abs(tval(p) - tip_t) <= 0.55 * med]
        if len(sel) < 4:
            return 0.0
        best = 0.0
        for i in range(len(sel)):
            for j in range(i + 1, len(sel)):
                dd = math.hypot(sel[i][0] - sel[j][0], sel[i][1] - sel[j][1])
                if dd > best:
                    best = dd
        return best
    axx = cb[-1][0] - cb[0][0]
    ayy = cb[-1][1] - cb[0][1]
    Ll = math.hypot(axx, ayy) or 1e-9
    dev = max(abs((p[1] - cb[0][1]) * axx - (p[0] - cb[0][0]) * ayy)
              for p in cb) / Ll
    ends_barlike = (end_spread(tval(d1[0])) > 0.75 * med and
                    end_spread(tval(d1[-1])) > 0.75 * med)
    if dev < 0.04 * Ll and max(body) < 1.3 * min(body) and ends_barlike:
        return None

    # end appendage guard: a width spike near an end means the contour
    # carries extra ink there (bar + 宀垂脚, hooks onto the shaft, ...) —
    # not a plain stroke tip; leave it untouched
    e8 = max(2, n // 8)
    if max(widths[:e8]) > 1.6 * med or max(widths[-e8:]) > 1.6 * med:
        return None

    center = center[lo:hi + 1]
    widths = widths[lo:hi + 1]
    rail_p = rail_p[lo:hi + 1]
    rail_q = rail_q[lo:hi + 1]
    n = len(center)
    margin = max(28.0, 0.07 * alen)
    # axis coordinate of the trimmed ends
    t_lo = tval(center[0])
    t_hi = tval(center[-1])

    # ---- end analysis ----
    def probe_width(t_target):
        k = min(range(len(d1)), key=lambda i: abs(t1[i] - t_target))
        p = d1[k]
        best_dd = None
        for j in range(len(d2)):
            if abs(t2[j] - t_target) > tol:
                continue
            dd = math.hypot(p[0] - d2[j][0], p[1] - d2[j][1])
            if best_dd is None or dd < best_dd:
                best_dd = dd
        return best_dd

    def end_model(tip, side):
        """('taper', tip_point) or ('flat', corner1, corner2)."""
        if side == 'start':
            r1 = [d1[k] for k in range(len(d1)) if t1[k] <= margin]
            r2 = [d2[j] for j in range(len(d2)) if t2[j] <= margin]
            w_in = widths[0]
            w_probe = probe_width(0.5 * margin)
        else:
            r1 = [d1[k] for k in range(len(d1)) if t1[k] >= alen - margin]
            r2 = [d2[j] for j in range(len(d2)) if t2[j] >= alen - margin]
            w_in = widths[-1]
            w_probe = probe_width(alen - 0.5 * margin)

        def closest_to_tip(region):
            if not region:
                return None
            return min(region, key=lambda p: (p[0] - tip[0]) ** 2 + (p[1] - tip[1]) ** 2)
        n1 = closest_to_tip(r1)
        n2 = closest_to_tip(r2)
        tip_gap = (math.hypot(n1[0] - n2[0], n1[1] - n2[1])
                   if (n1 is not None and n2 is not None) else 1e9)
        # converging outline (pointed tip) -> taper
        if tip_gap < 0.45 * max(w_in, 1) or \
                (w_probe is not None and w_probe < 0.8 * max(w_in, 1)):
            return ('taper', tip)

        # flat cut end: walk the transverse run from the tip
        def walk_transverse(chain, i0, reverse):
            corner = chain[i0]
            steps = 0
            while steps < len(chain) - 1:
                i = i0 + steps * (1 if not reverse else -1)
                j = i + (1 if not reverse else -1)
                sx = chain[j][0] - chain[i][0]
                sy = chain[j][1] - chain[i][1]
                sl = math.hypot(sx, sy)
                if sl < 1e-6:
                    break
                if abs(sx * ux + sy * uy) < 0.5 * sl:
                    corner = chain[j]
                    steps += 1
                else:
                    break
            return corner

        if side == 'end':
            c2 = walk_transverse(d2, 0, False)
            if math.hypot(c2[0] - tip[0], c2[1] - tip[1]) < 0.4 * w_in:
                c2 = walk_transverse(d1, len(d1) - 1, True)
        else:
            c2 = walk_transverse(d2, len(d2) - 1, True)
            if math.hypot(c2[0] - tip[0], c2[1] - tip[1]) < 0.4 * w_in:
                c2 = walk_transverse(d1, 0, False)
        if math.hypot(c2[0] - tip[0], c2[1] - tip[1]) < 0.4 * w_in:
            return ('taper', tip)
        return ('flat', tip, c2)

    # ---- wide-blunt (teardrop) tips (宽钝端) ----
    # A 收笔 that ends in a WIDE blunt teardrop — the source 撇/捺 tips:
    # the two edges meet in a wide V (the opening across 30u on each
    # side exceeds ~0.55*med), not a converging point. The rail pairing
    # there degenerates (one chain pins to the V corner while the other
    # runs along a foot edge, the "width" profile is garbage), and any
    # synthetic tip (tip curve, semicircle head) moves the foot off its
    # original position and notches the outline (the 捺's 咬口). Such
    # ends are marked 'blunt': rebuild_stroke splices back the ORIGINAL
    # ring arc between two cuts (the source teardrop is already a clean
    # 圆头) and only the body is smoothed.
    def v_opening(idx, dist=30.0):
        nr = len(ring)

        def walk(step):
            acc = 0.0
            i = idx
            while acc < dist:
                j = (i + step) % nr
                acc += math.hypot(ring[j][0] - ring[i][0],
                                  ring[j][1] - ring[i][1])
                i = j
            return ring[i]
        p1 = walk(1)
        p2 = walk(-1)
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    def chain_cut(chain, from_start, dist):
        """Index at arc distance `dist` from the tip end of the chain."""
        idx = 0 if from_start else len(chain) - 1
        step = 1 if from_start else -1
        acc = 0.0
        while 0 <= idx + step < len(chain):
            j = idx + step
            acc += math.hypot(chain[j][0] - chain[idx][0],
                              chain[j][1] - chain[idx][1])
            if acc >= dist:
                break
            idx = j
        return idx

    D = min(0.4 * med, 45.0)
    # end_a's tip is ring[min(a,b)] (d1[0]), end_b's is ring[max(a,b)]
    blunt_a = (not cut_at_start and v_opening(min(a, b)) > 0.55 * med)
    blunt_b = (not cut_at_end and v_opening(max(a, b)) > 0.55 * med)

    def blunt_end(tip, at_start):
        """('blunt', tip, arc, c1, c2). arc = original dense ring points
        cut -> tip -> cut in RING order; c1/c2 = the cut indices in the
        d1/d2 dense chains. rebuild_stroke splices the rebuilt rails
        onto the ORIGINAL chain points just past each cut (the pairing
        lingers in the V region and the synthetic rails there sit off
        the true edge).

        The arc must cover the tip's CORNER region (a wide foot like
        the 捺's keeps its silhouette up to ~0.9*med from the tip), so
        the cut distance is extended from 0.4*med to where the width
        profile first reads ~full, capped at 90u."""
        m1, m2 = len(d1), len(d2)
        if at_start:      # tip = d1[0] = d2[-1]
            k_full = next((kk for kk in range(len(widths))
                           if widths[kk] >= 0.9 * med), None)
            dist = (min(max(D, (lo + k_full + 2) * 8.0), 90.0)
                    if k_full is not None else D)
            c1 = chain_cut(d1, True, dist)
            c2 = chain_cut(d2, False, dist)
            arc = d2[c2:m2] + d1[1:c1 + 1]
        else:             # tip = d1[-1] = d2[0]
            k_full = next((kk for kk in range(len(widths) - 1, -1, -1)
                           if widths[kk] >= 0.9 * med), None)
            dist = (min(max(D, (len(widths) - 1 - k_full + 2) * 8.0), 90.0)
                    if k_full is not None else D)
            c1 = chain_cut(d1, False, dist)
            c2 = chain_cut(d2, True, dist)
            arc = d1[c1:m1] + d2[1:c2 + 1]
        return ('blunt', tip, arc, c1, c2)

    # a re-anchored flat cut keeps its true corners (the taper logic would
    # misread the cut midpoint as a converging tip)
    if cut_at_start:
        end_a = ('flat', cut_at_start[0], cut_at_start[1])
    elif blunt_a:
        end_a = blunt_end(d1[0], True)
    else:
        end_a = end_model(d1[0], 'start')
    if cut_at_end:
        end_b = ('flat', cut_at_end[0], cut_at_end[1])
    elif blunt_b:
        end_b = blunt_end(d1[-1], False)
    else:
        end_b = end_model(d1[-1], 'end')

    return {"center": center, "widths": widths, "med": med,
            "end_a": end_a, "end_b": end_b, "rail_p": rail_p,
            "rail_q": rail_q, "t_lo": t_lo, "t_hi": t_hi,
            "d1": d1, "d2": d2}


# ------------------------------------------------------------- smoothing --

def _box_smooth(vals, half, iters=1):
    n = len(vals)
    for _ in range(iters):
        new = list(vals)
        for i in range(1, n - 1):
            s = 0.0
            c = 0
            for j in range(max(0, i - half), min(n, i + half + 1)):
                s += vals[j]
                c += 1
            new[i] = s / c
        vals[:] = new
    return vals


def _resample_open(poly, n):
    """Resample an open chain to n+1 arc-length-uniform points
    (endpoints included)."""
    cum = [0.0]
    for i in range(len(poly) - 1):
        cum.append(cum[-1] + math.hypot(poly[i + 1][0] - poly[i][0],
                                        poly[i + 1][1] - poly[i][1]))
    total = cum[-1]
    if total < 1:
        return list(poly)
    out = []
    j = 0
    for k in range(n + 1):
        target = min(total * k / n, total)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        t = (target - cum[j]) / seg if seg > 1e-9 else 0.0
        out.append((poly[j][0] + t * (poly[j + 1][0] - poly[j][0]),
                    poly[j][1] + t * (poly[j + 1][1] - poly[j][1])))
    return out


def smooth_centerline(center, widths):
    """Kill the hand-drawn wobble in the centerline — a real smooth, not a
    light touch: coarse resample -> projected heat smoothing (every
    iteration clamps the drift to 12u of the raw centerline, so the
    calligraphic shape is kept while the wobble dies) -> resample back.
    Returns (center_s, widths_s) or None when a bend is tighter than the
    stroke width (rebuild would self-intersect).

    The width profile is only smoothed in the central 70% (the tapered
    ends are calligraphic design), clamped to ±14u so the taper gradient
    is not flattened."""
    m = len(center)
    N = max(48, m // 4)
    raw = _resample_open(center, N)
    pts = list(raw)
    for _ in range(300):
        moved = 0.0
        # stable Laplacian (alpha 0.5; a full step is unstable and the
        # period-2 mode never decays, so the 12u clamp would pin a
        # zigzag to its boundary)
        for i in range(1, N):
            x0, y0 = pts[i - 1]
            x2, y2 = pts[i + 1]
            dx = ((x0 + x2) / 2 - pts[i][0]) * 0.5
            dy = ((y0 + y2) / 2 - pts[i][1]) * 0.5
            d = math.hypot(dx, dy)
            if d > moved:
                moved = d
            pts[i] = (pts[i][0] + dx, pts[i][1] + dy)
        # drift clamp: the raw centerline wobble in this font reaches
        # ~20-25u, so the clamp must exceed it or an 8-12u S-wave
        # survives (visible on long 撇 / 弯钩). 24u flattens the whole
        # wobble; genuine calligraphic features (uniform arcs, the 捺
        # shoulder) are never pulled far by the Laplacian because
        # their neighbours sit on the same curve.
        for i in range(1, N):
            dx = pts[i][0] - raw[i][0]
            dy = pts[i][1] - raw[i][1]
            d = math.hypot(dx, dy)
            if d > 24.0:
                pts[i] = (raw[i][0] + dx * 24.0 / d,
                          raw[i][1] + dy * 24.0 / d)
        if moved < 0.15:
            break
    cs = _resample_open(pts, m - 1)
    ws = list(widths)
    s0 = int(m * 0.15)
    s1 = int(m * 0.85)
    raw_ws = list(ws)
    _box_smooth(ws[s0:s1], max(1, m // 10), iters=6)
    for i in range(s0, s1):
        if ws[i] > raw_ws[i] + 20:
            ws[i] = raw_ws[i] + 20
        elif ws[i] < raw_ws[i] - 20:
            ws[i] = raw_ws[i] - 20
    # self-intersection check on the body only (the tip regions are
    # replaced by the tip curve, which is locally safe)
    for k in range(max(1, int(m * 0.08)), int(m * 0.92)):
        x0, y0 = cs[k - 1]
        x1, y1 = cs[k]
        x2, y2 = cs[k + 1]
        r1 = math.hypot(x1 - x0, y1 - y0)
        r2 = math.hypot(x2 - x1, y2 - y1)
        if r1 < 1e-6 or r2 < 1e-6:
            continue
        cross = abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1))
        base = math.hypot(x2 - x0, y2 - y0)
        if cross < 1e-6 or base < 1e-9:
            continue
        turn_radius = r1 * r2 * base / cross
        if turn_radius < ws[k] * 0.55:
            return None
    return cs, ws


# --------------------------------------------------------------- rebuild --

def _poly_to_quadratic(poly):
    """Closed polyline -> [(x, y, on)] quadratic chain (midpoint
    construction)."""
    n = len(poly)
    out = []
    for i in range(n):
        x, y = poly[i]
        xn, yn = poly[(i + 1) % n]
        if i == 0:
            out.append(((x + xn) / 2, (y + yn) / 2, 1))
        else:
            out.append((x, y, 0))
            out.append(((x + xn) / 2, (y + yn) / 2, 1))
    return out


def _point_in_poly(x, y, poly):
    """Even-odd ray cast. poly items are (x, y, ...) tuples."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _end_flat_hidden(corner1, corner2, body_center, others, polys=None):
    """True when the flat end (corner1-corner2) is covered by another
    contour (capping it would poke through the crossing stroke).

    The bbox test alone gives false positives on large contours (a 口
    spanning half the glyph): the probe lands in its bbox although the
    ink is far away, and the flat cut is kept although the end is
    fully exposed. A bbox hit is only accepted when the cut corners
    AND the outward probe point are all inside that contour's actual
    fill (even-odd point-in-polygon)."""
    ex = (corner1[0] + corner2[0]) / 2
    ey = (corner1[1] + corner2[1]) / 2
    bx, by = body_center
    dx = ex - bx
    dy = ey - by
    L = math.hypot(dx, dy) or 1e-9
    px = ex + dx / L * 12
    py = ey + dy / L * 12
    for idx, (ox0, oy0, ox1, oy1) in enumerate(others):
        if not (ox0 - 10 <= px <= ox1 + 10 and oy0 - 10 <= py <= oy1 + 10):
            continue
        if not (ox0 - 10 <= corner1[0] <= ox1 + 10 and
                oy0 - 10 <= corner1[1] <= oy1 + 10):
            continue
        if not (ox0 - 10 <= corner2[0] <= ox1 + 10 and
                oy0 - 10 <= corner2[1] <= oy1 + 10):
            continue
        if polys is None or idx >= len(polys):
            return True  # bbox-only fallback: stay conservative
        poly = polys[idx]
        if _point_in_poly(px, py, poly) and \
           _point_in_poly(corner1[0], corner1[1], poly) and \
           _point_in_poly(corner2[0], corner2[1], poly):
            return True
    return False


def _arc_via_outward(cx, cy, r, p_from, a_out):
    """Semicircle starting at p_from (on the circle) whose sweep passes
    through direction a_out (degrees, y-up)."""
    a0 = math.degrees(math.atan2(p_from[1] - cy, p_from[0] - cx))
    rel = ((a_out - a0 + 540) % 360) - 180
    step = (180 if rel > 0 else -180)
    n = 4
    return [(cx + r * math.cos(math.radians(a0 + step * i / n)),
             cy + r * math.sin(math.radians(a0 + step * i / n)))
            for i in range(n + 1)]


def _tip_curve(P_L, d_L, tip, P_R, d_R, n=6):
    """Round a tapered tip: two quadratic Bezier segments P_L -> tip -> P_R.

    d_L / d_R are the rail directions AT the cuts pointing TOWARDS the tip.
    The curve leaves P_L tangent to d_L and arrives at P_R tangent to d_R,
    passing through the original tip point — so the taper is preserved, the
    tip position is kept, and only the sharp point is rounded. Returns the
    polyline from P_L (excluded) to P_R (included)."""
    L1 = min(max(0.5 * math.hypot(tip[0] - P_L[0], tip[1] - P_L[1]), 6.0), 20.0)
    L2 = min(max(0.5 * math.hypot(tip[0] - P_R[0], tip[1] - P_R[1]), 6.0), 20.0)
    C1 = (P_L[0] + d_L[0] * L1, P_L[1] + d_L[1] * L1)
    C2 = (P_R[0] + d_R[0] * L2, P_R[1] + d_R[1] * L2)

    def qz(p0, c, p1, t):
        u = 1 - t
        return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
                u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])

    out = []
    for i in range(1, n):
        out.append(qz(P_L, C1, tip, i / n))
    out.append(tip)
    for i in range(1, n):
        out.append(qz(tip, C2, P_R, i / n))
    out.append(P_R)
    return out


def _semicircle_head(p1, p2, outward, n=6):
    """Full semicircle head (全端半圆): a half disk with chord p1-p2
    (radius = chord/2, center = midpoint), bulging towards `outward`.
    p1/p2 are the two rail points at the cut — antipodal by construction,
    so the arc is an EXACT semicircle and joins both rails without a
    kink. Returns the chain p1 -> ... -> p2 (inclusive)."""
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    r = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / 2
    if r < 3:
        return [p1, p2]
    a1 = math.atan2(p1[1] - my, p1[0] - mx)
    a2 = math.atan2(p2[1] - my, p2[0] - mx)
    d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    if d == 0:
        d = math.pi
    a_out = math.atan2(outward[1], outward[0])
    if math.cos(a1 + d / 2 - a_out) < 0:
        d = -d
    out = [p1]
    for i in range(1, n):
        a = a1 + d * i / n
        out.append((mx + r * math.cos(a), my + r * math.sin(a)))
    out.append(p2)
    return out


def rebuild_stroke(model, center_s, widths_s, others, other_polys=None):
    """Closed outline ring (list of (x, y)) of the smoothed stroke."""
    center = center_s
    widths = widths_s
    m = len(center)

    def dir_at(k):
        if k == 0:
            dx, dy = center[1][0] - center[0][0], center[1][1] - center[0][1]
        elif k == m - 1:
            dx, dy = center[m - 1][0] - center[m - 2][0], center[m - 1][1] - center[m - 2][1]
        else:
            dx, dy = center[k + 1][0] - center[k - 1][0], center[k + 1][1] - center[k - 1][1]
        L = math.hypot(dx, dy) or 1e-9
        return dx / L, dy / L

    left, right = [], []
    rail_p, rail_q = model["rail_p"], model["rail_q"]
    cen_o = model["center"]

    # offset direction = original edge direction (centerline -> rail
    # point): tracks the true edge orientation, which differs from the
    # travel normal on curved edges (teardrop dots, flares) and must stay
    # raw near the tips (the rails converge there; a wide window would
    # lag the curvature and deflect the tip curve). A single wobbly
    # sample whose original centerline crossed to the other side flips
    # its direction ~180 deg and spikes the rail into the body
    # (self-intersection), so ONLY samples with a local reversal are
    # replaced by their window average (the healthy neighbours dominate).
    def edge_dirs(rail, side, zone_a=None, zone_b=None):
        # zone_a: cap zone [0, zone_a] at the start tip; zone_b: cap zone
        # [zone_b, m-1] at the end tip. A rounded end (cap) makes the
        # pairing ride the cap arc, where the axis->rail normals rotate
        # up to ~90 degrees. Without clipping, the window-smoothed
        # normals of the body samples next to the junction get dragged
        # along, the head chord [left[k], right[k]] skews and shrinks,
        # and the rebuilt semicircle head cuts into the original cap
        # (a notch at the 收笔). Inside the cap zone use the exact axis
        # normal (the rail there IS the cap arc: center + normal*w/2
        # reproduces it); the window never crosses the zone boundary.
        raw = []
        for k in range(m):
            ox, oy = cen_o[k]
            px, py = rail[k]
            dl = math.hypot(px - ox, py - oy)
            raw.append(((px - ox) / dl, (py - oy) / dl) if dl >= 1.0 else None)
        half = max(2, m // 12)

        def win(k, lo, hi):
            sx = sy = 0.0
            c = 0
            for j in range(max(0, lo), min(m, hi)):
                if raw[j] is None:
                    continue
                sx += raw[j][0]
                sy += raw[j][1]
                c += 1
            if c == 0:
                return None
            L = math.hypot(sx, sy)
            return (sx / L, sy / L) if L >= 0.5 else None

        def axis_normal(k, side):
            d = dir_at(k)
            n = (-d[1], d[0])
            return (n[0] * side, n[1] * side)

        out = []
        for k in range(m):
            in_cap = ((zone_a is not None and k <= zone_a) or
                      (zone_b is not None and k >= zone_b))
            if in_cap:
                out.append(axis_normal(k, side))
                continue
            lo = max(0, k - half, (zone_a + 1) if zone_a is not None else 0)
            hi = min(m, k + half + 1, zone_b if zone_b is not None else m)
            v = raw[k]
            if v is not None:
                pv = raw[k - 1] if k > 0 else None
                nv = raw[k + 1] if k < m - 1 else None
                flip = (pv is not None and
                        v[0] * pv[0] + v[1] * pv[1] < 0) or \
                       (nv is not None and
                        v[0] * nv[0] + v[1] * nv[1] < 0)
                if not flip:
                    out.append(v)
                    continue
            w = win(k, lo, hi)
            out.append(w if w is not None else axis_normal(k, side))
        return out

    # 全端半圆 cut indices (before the rails are built: the rail
    # normals in the cap zone depend on the cap boundaries). Where the
    # (smoothed) width narrows to W_head, the tapered tip is cut and
    # replaced by a FULL semicircle head — the calligraphic taper is
    # kept up to the cut, then a true round head (no pointed 收笔, no
    # fat tip blob).
    W_head = max(26.0, min(46.0, 0.5 * model["med"]))
    kA = m - 1
    for kk in range(m):
        if widths[kk] >= W_head:
            kA = kk
            break
    kB = 0
    for kk in range(m - 1, -1, -1):
        if widths[kk] >= W_head:
            kB = kk
            break

    # Capped ends read back as 'taper': round-terminals (or the source)
    # ends the stroke in a semicircle, and the pairing then converges
    # to the cap apex like a tip. Signature: the width reaches ~full
    # within a few samples of the tip (a true calligraphic taper ramps
    # slowly). A fillet on such an end degenerates into a squiggle at
    # the apex (the rail endpoints sit on top of the tip), so rebuild
    # the cap instead: a FULL semicircle at the cap-rail junction.
    def cap_junction():
        # Junction of the 收笔 end and the body = the LOCAL MAXIMUM of
        # the width ramp from the tip. Covers every kind of blunt end:
        # a semicircular cap (the max is the cap-rail tangent points),
        # a shallow V / blunt cut (the max is the V base), and a
        # calligraphic taper (the max is the taper's foot). Past the
        # junction the pairing converges toward the tip and its
        # normals rotate, so the rails there are rebuilt from the exact
        # axis normal and the FULL semicircle head sits on the chord
        # [left[j], right[j]] (width = the local full width, which can
        # be NARROWER than med on a tapered stroke). The ramp must
        # exist (2-30 samples); a degenerate tip keeps the fillet.
        if m < 8:
            return None
        j = m - 2
        for kk in range(m - 2, 0, -1):
            if widths[kk] >= widths[kk - 1] - 2.0:
                j = kk
                break
        ramp = m - 1 - j
        if not (2 <= ramp <= 30):
            return None
        # A semicircular cap extends axially ~ w/2 (its radius) past the
        # junction. A blunt tip that extends further (the 捺's shallow
        # pointed end: ~1.3x w/2) is a POINTED taper: a semicircle head
        # there ends short of the original tip and cuts inside the
        # silhouette (a notch) — keep the taper and round only the very
        # point (the fillet).
        if ramp * 8.0 > 1.15 * widths[j] / 2.0:
            return None
        return j

    both_heads = (kA < m - 2 and kB > 1 and kB - kA >= 3)

    # 收笔 (the end tip) of a tapered stroke is always rebuilt as a
    # FULL semicircle at the junction (全端半圆: no pointed 收笔): a
    # rounded cap, a shallow V / blunt cut, or a calligraphic taper all
    # converge past the local width maximum. The start tip keeps the
    # source entry (both_heads bars get their head at kA; other tapers
    # keep the small fillet).
    capB = (None if model["end_b"][0] != 'taper' else cap_junction())

    # Cap zone for the rail normals: past the junction the pairing
    # converges toward the tip and its normals rotate up to ~90
    # degrees; without clipping, the window-smoothed normals of the
    # body samples next to the junction get dragged along, the head
    # chord [left[k], right[k]] skews and shrinks, and the rebuilt
    # semicircle cuts into the original end (a notch at the 收笔).
    ldirs = edge_dirs(rail_p, +1, None, capB)
    rdirs = edge_dirs(rail_q, -1, None, capB)
    for k in range(m):
        dx, dy = dir_at(k)
        nx, ny = -dy, dx
        w2 = widths[k] / 2
        ld = ldirs[k] if ldirs[k] is not None else (nx, ny)
        rd = rdirs[k] if rdirs[k] is not None else (-nx, -ny)
        lx, ly = ld
        rx, ry = rd
        left.append((center[k][0] + lx * w2, center[k][1] + ly * w2))
        right.append((center[k][0] + rx * w2, center[k][1] + ry * w2))

    # rails must keep exactly m points so the 全端半圆 cut indices
    # (kA/kB, defined on the centerline) index the rails correctly
    left = _resample_open(left, m - 1)
    right = _resample_open(right, m - 1)

    # the rail positions inherit a 1-sample wobble: the raw edge direction
    # is polluted where the ORIGINAL centerline crosses itself at a wobble
    # peak, which spikes the offset point 2-7u into the neighbouring
    # rail segment (micro self-intersection, invisible to the eye but a
    # kink in the outline). A light [1,2,1]/4 box over the interiors
    # kills it; the very ends are left untouched (the tip curves and
    # heads anchor on left[0]/left[-1] etc.) and the slow flare profile
    # (many samples) survives.
    #
    # BLUNT strokes skip this full-rail pass: a raw edge-direction flip
    # in the blunt tip zone spikes a garbage sample 20-120u away, and
    # the [1,2,1] window at the handoff boundary would pull the first
    # retained sample towards the spike -- the junction then folds
    # back on the arc's last segment (a local self-crossing). Blunt
    # rails are box-passed inside the blunt block instead, with the
    # tip zones and handoff boundaries excluded from the windows.
    ea_b = model["end_a"][0] == 'blunt'
    eb_b = model["end_b"][0] == 'blunt'
    if not (ea_b or eb_b):
        for rail in (left, right):
            for _ in range(2):
                newl = list(rail)
                for k in range(1, len(rail) - 1):
                    ax, ay = rail[k - 1]
                    bx, by = rail[k]
                    cx, cy = rail[k + 1]
                    newl[k] = ((ax + 2 * bx + cx) / 4, (ay + 2 * by + cy) / 4)
                rail[:] = newl

    # ---------------- blunt-end splicing ----------------
    # 'blunt' ends keep the ORIGINAL edge: the tip arc, extended along
    # the original chain up to the handoff with the rebuilt rail. The
    # handoff is the first (from the tip) synthetic-rail sample that is
    # (a) on the BODY side of the cut, (b) within 6u of the original
    # edge, and (c) continuous with its rail neighbour (no >20u jump --
    # a raw edge-direction flip at the tip zone spikes the offset point
    # across the stroke; such samples are part of the garbage tip zone
    # and stay covered by the original arc).
    #
    # Between the two handoffs the rail is the smoothed synthetic rail
    # (the wobble smoothing of this op). When the pairing stays crossed
    # (a fork V) so that no handoff is found, the original arcs cover
    # the whole ring: with both ends blunt the chains are split at the
    # midpoint and the rails are empty -- the ring IS the original
    # edge, every point exactly once.
    i0L = i0R = 0
    i1L = i1R = m - 1
    d1, d2 = model["d1"], model["d2"]
    m1, m2 = len(d1), len(d2)
    JUMP = 20.0

    def _nearest(pt, chain):
        best, bd = 0, 1e18
        for i, q in enumerate(chain):
            dd = (q[0] - pt[0]) ** 2 + (q[1] - pt[1]) ** 2
            if dd < bd:
                bd, best = dd, i
        return best, math.sqrt(bd)

    def _side_sign(rail):
        """Sign of (travel x (rail - center)) at a healthy mid-stroke
        sample: identifies this rail's own side of the centerline."""
        k = m // 2
        ox, oy = center[k]
        tx = center[k + 1][0] - center[k - 1][0]
        ty = center[k + 1][1] - center[k - 1][1]
        cr = tx * (rail[k][1] - oy) - ty * (rail[k][0] - ox)
        return 1.0 if cr > 0 else -1.0

    sideL = _side_sign(left)
    sideR = _side_sign(right)

    def _handoff(rail, chain, cut, body_gt, k0, step, side, kmin, kmax):
        """First sample k (from k0, every step) whose synthetic position
        is (a) OUTSIDE the tip zone (kmin..kmax = the width-based
        cut bounds kA/kB: inside a tip zone the pairing converges to
        the tip and the idx test is meaningless -- a scrambled tip
        pairing puts even the tip sample itself "body-side" and the
        handoff would land ON THE TIP, double-traversing the cap),
        (b) on this rail's OWN side of the centerline (a flipped
        offset lands on the far-side edge and would double-traverse
        it), (c) body-side of the chain cut, (d) within 6u of the
        edge, and (e) continuous with the rail neighbour towards the
        body; None when none of the first 40 qualifies (the tip zone
        then swallows k0..k0+39 and the arc covers it)."""
        for off in range(0, 41):
            k = k0 + step * off
            if not (0 <= k < m):
                return None
            if k < kmin or k > kmax:
                continue
            # own side of the centerline (a raw edge-direction flip
            # rotates the offset across the stroke; the point still
            # sits ON the far-side edge, so only the side test sees it)
            ox, oy = center[k]
            if k == 0:
                tx = center[1][0] - center[0][0]
                ty = center[1][1] - center[0][1]
            elif k == m - 1:
                tx = center[m - 1][0] - center[m - 2][0]
                ty = center[m - 1][1] - center[m - 2][1]
            else:
                tx = center[k + 1][0] - center[k - 1][0]
                ty = center[k + 1][1] - center[k - 1][1]
            cr = tx * (rail[k][1] - oy) - ty * (rail[k][0] - ox)
            if abs(cr) >= 1.0 and cr * side < 0:
                continue
            # continuity with the rail neighbour towards the BODY (the
            # direction the ring continues): a >JUMP gap means this
            # sample sits on the garbage tip-zone boundary
            nb = k + step
            if 0 <= nb < m and math.hypot(rail[k][0] - rail[nb][0],
                                           rail[k][1] - rail[nb][1]) > JUMP:
                continue
            idx, dist = _nearest(rail[k], chain)
            body = (idx > cut) if body_gt else (idx < cut)
            if body and dist <= 6.0:
                return k
        return None

    end_a = model["end_a"]
    end_b = model["end_b"]
    ea_b = end_a[0] == 'blunt'
    eb_b = end_b[0] == 'blunt'

    # handoffs on each rail; a missing handoff keeps the full tip zone
    # (k0..k0+39) inside the original arc
    # fallbacks stay inside the body zone [kA, kB] (a fallback inside
    # a tip zone is a garbage-zone sample, same class of mistake);
    # when no body zone exists (kA >= kB: the whole stroke is tip
    # zones) the rails are forced empty and the arcs cover everything
    if ea_b:
        if kA < kB:
            i0L = _handoff(left, d1, end_a[3], True, 0, +1, sideL, kA, kB)
            i0L = i0L if i0L is not None else min(max(40, kA), kB)
            i0R = _handoff(right, d2, end_a[4], False, 0, +1, sideR, kA, kB)
            i0R = i0R if i0R is not None else min(max(40, kA), kB)
        else:
            i0L = i0R = m // 2 + 1
    if eb_b:
        if kA < kB:
            i1L = _handoff(left, d1, end_b[3], False, m - 1, -1, sideL, kA, kB)
            i1L = i1L if i1L is not None else max(min(m - 1 - 40, kB), kA)
            i1R = _handoff(right, d2, end_b[4], True, m - 1, -1, sideR, kA, kB)
            i1R = i1R if i1R is not None else max(min(m - 1 - 40, kB), kA)
        else:
            i1L = i1R = m // 2

    # where the arcs hand off to the rails, in chain-index terms
    idx_i0L = _nearest(left[i0L], d1)[0] if ea_b else 0
    idx_i1L = _nearest(left[i1L], d1)[0] if eb_b else m1 - 1
    idx_i0R = _nearest(right[i0R], d2)[0] if ea_b else m2 - 1
    idx_i1R = _nearest(right[i1R], d2)[0] if eb_b else 0
    # both-blunt overlap guard: the two arcs must not share a chain
    # point (a double traversal is a self-touch). Split at the midpoint
    # and empty the rails (the original edge then IS the ring).
    if ea_b and eb_b:
        if idx_i0L >= idx_i1L - 1 or idx_i1R + 1 <= idx_i0R:
            s1 = max(1, (idx_i0L + idx_i1L) // 2)
            s2 = max(1, (idx_i0R + idx_i1R) // 2)
            idx_i0L, idx_i1L = s1, s1
            idx_i0R, idx_i1R = s2, s2
            i0L, i1L = i1L + 1, i1L      # empty left rail
            i0R, i1R = i1R + 1, i1R      # empty right rail

    # empty-rail clamp: when a handoff was never found, the fallback
    # index is a GARBAGE-ZONE sample whose pairing does not match the
    # (empty) rail; the arc must not extend to that idx -- it would
    # double-traverse the edge and close with a long chord that
    # crosses the arc. Clamp the arc's d-side start to the other
    # end's handoff (the shared point dedupes away): the original
    # edge then spans the body side it was never remapped from, and
    # that is clean.
    if ea_b and eb_b:
        if i0R > i1R:
            idx_i0R = idx_i1R
        if i0L > i1L:
            idx_i0L = idx_i1L

    if ea_b:
        # tip = d1[0] = d2[-1]; arc in RING order: right handoff ->
        # tip -> left handoff
        arc_a = list(d2[idx_i0R:m2]) + list(d1[1:idx_i0L + 1])
        end_a = ('blunt', end_a[1], arc_a, end_a[3], end_a[4])
    if eb_b:
        # tip = d1[-1] = d2[0]; arc in RING order: left handoff ->
        # tip -> right handoff
        arc_b = list(d1[idx_i1L:m1]) + list(d2[1:idx_i1R + 1])
        end_b = ('blunt', end_b[1], arc_b, end_b[3], end_b[4])

    # the rails were rebuilt from the smoothed centerline - one light
    # box pass (the same [1,2,1]/4 as above) removes the residual
    # 1-2u wobble so the handoff with the ORIGINAL-edge arc is as clean
    # as the edge itself. Handoff points are re-anchored afterwards
    # (a hard anchor only when the synthetic sample already sits on the
    # edge within 3u; otherwise the short chord seam is left as-is --
    # pulling a far sample onto the arc kinks the outline).
    for rail, b0, b1 in ((left, i0L if ea_b else None, i1L if eb_b else None),
                         (right, i0R if ea_b else None, i1R if eb_b else None)):
        for _ in range(2):
            newl = list(rail)
            for k in range(1, len(rail) - 1):
                if b0 is not None and k <= b0:
                    continue  # start-side tip zone + handoff boundary
                if b1 is not None and k >= b1:
                    continue  # end-side tip zone + handoff boundary
                ax, ay = rail[k - 1]
                bx, by = rail[k]
                cx, cy = rail[k + 1]
                newl[k] = ((ax + 2 * bx + cx) / 4, (ay + 2 * by + cy) / 4)
            rail[:] = newl
    # a raw edge-direction flip (the ORIGINAL centerline crossing
    # itself at a wobble peak) can spike an offset point across the
    # stroke; a multi-sample flip survives the window-smoothed
    # directions and leaves a 30-45u jump in the rail. Left in the
    # ring, the chord back across the tip arc self-touches. Replace
    # jumped samples by the midpoint of their neighbours (iterated, so
    # a garbage RUN converges onto the healthy edge): the ring then
    # passes the garbage zone as short chords that can't cross the
    # arc bulging outside them. The handoff samples themselves are
    # never touched: their tip-side neighbour is the garbage zone
    # (always far away) and moving a handoff would open a long chord
    # seam with the arc it anchors to.
    boundary = set()
    if ea_b:
        boundary.update((i0L, i0R))
    if eb_b:
        boundary.update((i1L, i1R))
    for rail in (left, right):
        for _ in range(3):
            changed = False
            for k in range(1, len(rail) - 1):
                if k in boundary:
                    continue
                if math.hypot(rail[k][0] - rail[k - 1][0],
                              rail[k][1] - rail[k - 1][1]) > JUMP or \
                   math.hypot(rail[k][0] - rail[k + 1][0],
                              rail[k][1] - rail[k + 1][1]) > JUMP:
                    rail[k] = ((rail[k - 1][0] + rail[k + 1][0]) / 2,
                               (rail[k - 1][1] + rail[k + 1][1]) / 2)
                    changed = True
            if not changed:
                break
    if ea_b:
        if i0L < m and math.hypot(left[i0L][0] - d1[idx_i0L][0],
                                  left[i0L][1] - d1[idx_i0L][1]) <= 3.0:
            left[i0L] = d1[idx_i0L]
        if i0R < m and math.hypot(right[i0R][0] - d2[idx_i0R][0],
                                  right[i0R][1] - d2[idx_i0R][1]) <= 3.0:
            right[i0R] = d2[idx_i0R]
    if eb_b:
        if i1L >= 0 and math.hypot(left[i1L][0] - d1[idx_i1L][0],
                                   left[i1L][1] - d1[idx_i1L][1]) <= 3.0:
            left[i1L] = d1[idx_i1L]
        if i1R >= 0 and math.hypot(right[i1R][0] - d2[idx_i1R][0],
                                   right[i1R][1] - d2[idx_i1R][1]) <= 3.0:
            right[i1R] = d2[idx_i1R]


    # inner-rail hairpin pre-filter: at a tight bend the inner rail
    # radius can drop below the resample step and the polyline folds
    # back on itself (a micro self-intersection). A hairpin shows up as
    # a direction reversal inside a 15u span (a clean corner of radius
    # >= 15u needs a pi*R >= 47u arc for a half turn, so it can never
    # reverse inside the window). Plain valleys (U-shaped, no crossing)
    # also reverse, so this only gates an exact self-intersection test
    # on the finished ring — a valley passes that test and is kept.
    def _uturn(rail):
        n = len(rail)
        for k in range(2, n - 2):
            a = rail[k - 2]
            span = max(math.hypot(rail[k - 1][0] - a[0], rail[k - 1][1] - a[1]),
                       math.hypot(rail[k][0] - a[0], rail[k][1] - a[1]),
                       math.hypot(rail[k + 1][0] - a[0], rail[k + 1][1] - a[1]))
            if span > 15:
                continue
            v1 = (rail[k - 1][0] - a[0], rail[k - 1][1] - a[1])
            v2 = (rail[k + 1][0] - rail[k][0], rail[k + 1][1] - rail[k][1])
            l1 = math.hypot(v1[0], v1[1])
            l2 = math.hypot(v2[0], v2[1])
            if l1 < 1e-6 or l2 < 1e-6:
                continue
            if (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2) < -0.2:
                return True
        return False

    dx0, dy0 = dir_at(0)
    dx1, dy1 = dir_at(m - 1)

    def flat_head(corner1, corner2, k, sign, ref):
        """全端半圆 for a visible flat cut: a FULL semicircle on the cut
        edge itself (chord = the two corners, center = their midpoint),
        bulging away from the body. sign -1 at the start end (the arc
        must end at the left rail's first point), +1 at the end end
        (the arc must start at the left rail's last point). `ref` is the
        left rail point the arc joins. Returns the arc chain.

        (The old approach projected the centerline out to the cut edge;
        when the cut runs oblique to the stroke that projection lands
        far inside the body and the arc crosses the rails.)"""
        ex, ey = corner2[0] - corner1[0], corner2[1] - corner1[1]
        Le = math.hypot(ex, ey) or 1e-9
        e = (ex / Le, ey / Le)
        n1 = (-e[1], e[0])
        d = dir_at(k)
        dot = n1[0] * d[0] + n1[1] * d[1]
        if (dot > 0) != (sign > 0):
            n1 = (-n1[0], -n1[1])
        if math.hypot(corner1[0] - ref[0], corner1[1] - ref[1]) <= \
           math.hypot(corner2[0] - ref[0], corner2[1] - ref[1]):
            Lc, Rc = corner1, corner2
        else:
            Lc, Rc = corner2, corner1
        if sign < 0:
            return _semicircle_head(Rc, Lc, n1)
        return _semicircle_head(Lc, Rc, n1)

    def unit(p, q):
        dx, dy = p[0] - q[0], p[1] - q[1]
        L = math.hypot(dx, dy) or 1e-9
        return dx / L, dy / L

    ring = []

    # ---------------- start end ----------------
    if end_a[0] == 'blunt':
        # 宽钝端: the original tip arc (cutR -> tip -> cutL)
        ring += end_a[2]
    elif end_a[0] == 'flat':
        c1, c2 = end_a[1], end_a[2]
        hidden = _end_flat_hidden(c1, c2, center[1], others, other_polys)
        if hidden:
            # keep the original cut corners exactly (hidden under the
            # crossing stroke; any rebuilt geometry would be invisible
            # anyway, and the originals can't shift the end position).
            # Order the corners by RAIL proximity, not by travel normal:
            # the left rail sits on whichever normal side the ring
            # winding puts it, and a swapped order walks the cut edge
            # back and forth (the outline traverses it 3 times).
            if math.hypot(c1[0] - left[0][0], c1[1] - left[0][1]) <= \
               math.hypot(c2[0] - left[0][0], c2[1] - left[0][1]):
                L, R = c1, c2
            else:
                L, R = c2, c1
            ring += [R, L]
        else:
            ring += flat_head(c1, c2, 0, -1, left[0])
    elif both_heads:
        ring += _semicircle_head(right[kA], left[kA], (-dx0, -dy0))
    else:
        d_L = unit(left[0], left[1])
        d_R = unit(right[0], right[1])
        ring += _tip_curve(right[0], d_R, end_a[1], left[0], d_L)

    # ---------------- body: left rail ----------------
    # ring order must be start-cap -> left rail -> end-cap -> right rail
    # (a simple loop); the end cap belongs BETWEEN the two rails
    if end_a[0] == 'taper':
        i0 = (kA + 1) if both_heads else 1
    else:
        i0 = 0
    if end_b[0] == 'taper':
        i1 = capB if capB is not None else (kB if both_heads else m - 2)
    else:
        i1 = m - 1
    if i0 > i1:
        i0, i1 = 0, m - 1
    if end_a[0] != 'blunt':
        i0L = i0R = i0
    if end_b[0] != 'blunt':
        i1L = i1R = i1
    # A blunt end's rail range may legitimately be empty (the cap arcs
    # then cover the whole ring) -- only reset for non-blunt conflicts
    # (overlapping taper cap zones).
    if not (ea_b or eb_b):
        if i0L > i1L:
            i0L, i1L = 0, m - 1
        if i0R > i1R:
            i0R, i1R = 0, m - 1
    ring += list(left[i0L:i1L + 1])

    # ---------------- end end ----------------
    if end_b[0] == 'blunt':
        # 宽钝端: the original tip arc (cutL -> tip -> cutR)
        ring += end_b[2]
    elif end_b[0] == 'flat':
        c1, c2 = end_b[1], end_b[2]
        hidden = _end_flat_hidden(c1, c2, center[m - 2], others, other_polys)
        if hidden:
            if math.hypot(c1[0] - left[m - 1][0], c1[1] - left[m - 1][1]) <= \
               math.hypot(c2[0] - left[m - 1][0], c2[1] - left[m - 1][1]):
                L, R = c1, c2
            else:
                L, R = c2, c1
            ring += [L, R]
        else:
            ring += flat_head(c1, c2, m - 1, +1, left[m - 1])
    elif capB is not None:
        # 收笔: full semicircle at the junction (local width maximum)
        ring += _semicircle_head(left[capB], right[capB], (dx1, dy1))
    elif both_heads:
        ring += _semicircle_head(left[kB], right[kB], (dx1, dy1))
    else:
        d_L = unit(left[-1], left[-2])
        d_R = unit(right[-1], right[-2])
        ring += _tip_curve(left[-1], d_L, end_b[1], right[-1], d_R)

    ring += list(reversed(right[i0R:i1R + 1]))

    # chamfer sharp corners: the hidden flat cut end meets a rail at
    # ~90 degrees, and the midpoint-quadratic conversion of such a
    # corner bulges both side curves past the corner point, so the
    # flattened (int-stored) outline backtracks on itself by ~1u
    # (a micro self-touch). Cutting the corner by 6u makes each side
    # a <= 45-degree turn. Only sharp corners exist at hidden cut ends
    # (tips and heads are arcs, turning <= ~30 degrees per segment),
    # and the chamfer sits under the crossing stroke — invisible.
    def chamfer(ring_pts):
        n = len(ring_pts)
        out = []
        for i in range(n):
            p = ring_pts[i]
            prev = ring_pts[i - 1]
            nxt = ring_pts[(i + 1) % n]
            v1 = (p[0] - prev[0], p[1] - prev[1])
            v2 = (nxt[0] - p[0], nxt[1] - p[1])
            l1 = math.hypot(v1[0], v1[1])
            l2 = math.hypot(v2[0], v2[1])
            if l1 < 1e-6 or l2 < 1e-6:
                out.append(p)
                continue
            cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
            if cos >= 0.25:  # turn < ~75 degrees: keep the corner
                out.append(p)
                continue
            d = min(6.0, 0.5 * l1, 0.5 * l2)
            out.append((p[0] - v1[0] / l1 * d, p[1] - v1[1] / l1 * d))
            out.append((p[0] + v2[0] / l2 * d, p[1] + v2[1] / l2 * d))
        return out

    out_ring = []
    for p in ring:
        if not out_ring or math.hypot(p[0] - out_ring[-1][0],
                                      p[1] - out_ring[-1][1]) > 0.01:
            out_ring.append(p)
    if len(out_ring) > 2 and math.hypot(out_ring[0][0] - out_ring[-1][0],
                                        out_ring[0][1] - out_ring[-1][1]) < 0.01:
        out_ring.pop()
    # chamfer AFTER dedup: duplicate corner points (rail end == cut
    # corner) would create zero-length edges and skip the chamfer
    out_ring = chamfer(out_ring)
    # the hairpin pre-filter (valleys included) gates the exact test:
    # a ring that actually self-intersects is worse than no rebuild
    # exact self-intersection gate: a rebuilt ring that self-touches is
    # worse than no rebuild at all (the original contour is kept). The
    # old _uturn pre-filter was tuned to a smaller resample step and
    # never fired at the 8u step (a 4-sample window always spans
    # > 15u); the exact test on <= ~300 points, bbox pre-filtered, is
    # fast enough to run on every reconstructed contour.
    if _ring_self_intersects(out_ring):
        return None
    return out_ring


def _ring_self_intersects(ring):
    """Exact non-adjacent segment intersection test on a closed ring."""
    n = len(ring)
    if n < 5:
        return False
    for i in range(n):
        p1 = ring[i]
        p2 = ring[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            p3 = ring[j]
            p4 = ring[(j + 1) % n]
            if max(p1[0], p2[0]) + 1 < min(p3[0], p4[0]) or \
               max(p3[0], p4[0]) + 1 < min(p1[0], p2[0]) or \
               max(p1[1], p2[1]) + 1 < min(p3[1], p4[1]) or \
               max(p3[1], p4[1]) + 1 < min(p1[1], p2[1]):
                continue
            if _segments_cross(p1, p2, p3, p4):
                return True
    return False


def _segments_cross(p1, p2, p3, p4):
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)
    return ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))


def smooth_contour(points, other_bboxes, other_polys=None):
    """Full pipeline for one contour. Returns a new [(x, y, on)] contour,
    or None when the contour is not a smoothable thin stroke (or the
    rebuilt geometry fails the sanity check)."""
    ring = [(x, y) for (x, y, on) in points]
    dense = resample_ring(ring, 8.0)
    model = extract_stroke(dense)
    if model is None:
        return None
    sm = smooth_centerline(model["center"], model["widths"])
    if sm is None:
        return None
    ring2 = rebuild_stroke(model, sm[0], sm[1], other_bboxes, other_polys)
    if ring2 is None or len(ring2) < 12:
        return None
    ob = _bbox(ring)
    nb = _bbox(ring2)
    if (nb[0] < ob[0] - 200 or nb[1] < ob[1] - 200 or
            nb[2] > ob[2] + 200 or nb[3] > ob[3] + 200 or
            nb[0] > ob[0] + 200 or nb[1] > ob[1] + 200 or
            nb[2] < ob[2] - 200 or nb[3] < ob[3] - 200):
        return None
    # no edge may retreat grossly (wobble smoothing removes up to the
    # wobble amplitude; a large retreat means the rails lost the edge).
    # 40u: wobble bulges in this font reach ~30u and they must go (that
    # IS the smoothing); a rail that truly loses the edge retreats by
    # >= w/2 = 36u (to the centerline) or w (across), so 40u stays
    # below the collapse cases with margin.
    if (nb[0] > ob[0] + 40 or nb[1] > ob[1] + 40 or
            nb[2] < ob[2] - 40 or nb[3] < ob[3] - 40):
        return None
    # contact edges: a bbox edge that sits on (or within 6u of) another
    # contour's edge must not open a gap (a dot resting on a bar, a stem
    # meeting a roof) — at most 6u of movement (0.24px at 40pt, invisible;
    # a real contact pushed open by >= 6u is still rejected). The 10u/3u
    # version tripped on wobble bulges that merely NEAR-miss an edge by
    # 4u (no visible contact, and the gap after smoothing is sub-pixel).
    for (ox0, oy0, ox1, oy1) in other_bboxes:
        if abs(ob[1] - oy1) <= 6 and nb[1] > ob[1] + 6:
            return None
        if abs(ob[3] - oy0) <= 6 and nb[3] < ob[3] - 6:
            return None
        if abs(ob[2] - ox0) <= 6 and nb[2] < ob[2] - 6:
            return None
        if abs(ob[0] - ox1) <= 6 and nb[0] > ob[0] + 6:
            return None
    a1, a2 = _area(ring), _area(ring2)
    if a1 < 1 or not (0.4 <= a2 / a1 <= 2.5):
        return None
    return _poly_to_quadratic(ring2)


def _bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2
