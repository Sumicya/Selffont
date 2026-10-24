"""切线连续（G1）的曲线拟合原型 —— **尚未达到可用**，不要接进流水线。

问题在哪
--------
`curve_simplify.py` 用 RDP 找关键点后逐段独立凑二次贝塞尔，段与段只保证位置连续。
实测 `入`：容差 2.5 时 75 段里 63 段接头切线不连续（中位 7.6°），容差 1.0 时 576 段
里 572 段不连续（中位 33.7°）。放大后就是肉眼看到的"边缘一波一波"和"端头被压成
多边形"。

本模块把约束反过来：接头共享同一条切线、尖角处允许断开。214 部首实测（对原
Maruko，700 px/em）：

| 版本 | IoU 均值 | 最低 | <0.95 | 点数/字 |
|---|---|---|---|---|
| 旧 RDP（tol 2.5） | 0.9817 | 0.9724 | 0 | 134 |
| 本模块（error 2.5） | 0.9830 | 0.9739 | 0 | 472 |

IoU 与最低值都更好，但**点数涨了 3.5 倍**，全字库放不下；而且它不是在所有地方都
更好——6000 px/em 逐处核对：`入` 的撇/捺端头明显更圆、更平滑（这一项是它赢），
但 `一` 的右端头被鼓成圆球、下边缘还被咬掉一块（这一项是旧 RDP 赢）。

已知未解决
----------
1. 端头与直边的交界处没有可靠的角点判据，平滑会越过交界，把端头推出去。
2. 逐段自适应加密在直线边附近仍会追着 0.5 fu 的光栅阶梯走，点数降不下来。
3. 端点切线窗口固定 10 fu，对细笔画（Light）偏宽、对粗笔画（Medium）偏窄。

保留原因：上面那张表和三处 6000 px 对照是可复核的中间结果，说明"G1 能改善端头
圆度"这件事成立，但"能直接当产出"不成立。下次要接着做，从第 1 条开始。

用法（仅用于实验）：
    python3 tools/curve_fit_g1.py 输入.ttf 输出.ttf --chars 入 --error 2.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curve_simplify import FlattenPen, unique_mapped_chars  # noqa: E402


def _resample_closed(points: np.ndarray, step: float) -> np.ndarray:
    delta = np.hypot(*(np.roll(points, -1, axis=0) - points).T)
    total = delta.sum()
    if total < step * 8:
        return points
    arc = np.concatenate([[0.0], np.cumsum(delta)[:-1]])
    count = max(24, int(round(total / step)))
    t = np.linspace(0.0, total, count, endpoint=False)
    return np.stack([np.interp(t, arc, points[:, 0]), np.interp(t, arc, points[:, 1])], 1)


def _smooth_run(run: np.ndarray, sigma: float, step: float) -> np.ndarray:
    """沿弧长做高斯平滑，**边缘复制**：两端是尖角，必须原地不动。

    用环形平滑会让角点被对面的点拽走，`入` 的分叉尖、笔锋都会被磨圆。
    """
    if sigma <= 0 or len(run) < 5:
        return run
    radius = max(1, int(round(sigma / step * 2.5)))
    x = np.arange(-radius, radius + 1, dtype=float) * step
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    pad = np.concatenate([np.repeat(run[:1], radius, 0), run, np.repeat(run[-1:], radius, 0)])
    return np.stack([
        np.convolve(pad[:, 0], kernel, "valid"),
        np.convolve(pad[:, 1], kernel, "valid"),
    ], 1)


def _tangent(points: np.ndarray, index: int, half: int) -> np.ndarray:
    count = len(points)
    forward = points[(index + half) % count]
    backward = points[(index - half) % count]
    vector = forward - backward
    length = float(np.hypot(*vector))
    if length < 1e-9:
        return np.array([1.0, 0.0])
    return vector / length


def detect_corners(points: np.ndarray, step: float, threshold: float = 40.0,
                   half: float = 6.0) -> list[int]:
    """找出真正的尖角。返回轮廓下标。

    判据是"跨过该点前后各 half fu 的弦方向变化"。窗口不能太短，否则光栅台阶会被
    当成角；也不能太长，否则曲线最弯处会被当成角。
    """
    count = len(points)
    half_idx = max(1, int(round(half / step)))
    forward = points[(np.arange(count) + half_idx) % count] - points
    backward = points - points[(np.arange(count) - half_idx) % count]
    def _norm(vectors):
        length = np.hypot(vectors[:, 0], vectors[:, 1])
        length[length < 1e-9] = 1e-9
        return vectors / length[:, None]
    cosine = np.clip((_norm(forward) * _norm(backward)).sum(1), -1.0, 1.0)
    angle = np.degrees(np.arccos(cosine))

    hits = np.where(angle > threshold)[0]
    if len(hits) == 0:
        return []
    # 一段连续的超阈值区间只保留角度最大的那个点
    groups, current = [], [int(hits[0])]
    for hit in hits[1:]:
        if hit - current[-1] <= max(2, half_idx):
            current.append(int(hit))
        else:
            groups.append(current)
            current = [int(hit)]
    groups.append(current)
    return [max(group, key=lambda i: angle[i]) for group in groups]


def _fit_cubic(points: np.ndarray, tangent_start: np.ndarray,
               tangent_end: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """端点与端点切向固定，最小二乘求两个手柄长度（Schneider 1990 的解法）。

    两个切向都是**沿曲线前进方向**的单位向量。起点手柄在 ``p0`` 前方，
    终点手柄在 ``p3`` 后方——写成一个方向会把曲线折回来（实测手负值被钳到
    下限、段误差 3.7 fu，一直加密到 449 段才收敛）。
    """
    p0, p3 = points[0], points[-1]
    chord = np.hypot(*(p3 - p0))
    if chord < 1e-9:
        return p0, p3
    delta = np.hypot(*(np.diff(points, axis=0)).T)
    u = np.concatenate([[0.0], np.cumsum(delta)])
    if u[-1] < 1e-9:
        return p0, p3
    u = u / u[-1]

    c00 = c01 = c11 = 0.0
    x0 = x1 = 0.0
    for ui, pi in zip(u, points):
        b0 = (1 - ui) ** 3
        b1 = 3 * ui * (1 - ui) ** 2
        b2 = 3 * ui ** 2 * (1 - ui)
        b3 = ui ** 3
        a1 = tangent_start * b1
        a2 = -tangent_end * b2
        c00 += float(a1 @ a1)
        c01 += float(a1 @ a2)
        c11 += float(a2 @ a2)
        tmp = pi - (p0 * (b0 + b1) + p3 * (b2 + b3))
        x0 += float(a1 @ tmp)
        x1 += float(a2 @ tmp)

    det = c00 * c11 - c01 * c01
    if abs(det) < 1e-12:
        alpha1 = alpha2 = chord / 3.0
    else:
        alpha1 = (x0 * c11 - x1 * c01) / det
        alpha2 = (c00 * x1 - c01 * x0) / det
    # 负手柄会让曲线往回折；超出弦长 3 倍会长出尖刺。两种情况都退回经验值 chord/3
    if not (chord * 0.02 < alpha1 < chord * 3.0 and chord * 0.02 < alpha2 < chord * 3.0):
        alpha1 = alpha2 = chord / 3.0
    return p0 + tangent_start * alpha1, p3 - tangent_end * alpha2


def _cubic_points(p0, p1, p2, p3, count=48) -> np.ndarray:
    t = np.linspace(0.0, 1.0, count)[:, None]
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
            + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)


def _segment_error(points, p0, p1, p2, p3) -> float:
    sample = _cubic_points(p0, p1, p2, p3, max(24, min(200, len(points) * 2)))
    # 点到采样折线的最近距离
    worst = 0.0
    for point in points[:: max(1, len(points) // 60)]:
        worst = max(worst, float(np.min(np.hypot(*(sample - point).T))))
    return worst


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.hypot(*vector))
    if length < 1e-9:
        return np.array([1.0, 0.0])
    return vector / length


def _piece(run: np.ndarray, a: int, b: int, half: int):
    """拟合 run[a:b+1] 这一段，返回 (a, b, p0, p1, p2, p3, 最大偏差)。

    切线只在该段内部取：跨过尖角取会把尖角磨圆；跨过拐点取则会让相邻两段
    不再共用同一条切线。
    """
    count = len(run)
    sub = run[a:b + 1]
    t_start = _unit(run[min(count - 1, a + half)] - run[a])
    t_end = _unit(run[b] - run[max(0, b - half)])
    p0, p3 = sub[0], sub[-1]
    p1, p2 = _fit_cubic(sub, t_start, t_end)
    return a, b, p0, p1, p2, p3, _segment_error(sub, p0, p1, p2, p3)


def fit_run(run: np.ndarray, step: float, error: float, smooth: float = 4.0):
    """把一段（角到角）折线拟合成一串切线连续的三次贝塞尔。

    先按约 220 fu 粗分，再**只对超差的那几段**二分加密。整条轮廓一起加密会把
    直线边也切碎，实测每字从 134 点涨到 472 点。
    """
    run = _smooth_run(run, smooth, step)
    count = len(run)
    if count < 3:
        return []

    half = max(2, int(round(10.0 / step)))
    bounds = list(range(0, count - 1, max(8, int(round(220.0 / step)))))
    if bounds[-1] != count - 1:
        bounds.append(count - 1)
    if len(bounds) < 2:
        return []

    pieces = [_piece(run, a, b, half) for a, b in zip(bounds, bounds[1:])]
    for _ in range(10):
        bad = [i for i, piece in enumerate(pieces) if piece[6] > error]
        if not bad:
            break
        for index in reversed(bad):
            a, b = pieces[index][0], pieces[index][1]
            if b - a < 4:
                continue
            mid = (a + b) // 2
            pieces[index:index + 1] = [
                _piece(run, a, mid, half),
                _piece(run, mid, b, half),
            ]
        if len(pieces) > 3000:
            break
    return [(p[2], p[3], p[4], p[5]) for p in pieces]


def _split_runs(points: np.ndarray, step: float, corner_threshold: float):
    """按尖角把闭合轮廓切成若干段。没有尖角时切成两条半环。"""
    corners = detect_corners(_smooth_run(
        np.concatenate([points[-1:], points, points[:1]]), 1.0, step)[1:-1],
        step, corner_threshold)
    if not corners:
        seed = int(np.argmax(np.hypot(*(points - points.mean(0)).T)))
        ring = np.concatenate([points[seed:], points[:seed]])
        half = len(ring) // 2
        return [ring[:half + 1], np.concatenate([ring[half:], ring[:1]])]
    runs = []
    for index in range(len(corners)):
        a = corners[index]
        b = corners[(index + 1) % len(corners)]
        runs.append(points[a:b + 1] if b > a else np.concatenate([points[a:], points[:b + 1]]))
    return runs


def fit_contour(points: np.ndarray, step: float = 2.0, error: float = 0.8,
                corner_threshold: float = 40.0, smooth: float = 4.0):
    points = _resample_closed(np.asarray(points, float), step)
    if len(points) < 6:
        return []
    out = []
    for run in _split_runs(points, step, corner_threshold):
        out.extend(fit_run(run, step, error, smooth))
    return out


def fit_contour_checked(points, step=2.0, error=0.8, corner_threshold=40.0,
                        smooth=4.0, retries: int = 3):
    """拟合后整环采样核对偏差；超差就收紧容差重来，取历史上最好的一次。"""
    target = _resample_closed(np.asarray(points, float), step)
    tol = error
    best, best_worst = None, float("inf")
    for _ in range(retries + 1):
        segments = fit_contour(points, step, tol, corner_threshold, smooth)
        if not segments:
            return None
        sample = np.concatenate([_cubic_points(*seg, 24)[:-1] for seg in segments])
        worst = max(float(np.min(np.hypot(*(sample - point).T))) for point in target)
        if worst < best_worst:
            best, best_worst = segments, worst
        if worst <= tol * 2.0 + 0.5:
            return segments
        tol *= 0.6
    return best


def _emit(tt_pen, segments):
    quad = Cu2QuPen(tt_pen, max_err=0.35)
    start = segments[0][0]
    quad.moveTo((float(start[0]), float(start[1])))
    for p0, p1, p2, p3 in segments:
        quad.curveTo((float(p1[0]), float(p1[1])),
                     (float(p2[0]), float(p2[1])),
                     (float(p3[0]), float(p3[1])))
    quad.closePath()


def process_font(font: TTFont, chars, error=0.6, step=2.0, corner_threshold=40.0,
                 source_font=None):
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
        # 简单字形直接读 glyf：走 getGlyphSet() 会按 lsb - xMin 平移整个字
        if glyph.isComposite():
            flat = FlattenPen(source_glyph_set, seg_len=step)
            source_glyph_set[gname].draw(flat)
        else:
            flat = FlattenPen(None, seg_len=step)
            glyph.draw(flat, source_glyf)

        coords, _ends, _flags = glyph.getCoordinates(source_glyf)
        before = len(coords)

        tt_pen = TTGlyphPen(source_glyph_set)
        kept = 0
        failed = 0
        for contour in flat.contours:
            if len(set(contour)) < 3:
                tt_pen.moveTo(contour[0])
                for point in contour[1:]:
                    tt_pen.lineTo(point)
                tt_pen.closePath()
                kept += 1
                continue
            segments = fit_contour_checked(contour, step, error, corner_threshold)
            if not segments:
                failed += 1
                tt_pen.moveTo(contour[0])
                for point in contour[1:]:
                    tt_pen.lineTo(point)
                tt_pen.closePath()
                continue
            _emit(tt_pen, segments)
        new_glyph = tt_pen.glyph()
        new_glyph.recalcBounds(output_glyf)
        output_glyf[gname] = new_glyph
        after = len(new_glyph.coordinates) if hasattr(new_glyph, "coordinates") else 0
        advance = font["hmtx"][gname][0]
        font["hmtx"][gname] = (advance, new_glyph.xMin)
        notes = []
        if kept:
            notes.append(f"{kept} 处零面积轮廓原样保留")
        if failed:
            notes.append(f"{failed} 处拟合失败退回折线")
        msg = f"{before} -> {after} 点"
        if notes:
            msg += "（" + "，".join(notes) + "）"
        report.append((ch, gname, msg))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--chars", help="要处理的字符")
    selection.add_argument("--all-mapped", action="store_true")
    parser.add_argument("--error", type=float, default=0.6, help="几何偏差上限（字体单位）")
    parser.add_argument("--step", type=float, default=2.0, help="重采样步长（字体单位）")
    parser.add_argument("--corner", type=float, default=40.0, help="尖角判据（度）")
    args = parser.parse_args()

    source = TTFont(args.infont)
    font = TTFont(args.infont)
    chars = unique_mapped_chars(source) if args.all_mapped else list(args.chars or "入")
    report = process_font(font, chars, args.error, args.step, args.corner,
                          source_font=source)
    font.save(args.outfont)
    print(f"处理 {len(report)} 字")
    if not args.all_mapped:
        for ch, gname, msg in report:
            print(f"  {ch} ({gname}): {msg}")
    print(f"saved -> {args.outfont}")


if __name__ == "__main__":
    sys.exit(main())
