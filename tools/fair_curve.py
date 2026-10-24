"""磨平轮廓上的小回勾（折角 / 台阶 / 手抖式拐点）。

为什么需要这一步
----------------
Maruko 的上游轮廓是自动描摹出来的，有些边（`入` 的捺上边缘是典型）在很短的
距离内切线会突然折一下，形成肉眼可见的台阶。这个折角是**上游自带的**，不是保形
并集重描造出来的：4000 px 光栅、30 fu 窗口下原版 0.84°、未磨平的现代版 0.86°，
两者几乎相同；折角区差分 96,076 px 落在共有墨迹里（只原版 147 px、只现代版 821 px）。

本工具不碰拓扑、不碰笔宽，只做一件事：找出"短窗口内切线极差超阈值"的区段，
用两端点与端点切向构造 Hermite 曲线替换掉中间那些点。端点不变，所以笔画长度、
与其他笔画的交点都不动。

量角度必须先定窗口
------------------
12 fu 窗口会给出 21°、60 步/曲线会给出 16.2°，都是量化噪声；设计尺度上的窗口要按
笔宽取（默认 30 fu）。`tangent_score()` 把角度序列接成两圈后整体 unwrap 再滑窗，
否则闭合轮廓绕一圈的 360° 自转会跑进首尾窗口，凭空造出 356° 的假极差。

与 `curve_simplify.py` 的顺序
-----------------------------
`curve_simplify.py` 把折线拟合成二次贝塞尔，追求点数少；它会把折角**当成特征保留**。
本工具输出的是折线，所以必须跑在精简**之前**：顺序颠倒会得到 3248 点/字，
正确顺序下是 135 点/字。

用法：
    python3 tools/fair_curve.py 输入.ttf 输出.ttf --chars 入 --window 30 --span 34 --threshold 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curve_simplify import unique_mapped_chars  # noqa: E402
from stroke_width_audit import FlattenPen  # noqa: E402


def _resample(points: np.ndarray, step: float) -> np.ndarray:
    delta = np.hypot(*(np.roll(points, -1, axis=0) - points).T)
    arc = np.concatenate([[0.0], np.cumsum(delta)[:-1]])
    total = delta.sum()
    if total <= step * 8:
        return points
    count = max(32, int(total / step))
    t = np.linspace(0, total, count, endpoint=False)
    return np.stack([np.interp(t, arc, points[:, 0]), np.interp(t, arc, points[:, 1])], 1)


def _tangents(points: np.ndarray, window_idx: int) -> np.ndarray:
    ahead = np.roll(points, -window_idx, axis=0)
    behind = np.roll(points, window_idx, axis=0)
    tangent = ahead - behind
    norm = np.hypot(tangent[:, 0], tangent[:, 1])
    norm[norm < 1e-9] = 1e-9
    return tangent / norm[:, None]


def tangent_score(points: np.ndarray, window: float = 30.0, span: float = 34.0):
    """每个点所在短窗口内的切线角极差（度）。这就是"台阶"的量化指标。

    闭合轮廓绕一圈本身要转 360°，所以不能先算全局相对角再开窗：那样轮廓首尾
    附近的窗口会把 +0° 和 +356° 混在一起，凭空造出 356° 的假极差。正确做法是把
    角度序列接成两圈后整体 unwrap，再对它做滑窗——两圈之内角度连续，任何真实窗口
    的极差都不会超过窗口自身的转角。
    """
    count = len(points)
    if count < 24:
        return np.zeros(count)
    delta = np.hypot(*(np.roll(points, -1, axis=0) - points).T)
    step = delta.sum() / count
    tangent = _tangents(points, max(4, int(window / step)))
    angle = np.degrees(np.arctan2(tangent[:, 1], tangent[:, 0]))
    doubled = np.degrees(np.unwrap(np.radians(np.concatenate([angle, angle]))))
    half = max(2, int(span / step / 2))
    k = 2 * half
    if k >= count:
        return np.zeros(count)
    win = np.lib.stride_tricks.sliding_window_view(doubled, k)
    score = win.max(axis=1) - win.min(axis=1)
    return score[:count]


def fair(points: np.ndarray, window: float = 30.0, span: float = 34.0,
         threshold: float = 3.0):
    """返回（磨平后的点, 实际替换的处数）。"""
    count = len(points)
    if count < 24:
        return points, 0
    delta = np.hypot(*(np.roll(points, -1, axis=0) - points).T)
    total = delta.sum()
    step = total / count
    arc = np.concatenate([[0.0], np.cumsum(delta)[:-1]])

    tangent = _tangents(points, max(4, int(window / step)))
    score = tangent_score(points, window, span)
    half = max(2, int(span / step / 2))

    hits = np.where(score > threshold)[0]
    if len(hits) == 0:
        return points, 0

    groups = []
    current = [int(hits[0])]
    for hit in hits[1:]:
        if hit - current[-1] <= half:
            current.append(int(hit))
        else:
            groups.append(current)
            current = [int(hit)]
    groups.append(current)

    output = points.copy()
    applied = 0
    for group in sorted(groups, key=lambda g: -int(np.mean(g))):
        center = int(np.mean(group))
        start, end = center - half, center + half
        if start < 0 or end >= count:
            continue
        p0, p1 = points[start], points[end]
        arc_len = arc[end] - arc[start]
        t0 = tangent[start] * arc_len
        t1 = tangent[end] * arc_len
        sub = end - start
        for k in range(1, sub):
            u = k / sub
            h00 = 2 * u ** 3 - 3 * u ** 2 + 1
            h10 = u ** 3 - 2 * u ** 2 + u
            h01 = -2 * u ** 3 + 3 * u ** 2
            h11 = u ** 3 - u ** 2
            output[start + k] = (h00 * p0[0] + h10 * t0[0] + h01 * p1[0] + h11 * t1[0],
                                 h00 * p0[1] + h10 * t0[1] + h01 * p1[1] + h11 * t1[1])
        applied += 1
    return output, applied


def process_font(font: TTFont, chars, window=30.0, span=34.0, threshold=3.0,
                 step=2.0):
    glyf = font["glyf"]
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap() or {}
    report = []
    for ch in chars:
        if ord(ch) not in cmap:
            report.append((ch, None, "missing"))
            continue
        gname = cmap[ord(ch)]
        glyph = glyf[gname]
        if glyph.isComposite():
            report.append((ch, gname, "composite，跳过"))
            continue
        pen = FlattenPen(None, steps_per_curve=max(8, int(48 / step)))
        glyph.draw(pen, glyf)
        out = TTGlyphPen(None)
        total = 0
        changed = 0
        for contour in pen.contours:
            if len(contour) < 3:
                continue
            pts = _resample(np.asarray(contour, dtype=float), step)
            pts, n = fair(pts, window, span, threshold)
            total += n
            ring = [(round(x), round(y)) for x, y in pts]
            compact = []
            for point in ring:
                if not compact or point != compact[-1]:
                    compact.append(point)
            if len(compact) > 2 and compact[0] == compact[-1]:
                compact.pop()
            if len(compact) < 3:
                continue
            out.moveTo(compact[0])
            for point in compact[1:]:
                out.lineTo(point)
            out.closePath()
            changed += 1
        if total:
            new_glyph = out.glyph()
            glyf[gname] = new_glyph
            new_glyph.recalcBounds(glyf)
            advance = font["hmtx"][gname][0]
            font["hmtx"][gname] = (advance, new_glyph.xMin)
        report.append((ch, gname, total))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--chars", help="要处理的字符（默认只处理 入）")
    selection.add_argument("--all-mapped", action="store_true")
    parser.add_argument("--window", type=float, default=30.0, help="切线窗口（字体单位）")
    parser.add_argument("--span", type=float, default=34.0, help="替换区间长度（字体单位）")
    parser.add_argument("--threshold", type=float, default=3.0, help="窗口内切线极差阈值（度）")
    parser.add_argument("--step", type=float, default=2.0, help="重采样步长（字体单位）")
    args = parser.parse_args()

    source = TTFont(args.infont)
    font = TTFont(args.infont)
    chars = unique_mapped_chars(source) if args.all_mapped else list(args.chars or "入")
    report = process_font(font, chars, args.window, args.span, args.threshold, args.step)
    font.save(args.outfont)
    touched = [(ch, n) for ch, _, n in report if isinstance(n, int) and n]
    print(f"处理 {len(report)} 字；磨平 {sum(n for _, n in touched)} 处，涉及 {len(touched)} 字")
    if not args.all_mapped:
        for ch, gname, n in report:
            print(f"  {ch} ({gname}): {n}")
    print(f"saved -> {args.outfont}")


if __name__ == "__main__":
    sys.exit(main())
