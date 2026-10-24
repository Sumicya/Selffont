"""马路口圆体（Maruko Gothic）轮廓曲线重新拟合工具（研究原型，2026-10-19 新建）。

重要边界：本工具只重拟合轮廓曲线并精简控制点，不解析语义笔画，不合并/删除笔画，不调整笔画粗细；
控制点下降不能称为实际笔画简化或视觉质量改善。

背景：马路口圆体作者自己在 README 里承认"几乎都是电脑用 notosans 推论为 zen maru 产生的
字形，很粗糙……直线可能变阶梯形狀"——实测核验过（见会话记录）：它的"回"字 117 个点，
文渊同一个字只要 20 个点，密度差 6 倍；拆开点序列能看到好几段 2~6 个"纯控制点"
(off-curve) 连续堆在一起、中间没有真正落笔的锚点——这是自动描摹/矢量化工具的典型指纹
（潦草地把一条本该一笔到底的长弧线，切成一堆首尾相连的短弧拼出来），不是手工画字那种
"一条视觉弧线对应一个干净控制点"的做法。

本工具不训练神经网络（这个沙箱没有 GPU，zi2zi/HanziGen 这类方案都跑不起来，见会话记录），
走经典几何算法：把轮廓按真实曲线形状密集采样成折线，再用"自适应单二次贝塞尔拟合"
（类似 Potrace/Schneider 曲线拟合思路，但只产出 TrueType 原生的二次贝塞尔，不是三次）
重新分段——该是直线的地方还原成干净直线，该是一条连续弧线的地方用尽量少的控制点拟合，
拟合误差超过阈值就在最大偏差点处切开递归细分，而不是像自动描摹那样见到曲率变化就无脑
多插点。

用法：
    python3 curve_simplify.py 字体.ttf 输出.ttf --chars 回了 --tolerance 3.0
    python3 curve_simplify.py 字体.ttf 输出.ttf --all-mapped --tolerance 4.0 --seg-len 1.5
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import shapely.geometry as sg
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from fontTools.pens.ttGlyphPen import TTGlyphPen

# 拟合出的环自交时容差减半重试的次数；仍自交就退回密集采样折线（见 fit_contour_valid）。
MAX_VALIDITY_RETRIES = 3


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _quad_point(p0, p1, p2, t):
    mt = 1.0 - t
    x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
    y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
    return (x, y)


class FlattenPen(BasePen):
    """把字形轮廓（可能含二次/三次曲线）按弧长密集采样成折线，每个轮廓一条。

    采样点本身不是最终产物，只是给后面的拟合算法当"真实形状的标尺"用——精简后的
    曲线要始终跟这条密集折线比对误差，不是跟原始稀疏控制点比。
    """

    def __init__(self, glyphSet, seg_len=4.0):
        super().__init__(glyphSet)
        self.seg_len = seg_len
        self.contours = []
        self.cur = []
        self.last = None

    def _moveTo(self, pt):
        self.cur = [pt]
        self.last = pt

    def _lineTo(self, pt):
        if pt != self.last:
            self.cur.append(pt)
        self.last = pt

    def _curveToOne(self, p1, p2, p3):
        p0 = self.last
        n = max(2, int(_dist(p0, p3) / self.seg_len))
        for i in range(1, n + 1):
            t = i / n
            mt = 1 - t
            x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
            y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
            self.cur.append((x, y))
        self.last = p3

    def _qCurveToOne(self, p1, p2):
        p0 = self.last
        n = max(2, int(_dist(p0, p2) / self.seg_len))
        for i in range(1, n + 1):
            t = i / n
            self.cur.append(_quad_point(p0, p1, p2, t))
        self.last = p2

    def _closePath(self):
        if self.cur:
            self.contours.append(self.cur)
        self.cur = []

    def _endPath(self):
        if self.cur:
            self.contours.append(self.cur)
        self.cur = []


def rdp_closed(points, tol):
    """闭合轮廓版 Douglas-Peucker：先找一对距离最远的点把环切成两条开放链，
    分别做标准 RDP，再拼回去——避免闭合轮廓首尾相接处被两端各自独立的 RDP
    漏判（标准 RDP 只对开放折线定义明确）。
    """
    pts = np.asarray(points, dtype=float)
    n = len(pts)
    if n < 4:
        return list(range(n))
    # 找距离最远的两点作为切割锚点
    i_max, j_max, best = 0, 0, -1.0
    # 用凸包量级的近似：只挑和质心距离最远的点作为锚点之一，再挑离它最远的另一点
    centroid = pts.mean(axis=0)
    i0 = int(np.argmax(np.linalg.norm(pts - centroid, axis=1)))
    j0 = int(np.argmax(np.linalg.norm(pts - pts[i0], axis=1)))
    i_max, j_max = sorted((i0, j0))

    def rdp_open(idx_list):
        if len(idx_list) < 3:
            return idx_list
        p0, p1 = pts[idx_list[0]], pts[idx_list[-1]]
        seg = p1 - p0
        seg_len = np.linalg.norm(seg)
        if seg_len < 1e-9:
            dists = np.linalg.norm(pts[idx_list] - p0, axis=1)
        else:
            normal = np.array([-seg[1], seg[0]]) / seg_len
            dists = np.abs((pts[idx_list] - p0) @ normal)
        k = int(np.argmax(dists))
        if dists[k] <= tol:
            return [idx_list[0], idx_list[-1]]
        left = rdp_open(idx_list[: k + 1])
        right = rdp_open(idx_list[k:])
        return left[:-1] + right

    chain_a = list(range(i_max, j_max + 1))
    chain_b = list(range(j_max, n)) + list(range(0, i_max + 1))
    ra = rdp_open(chain_a)
    rb = rdp_open(chain_b)
    keep = set(ra) | set(rb)
    return sorted(keep)


def fit_quad_segment(pts, tol, depth=0, max_depth=6):
    """对 pts（含首尾端点在内的一段密集采样点）拟合尽量少的二次贝塞尔段。

    先试"整段一条直线"；不行就试"整段一条二次贝塞尔"（最小二乘求控制点，
    端点固定）；拟合误差仍超阈值，在最大偏差点切开递归——这是本工具的核心，
    保证"该直就直、该一条弧线就一条弧线"，不会像自动描摹那样见到采样噪声
    就跟着多插点。返回 [(kind, p1_or_None, p2), ...]，kind 是 'line' 或 'quad'。
    """
    pts = np.asarray(pts, dtype=float)
    p0, p_end = pts[0], pts[-1]

    # 先试直线
    seg = p_end - p0
    seg_len = np.linalg.norm(seg)
    if seg_len < 1e-9:
        line_err = np.linalg.norm(pts - p0, axis=1).max()
    else:
        normal = np.array([-seg[1], seg[0]]) / seg_len
        line_err = np.abs((pts - p0) @ normal).max()
    if line_err <= tol:
        return [("line", None, tuple(p_end))]

    # 按弦长估参数 t，最小二乘求二次贝塞尔中间控制点（端点固定）
    chord = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(chord)])
    total = cum[-1] if cum[-1] > 1e-9 else 1.0
    t = cum / total
    w = 2 * (1 - t) * t
    target = pts - np.outer((1 - t) ** 2, p0) - np.outer(t ** 2, p_end)
    denom = float((w * w).sum())
    if denom > 1e-9:
        p1 = (w[:, None] * target).sum(axis=0) / denom
    else:
        p1 = (p0 + p_end) / 2
    fitted = np.array([_quad_point(p0, p1, p_end, ti) for ti in t])
    err = np.linalg.norm(fitted - pts, axis=1).max()

    if err <= tol or depth >= max_depth or len(pts) < 5:
        return [("quad", tuple(p1), tuple(p_end))]

    # 误差太大，在最大偏差点切开递归
    k = int(np.argmax(np.linalg.norm(fitted - pts, axis=1)))
    k = max(1, min(len(pts) - 2, k))
    left = fit_quad_segment(pts[: k + 1], tol, depth + 1, max_depth)
    right = fit_quad_segment(pts[k:], tol, depth + 1, max_depth)
    return left + right


def simplify_contour(points, tolerance):
    """points: 密集采样闭合折线（不重复首尾）。返回精简后的 (kind,p1,p2) 段列表，
    从 points[0] 出发首尾相接回到 points[0]。
    """
    n = len(points)
    key_idx = rdp_closed(points, tolerance * 0.6)  # RDP 门槛比最终拟合门槛略紧，避免漏检关键拐点
    if len(key_idx) < 3:
        key_idx = [0, n // 3, 2 * n // 3]
    segments = []
    for a, b in zip(key_idx, key_idx[1:] + [key_idx[0]]):
        if b > a:
            chunk = points[a : b + 1]
        else:
            chunk = points[a:] + points[: b + 1]
        if len(chunk) < 2:
            continue
        segments.extend(fit_quad_segment(chunk, tolerance))
    start = points[key_idx[0]]
    return start, segments


def simplify_glyph(glyphSet, pen_seg_len=4.0, tolerance=3.0):
    flat = FlattenPen(glyphSet, seg_len=pen_seg_len)
    glyphSet.draw = glyphSet.draw if hasattr(glyphSet, "draw") else None
    return flat


def unique_mapped_chars(font):
    """Return one Unicode representative per mapped glyph, in codepoint order."""
    cmap = font.getBestCmap() or {}
    seen = set()
    chars = []
    for codepoint, glyph_name in sorted(cmap.items()):
        if glyph_name in seen:
            continue
        seen.add(glyph_name)
        chars.append(chr(codepoint))
    return chars


def _rounded_points(start, segs):
    points = [(round(start[0]), round(start[1]))]
    for _kind, _p1, p2 in segs:
        points.append((round(p2[0]), round(p2[1])))
    return points


def _ring_is_valid(points):
    """拟合结果必须能构成一个合法环，否则宁可少精简也不能留下自交轮廓。"""
    if len(points) < 3 or len(set(points)) < 3:
        return False
    try:
        return sg.Polygon(points).is_valid
    except ValueError:
        return False


def _emit_contour(tt_pen, start, segs):
    tt_pen.moveTo((round(start[0]), round(start[1])))
    for kind, p1, p2 in segs:
        p2r = (round(p2[0]), round(p2[1]))
        if kind == "line":
            tt_pen.lineTo(p2r)
        else:
            tt_pen.qCurveTo((round(p1[0]), round(p1[1])), p2r)
    tt_pen.closePath()


def fit_contour_valid(contour, tolerance):
    """拟合一条轮廓并保证结果环合法。

    返回 ``(start, segs, used_tolerance)``；容差内拟合出的环自交时把容差减半重试，
    重试到 ``MAX_VALIDITY_RETRIES`` 次仍自交就退回密集采样折线（点数多，形状合法）。
    """
    tol = tolerance
    for _ in range(MAX_VALIDITY_RETRIES):
        start, segs = simplify_contour(contour, tol)
        if _ring_is_valid(_rounded_points(start, segs)):
            return start, segs, tol
        tol /= 2.0
    return contour[0], [("line", None, pt) for pt in contour[1:]], None


def process_font(font, chars, tolerance=3.0, seg_len=4.0, source_font=None):
    """Rewrite selected glyphs in ``font`` using geometry from an immutable source.

    Pass a separately opened ``source_font`` when processing a whole font. Otherwise,
    simplifying an early component can silently change the geometry later read from
    composites that reference it, making the result order-dependent or cumulatively
    simplified. The default is kept for small in-memory callers and simple tests.
    """
    source_font = source_font or font
    output_glyf = font["glyf"]
    source_glyf = source_font["glyf"]
    source_glyph_set = source_font.getGlyphSet()
    cmap = source_font.getBestCmap() or {}
    report = []
    processed = set()
    for ch in chars:
        if ord(ch) not in cmap:
            report.append((ch, None, "missing"))
            continue
        gname = cmap[ord(ch)]
        if gname in processed:
            continue
        processed.add(gname)
        g = source_glyf[gname]
        # 简单字形必须直接读 glyf 坐标：`getGlyphSet()` 会按 `lsb - xMin` 平移。
        # 上游重描过的字形 xMin 变了而 hmtx 的 lsb 还是旧值，走 glyphSet 就会把整个
        # 字平移 lsb-xMin 个单位（实测「个」被移了 20 单位，IoU 0.98 → 0.63）。
        if g.isComposite():
            flat = FlattenPen(source_glyph_set, seg_len=seg_len)
            source_glyph_set[gname].draw(flat)
        else:
            flat = FlattenPen(None, seg_len=seg_len)
            g.draw(flat, source_glyf)

        coords, ends, flags = g.getCoordinates(source_glyf)
        before_real = len(coords)

        tt_pen = TTGlyphPen(source_glyph_set)
        kept_degenerate = 0
        polyline_fallbacks = 0
        tightened = 0
        for contour in flat.contours:
            if len(set(contour)) < 3:
                # 零面积残留轮廓（上游自动描摹留下的 2 点轮廓）原样保留：拟合只会把它变成
                # 一个 shapely 构不成环的假环，被误报成自交。
                _emit_contour(tt_pen, contour[0], [("line", None, pt) for pt in contour[1:]])
                kept_degenerate += 1
                continue
            start, segs, used_tolerance = fit_contour_valid(contour, tolerance)
            if used_tolerance is None:
                polyline_fallbacks += 1
            elif used_tolerance != tolerance:
                tightened += 1
            _emit_contour(tt_pen, start, segs)
        new_glyph = tt_pen.glyph()
        output_glyf[gname] = new_glyph
        after_real = len(new_glyph.coordinates) if hasattr(new_glyph, "coordinates") else 0
        notes = []
        if kept_degenerate:
            notes.append(f"{kept_degenerate} 处零面积轮廓原样保留")
        if tightened:
            notes.append(f"{tightened} 处收紧容差避免自交")
        if polyline_fallbacks:
            notes.append(f"{polyline_fallbacks} 处自交退回密集折线")
        msg = f"{before_real} -> {after_real} 点"
        if notes:
            msg += "（" + "，".join(notes) + "）"
        report.append((ch, gname, msg))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("infont")
    ap.add_argument("outfont")
    selection = ap.add_mutually_exclusive_group()
    selection.add_argument("--chars", help="要精简的字符（不指定时默认 回了）")
    selection.add_argument("--all-mapped", action="store_true", help="处理 cmap 中所有唯一映射字形")
    ap.add_argument("--tolerance", type=float, default=3.0, help="允许的最大几何偏差（字体单位，1000upm 下建议 2~5）")
    ap.add_argument("--seg-len", type=float, default=4.0, help="密集采样步长（字体单位）")
    args = ap.parse_args()

    if Path(args.infont).resolve() == Path(args.outfont).resolve():
        ap.error("输入与输出字体路径不能相同")
    source_font = TTFont(args.infont)
    font = TTFont(args.infont)
    chars = unique_mapped_chars(source_font) if args.all_mapped else list(args.chars or "回了")
    report = process_font(
        font, chars, tolerance=args.tolerance, seg_len=args.seg_len,
        source_font=source_font,
    )
    font.save(args.outfont)
    if args.all_mapped:
        counts = [(int(msg.split(" -> ")[0]), int(msg.split(" -> ")[1].split()[0]))
                  for _, glyph_name, msg in report if glyph_name is not None]
        before = sum(old for old, _ in counts)
        after = sum(new for _, new in counts)
        reduced = sum(new < old for old, new in counts)
        print(f"mapped glyphs={len(counts)}; points={before:,}->{after:,}; "
              f"reduced glyphs={reduced:,}; reduction={(before-after)/before:.1%}" if before else
              f"mapped glyphs={len(counts)}; no contour points")
    else:
        for ch, gname, msg in report:
            print(f"{ch} ({gname}): {msg}")
    print(f"saved -> {args.outfont}")
    font.close()
    source_font.close()


if __name__ == "__main__":
    main()
