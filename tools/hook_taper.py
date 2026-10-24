"""按根线（骨架）去钩：把钩顺成捺，不剪断接圆头。

思路
----
主人画的线稿是字形的**根线**（骨架）。钩的毛病不在轮廓，在根线末端那一段回卷；
所以处理也在根线上做：

1. 栅格化取骨架 + 距离变换；钩的位置用 `hook_erase.find_hooks`（骨架判据，在 Maruko 上
   验证过：`乙`2、`了`/`子`/`也`/`九`/`電` 各 1，对照组 `十`/`口`/`大` 全 0）。
2. 在钩根处的骨架上，取**背离钩**的笔身方向 d，以及沿笔身的真实半笔宽 r（距离变换取
   若干点的中位数，不是全局常数）。
3. 过钩根、垂直于 d 的直线与轮廓求交，得到两个切口端点；它们天然落在轮廓上，
   不用拿原有顶点凑，所以不留缝。
4. 从两个端点各拉一条三次贝塞尔到轴线上，**起点切线直接取轮廓在该点的切线**（G1 连续），
   末端汇到一个小圆头（半径 0.28r）——这就是捺尖。
5. 曲线用 de Casteljau 精确分裂，不展平、不重采样。

用法：
    python3 tools/hook_taper.py 输入.ttf 输出.ttf --chars 九气也
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from scipy import ndimage
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_cut import split_contours  # noqa: E402
from hook_erase import find_hooks as raster_hooks  # noqa: E402
from stroke_width_normalize_prototype import raster_mask  # noqa: E402

SAMPLE = 32
TIP_RATIO = 0.28      # 捺尖圆头半径 / 半笔宽
REACH = 1.9           # 捺尖长度 / 半笔宽


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _side(p, origin, direction):
    return _cross((p[0] - origin[0], p[1] - origin[1]), direction)


def _norm(v):
    d = math.hypot(*v) or 1.0
    return (v[0] / d, v[1] / d)


def segments_of(contour):
    n = len(contour)
    on_idx = [i for i in range(n) if contour[i][2]]
    if not on_idx:
        return []
    segs = []
    for k, i in enumerate(on_idx):
        j = on_idx[(k + 1) % len(on_idx)]
        p0 = (contour[i][0], contour[i][1])
        p1 = (contour[j][0], contour[j][1])
        offs = []
        m = (i + 1) % n
        while m != j:
            offs.append((contour[m][0], contour[m][1]))
            m = (m + 1) % n
        if not offs:
            segs.append(("line", p0, [], p1, i, j))
        else:
            pts = [p0] + offs + [p1]
            for t in range(len(pts) - 2):
                a, c, b = pts[t], pts[t + 1], pts[t + 2]
                if t + 2 < len(pts) - 1:
                    mid = ((c[0] + b[0]) / 2, (c[1] + b[1]) / 2)
                    segs.append(("quad", a, [c], mid, i, -1))
                else:
                    segs.append(("quad", a, [c], b, i, j))
    return segs


def _quad_at(p0, c, p1, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
            u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])


def _quad_tangent(p0, c, p1, t):
    u = 1 - t
    return _norm((2 * u * (c[0] - p0[0]) + 2 * t * (p1[0] - c[0]),
                  2 * u * (c[1] - p0[1]) + 2 * t * (p1[1] - c[1])))


def _split_quad(p0, c, p1, t):
    a = (p0[0] + (c[0] - p0[0]) * t, p0[1] + (c[1] - p0[1]) * t)
    b = (c[0] + (p1[0] - c[0]) * t, c[1] + (p1[1] - c[1]) * t)
    m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return (p0, a, m), (m, b, p1)


def tangent_of(contour, seg_index, t):
    kind, p0, ctrls, p1, _i, _j = segments_of(contour)[seg_index]
    if kind == "line":
        return _norm((p1[0] - p0[0], p1[1] - p0[1]))
    return _quad_tangent(p0, ctrls[0], p1, t)


def cut_points(contour, origin, direction):
    """轮廓（含曲线）与直线的交点：[(距离, 段号, t, 点)]。"""
    hits = []
    for si, (kind, p0, ctrls, p1, _i, _j) in enumerate(segments_of(contour)):
        if kind == "line":
            e = (p1[0] - p0[0], p1[1] - p0[1])
            den = _cross(e, direction)
            if abs(den) < 1e-12:
                continue
            w = (origin[0] - p0[0], origin[1] - p0[1])
            t = _cross(w, direction) / den
            s = _cross(w, e) / den
            if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= s <= 1 + 1e-9:
                pt = (p0[0] + e[0] * t, p0[1] + e[1] * t)
                hits.append((_dist(pt, origin), si, t, pt))
            continue
        c = ctrls[0]
        prev = _quad_at(p0, c, p1, 0.0)
        prev_s = _side(prev, origin, direction)
        for k in range(1, SAMPLE + 1):
            t = k / SAMPLE
            pt = _quad_at(p0, c, p1, t)
            s = _side(pt, origin, direction)
            if prev_s == 0 or s == 0 or (s > 0) != (prev_s > 0):
                lo, hi = (k - 1) / SAMPLE, t
                for _ in range(48):
                    mid = (lo + hi) / 2
                    if (_side(_quad_at(p0, c, p1, mid), origin, direction) > 0) == (prev_s > 0):
                        lo = mid
                    else:
                        hi = mid
                tt = (lo + hi) / 2
                hits.append((_dist(_quad_at(p0, c, p1, tt), origin), si, tt,
                             _quad_at(p0, c, p1, tt)))
                break
            prev, prev_s = pt, s
    return hits


def insert_point(contour, seg_index, t):
    """在指定段的参数 t 处插入 on-curve 点，返回 (新轮廓, 新点下标)。"""
    kind, p0, ctrls, p1, i, j = segments_of(contour)[seg_index]
    if kind == "line":
        mid = (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
        at = (i + 1) % len(contour)
        if at == 0:
            contour.append((mid[0], mid[1], True))
            return contour, len(contour) - 1
        contour.insert(at, (mid[0], mid[1], True))
        return contour, at
    left, right = _split_quad(p0, ctrls[0], p1, t)
    at = (i + 1) % len(contour)
    new = [(left[1][0], left[1][1], False), (left[2][0], left[2][1], True),
           (right[1][0], right[1][1], False)]
    if at == 0:
        contour.extend(new)
        return contour, len(contour) - 2
    for k, pt in enumerate(new):
        contour.insert(at + k, pt)
    return contour, at + 1


def semicircle_quads(center, start, end, axis, radius, quads=2):
    """start → end 绕 axis 一侧的半圆，用 quads 段二次贝塞尔。"""
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    at = math.atan2(axis[1], axis[0])
    d1 = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    dt = (at - a0 + math.pi) % (2 * math.pi) - math.pi
    if d1 >= 0:
        sweep = d1 if (0 <= dt <= d1) else d1 - 2 * math.pi
    else:
        sweep = d1 if (d1 <= dt <= 0) else d1 + 2 * math.pi
    out = []
    for k in range(quads):
        t0 = a0 + sweep * k / quads
        t1 = t0 + sweep / quads
        tm = (t0 + t1) / 2
        ctrl = (center[0] + radius / math.cos(sweep / (2 * quads)) * math.cos(tm),
                center[1] + radius / math.cos(sweep / (2 * quads)) * math.sin(tm))
        out.append((ctrl[0], ctrl[1], False))
        if k < quads - 1:
            out.append((center[0] + radius * math.cos(t1),
                        center[1] + radius * math.sin(t1), True))
    return out


def tapered_tip(a, ta, b, tb, axis, apex, tip_r):
    """从 a（切线 ta）到 b（切线 tb）顺成尖端，尖端是半径 tip_r 的圆弧。

    关键：侧边用**三次贝塞尔**，起点控制点沿轮廓原切线方向（G1 连续），
    终点控制点沿轴线方向，这样侧边在接近尖端时自然收拢，不会鼓出赘肉、
    也不会像两段二次那样在接缝处折一个角。
    """
    base = (apex[0] - axis[0] * tip_r, apex[1] - axis[1] * tip_r)
    perp = (-axis[1], axis[0])
    a2 = (base[0] + perp[0] * tip_r, base[1] + perp[1] * tip_r)
    b2 = (base[0] - perp[0] * tip_r, base[1] - perp[1] * tip_r)
    if _dist(a2, a) > _dist(b2, a):
        a2, b2 = b2, a2

    def side(p, tp, q):
        chord = _dist(p, q) or 1.0
        c1 = (p[0] + tp[0] * chord * 0.45, p[1] + tp[1] * chord * 0.45)
        # 第二控制点：从 q 往回沿轴线一个 tip_r
        c2 = (q[0] + axis[0] * tip_r * 1.6, q[1] + axis[1] * tip_r * 1.6)
        return [(c1[0], c1[1], False), (c2[0], c2[1], False), (q[0], q[1], True)]

    out = side(a, ta, a2)
    out += semicircle_quads(base, a2, b2, (perp[0], perp[1]) if _dist(a2, a) < _dist(b2, a) else axis, tip_r, quads=2)
    out += side(b2, (-tb[0], -tb[1]), b)
    return out


def process(font, gname, px=2000, margin_frac=0.08, verbose=True):
    mask, tr = raster_mask(font, gname, px, margin_frac)
    xmin, ymin, scale, margin, upp, sign = tr
    dist = ndimage.distance_transform_edt(mask)
    sk = skeletonize(mask)
    hooks = raster_hooks(mask, sk, dist)
    if not hooks:
        return None

    glyf = font["glyf"]
    glyph = glyf[gname]
    coords, ends, flags = glyph.getCoordinates(glyf)
    contours = split_contours(coords, ends, flags)

    def area(c):
        return sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1]
                   for i in range(len(c))) / 2

    outer = max(range(len(contours)), key=lambda k: abs(area(contours[k])))
    contour = list(contours[outer])

    def to_font(y, x):
        return (xmin + (x - margin) * upp, ymin + (px - margin - y) * upp)

    report = []
    for cut, removed, width_px in hooks:
        cy, cx = cut
        P = to_font(cy, cx)
        banned = {(int(p[0]), int(p[1])) for p in removed}
        # 笔身方向：骨架上去掉钩之后、离开 P 一段距离的点
        # 笔宽不能取自 cut 点：钩根在骨架端点处距离变换会塌成 3 px（`乙` 实测），
        # 而真实半笔宽是 68 px。基准改用**整字骨架距离的中位数**，跟几何无关、稳。
        r = float(np.median(dist[sk])) * upp
        span_px = max(6.0, r / upp * 1.1)
        samples = []
        for y, x in np.argwhere(sk):
            if (y, x) in banned:
                continue
            dd = math.hypot(x - cx, y - cy)
            if 0.8 * span_px <= dd <= 3.2 * span_px:
                samples.append((dd, x, y))
        if not samples:
            # 钩太靠端点：放宽到 6 倍笔宽
            for y, x in np.argwhere(sk):
                if (y, x) in banned:
                    continue
                dd = math.hypot(x - cx, y - cy)
                if dd <= 6.0 * span_px:
                    samples.append((dd, x, y))
        if not samples:
            report.append(("no-body", 0))
            continue
        samples.sort()
        take = samples[: max(6, len(samples) // 3)]
        bx = float(np.mean([s[1] for s in take]))
        by = float(np.mean([s[2] for s in take]))
        B = to_font(by, bx)
        d = _norm((P[0] - B[0], P[1] - B[1]))
        n = (-d[1], d[0])

        hits = cut_points(contour, P, n)
        if len(hits) < 2:
            report.append(("miss", len(hits)))
            continue
        hits.sort(key=lambda h: h[0])
        best = None
        for x in range(len(hits)):
            for y in range(x + 1, len(hits)):
                a, b = hits[x], hits[y]
                w = _dist(a[3], b[3])
                mid = ((a[3][0] + b[3][0]) / 2, (a[3][1] + b[3][1]) / 2)
                cost = abs(w - 2 * r) + 2 * _dist(mid, P)
                if best is None or cost < best[0]:
                    best = (cost, a, b, w)
        _, left, right, width = best
        # 硬门槛：切口的两个交点必须正好是笔宽量级。配对代价天然的次优解
        # （`乙` 第一钩 31 对 64、`包` 第二钩 381 对 63）在这里被挡掉。
        if not (0.82 * 2 * r <= width <= 1.22 * 2 * r):
            report.append(("bad-width", round(width, 1), round(2 * r, 1)))
            continue

        ta = tangent_of(contour, left[1], left[2])
        tb = tangent_of(contour, right[1], right[2])
        inserts = sorted([(left[1], left[2]), (right[1], right[2])], reverse=True)
        spots = []
        for si, t in inserts:
            contour, idx = insert_point(contour, si, t)
            spots.append(idx)
        spots.sort()
        ia, ib = spots
        a = (contour[ia][0], contour[ia][1])
        b = (contour[ib][0], contour[ib][1])
        apex = (P[0] + d[0] * r * REACH, P[1] + d[1] * r * REACH)
        tip_r = max(8.0, r * TIP_RATIO)
        cap = tapered_tip(a, ta, b, tb, d, apex, tip_r)

        m = len(contour)
        forward = (ib - ia) % m
        backward = (ia - ib) % m
        if forward <= backward:
            start, end, span = ia, ib, forward
        else:
            start, end, span = ib, ia, backward
        new = [contour[start]] + cap
        k = (end + 1) % m
        while k != start:
            new.append(contour[k])
            k = (k + 1) % m
        # cap 的最后一个点是 contour[end]，会重复，去掉
        if _dist((new[len(cap)][0], new[len(cap)][1]),
                 (new[len(cap) - 1][0], new[len(cap) - 1][1])) < 1e-6:
            del new[len(cap)]
        contour = new
        report.append(("ok", round(r, 1), round(span, 1)))
        if verbose:
            print(f"  {gname}: {report[-1]}")
    if not any(r[0] == "ok" for r in report):
        return None
    contours[outer] = contour
    flat, new_ends = [], []
    for c in contours:
        flat.extend(c)
        new_ends.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x, y, on in flat])
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    parser.add_argument("--chars", required=True)
    parser.add_argument("--px", type=int, default=2000)
    args = parser.parse_args()
    font = TTFont(args.infont)
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    ok = []
    for ch in dict.fromkeys(args.chars):
        if ord(ch) not in cmap:
            continue
        gname = cmap[ord(ch)]
        if glyf[gname].isComposite():
            continue
        res = process(font, gname, args.px)
        print(f"{ch}: {res}")
        if res:
            ok.append(gname)
    for gname in ok:
        advance = font["hmtx"][gname][0]
        font["hmtx"][gname] = (advance, glyf[gname].xMin)
    font.save(args.outfont)
    print(f"处理 {len(ok)} 字 -> {args.outfont}")


if __name__ == "__main__":
    main()
