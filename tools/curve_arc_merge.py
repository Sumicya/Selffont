"""把 RDP 折线合并成真弧：修掉 `curve_simplify.py` 退化成多边形的问题。

问题
----
`curve_simplify.py` 先用 RDP 以 ``tolerance * 0.6`` 切出关键点，再对每两个相邻
关键点之间的小段试拟合——因为 RDP 已经保证每段离直线不超过 0.6 倍容差，
`fit_quad_segment` 的"先试直线"永远命中。实测 214 个部首共 **28,691 段，全是
直线，0 条曲线**。输出是一个多边形字体，放大后必然一波一波、端头必然是多边形。

本工具不改那个工具，只换拟合这一步：仍然用 RDP 找候选断点，但**允许跨越多个
关键点合并成一条二次弧**，直到再加一个点就超差或累计转角超 90° 为止。

为什么要卡 90°
--------------
`tools/round.py` 里早就量过：用单段抛物线去近似 180° 的半圆，肩部外鼓 55%，
是方肩；拆成两段 90° 弧，肩部误差 <7%，肉眼即圆。所以"一段最多转 90°"是端头
能不能圆的分水岭，也是筑紫 A 那套半圆端头算法的隐含前提。

用法：
    python3 tools/curve_arc_merge.py 输入.ttf 输出.ttf --chars 入 --tolerance 2.5
    python3 tools/curve_arc_merge.py 输入.ttf 输出.ttf --all-mapped --tolerance 2.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curve_simplify import (  # noqa: E402
    MAX_VALIDITY_RETRIES,
    FlattenPen,
    _emit_contour,
    _ring_is_valid,
    _rounded_points,
    rdp_closed,
    unique_mapped_chars,
)

MAX_TURN = 90.0          # 单段最多转 90°：超过就必然鼓成方肩
LINE_SAGITTA = 0.35      # 弦偏差小于这个值直接当直线，别硬套一条弧
SAMPLE_STEPS = 24        # 校验环时要按真实曲线取样，不能只看控制点


def _fit_quad(pts: np.ndarray):
    """端点固定，最小二乘求二次贝塞尔的控制点；返回 (控制点, 最大偏差)。"""
    p0, p_end = pts[0], pts[-1]
    chord = np.hypot(*(np.diff(pts, axis=0)).T)
    cum = np.concatenate([[0.0], np.cumsum(chord)])
    total = cum[-1] if cum[-1] > 1e-9 else 1.0
    t = cum / total
    w = 2 * (1 - t) * t
    target = pts - np.outer((1 - t) ** 2, p0) - np.outer(t ** 2, p_end)
    denom = float((w * w).sum())
    p1 = ((w[:, None] * target).sum(axis=0) / denom) if denom > 1e-9 else (p0 + p_end) / 2
    fitted = ((1 - t) ** 2)[:, None] * p0 + w[:, None] * p1 + (t ** 2)[:, None] * p_end
    return p1, float(np.linalg.norm(fitted - pts, axis=1).max())


def _turn(p0, p1, p2) -> float:
    a, b = p1 - p0, p2 - p1
    na, nb = float(np.hypot(*a)), float(np.hypot(*b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(float(a @ b) / (na * nb), -1.0, 1.0))))


def _chord_points(points: np.ndarray, a: int, b: int) -> np.ndarray:
    n = len(points)
    if b > a:
        return points[a:b + 1]
    return np.concatenate([points[a:], points[:b + 1]])


def sample_segments(start, segs, steps: int = SAMPLE_STEPS):
    """按真实曲线取样。只拿控制点当环去判自交是无效的：控制点可能落在合法位置上，
    而二次弧实际鼓出去的那部分却越界了（`入` 的撇端头就这样漏了过去）。"""
    out = []
    for kind, p1, p2 in segs:
        p0 = out[-1] if out else start
        if kind == "line":
            for k in range(1, steps + 1):
                t = k / steps
                out.append((p0[0] + (p2[0] - p0[0]) * t, p0[1] + (p2[1] - p0[1]) * t))
        else:
            for k in range(1, steps + 1):
                t = k / steps
                u = 1.0 - t
                out.append((
                    u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
                ))
    return out


def merge_contour_valid(contour, tolerance, max_turn=MAX_TURN):
    """合并后按真实曲线取样核对环合法性；自交就把容差减半重来。"""
    tol = tolerance
    for _ in range(MAX_VALIDITY_RETRIES):
        start, segs = merge_contour(contour, tol, max_turn)
        if _ring_is_valid(sample_segments(start, segs)):
            return start, segs, tol
        tol /= 2.0
    return contour[0], [("line", None, pt) for pt in contour[1:]], None


def merge_contour(points, tolerance, max_turn=MAX_TURN):
    """返回 (起点, [(kind, 控制点或 None, 终点), ...])，首尾相接。"""
    points = np.asarray(points, float)
    n = len(points)
    if n < 4:
        return points[0], [("line", None, tuple(points[i])) for i in range(1, n)]

    keys = rdp_closed(points, tolerance * 0.6)
    if len(keys) < 3:
        keys = [0, n // 3, 2 * n // 3]
    m = len(keys)

    segments = []
    i = 0
    while i < m:
        a = keys[i]
        best = None
        best_j = None
        # 至少吃掉下一个关键点，然后尽量往后并；j 只在"接受"时才推进 best_j，
        # 否则跳出循环时 i 会落到被拒的那个点上，段与段之间凭空裂开。
        j = i + 1
        while j - i < m:
            b = keys[j % m]
            if j % m == 0:
                b = keys[0]
            if b == a:
                break
            chunk = _chord_points(points, a, b)
            if len(chunk) < 2:
                break
            p0, p_end = chunk[0], chunk[-1]
            span = p_end - p0
            span_len = float(np.hypot(*span))
            if span_len < 1e-9:
                sagitta = float(np.linalg.norm(chunk - p0, axis=1).max())
            else:
                normal = np.array([-span[1], span[0]]) / span_len
                sagitta = float(np.abs((chunk - p0) @ normal).max())
            p1, err = _fit_quad(chunk)
            turn = _turn(p0, p1, p_end)
            if err > tolerance or turn > max_turn:
                break
            best = (p0, p1, p_end, err, sagitta)
            best_j = j
            j += 1
        if best is None:
            b = keys[(i + 1) % m]
            segments.append(("line", None, tuple(points[b])))
            i += 1
            continue
        p0, p1, p_end, err, sagitta = best
        if err <= LINE_SAGITTA or sagitta <= LINE_SAGITTA:
            segments.append(("line", None, tuple(p_end)))
        else:
            segments.append(("quad", tuple(p1), tuple(p_end)))
        i = best_j
        if best_j >= m:
            break
    return points[keys[0]], segments


def process_font(font: TTFont, chars, tolerance=2.5, seg_len=1.0, source_font=None):
    source_font = source_font or font
    output_glyf = font["glyf"]
    source_glyf = source_font["glyf"]
    source_glyph_set = source_font.getGlyphSet()
    cmap = source_font.getBestCmap() or {}
    report, processed = [], set()
    for ch in chars:
        if ord(ch) not in cmap:
            report.append((ch, None, "missing"))
            continue
        gname = cmap[ord(ch)]
        if gname in processed:
            continue
        processed.add(gname)
        glyph = source_glyf[gname]
        if glyph.isComposite():
            flat = FlattenPen(source_glyph_set, seg_len=seg_len)
            source_glyph_set[gname].draw(flat)
        else:
            flat = FlattenPen(None, seg_len=seg_len)
            glyph.draw(flat, source_glyf)

        coords, _ends, _flags = glyph.getCoordinates(source_glyf)
        before = len(coords)

        tt_pen = TTGlyphPen(source_glyph_set)
        quads = 0
        kept = 0
        for contour in flat.contours:
            if len(set(contour)) < 3:
                tt_pen.moveTo(contour[0])
                for point in contour[1:]:
                    tt_pen.lineTo(point)
                tt_pen.closePath()
                kept += 1
                continue
            start, segs, _used = merge_contour_valid(contour, tolerance)
            quads += sum(1 for seg in segs if seg[0] == "quad")
            _emit_contour(tt_pen, start, segs)
        new_glyph = tt_pen.glyph()
        output_glyf[gname] = new_glyph
        new_glyph.recalcBounds(output_glyf)
        advance = font["hmtx"][gname][0]
        font["hmtx"][gname] = (advance, new_glyph.xMin)
        after = len(new_glyph.coordinates) if hasattr(new_glyph, "coordinates") else 0
        note = f"{before} -> {after} 点，真弧 {quads} 段"
        if kept:
            note += f"，{kept} 处零面积轮廓原样保留"
        report.append((ch, gname, note))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--chars")
    selection.add_argument("--all-mapped", action="store_true")
    parser.add_argument("--tolerance", type=float, default=2.5)
    parser.add_argument("--seg-len", type=float, default=1.0)
    args = parser.parse_args()

    source = TTFont(args.infont)
    font = TTFont(args.infont)
    chars = unique_mapped_chars(source) if args.all_mapped else list(args.chars or "入")
    report = process_font(font, chars, args.tolerance, args.seg_len, source_font=source)
    font.save(args.outfont)
    print(f"处理 {len(report)} 字")
    if not args.all_mapped:
        for ch, gname, note in report:
            print(f"  {ch} ({gname}): {note}")
    print(f"saved -> {args.outfont}")


if __name__ == "__main__":
    sys.exit(main())
