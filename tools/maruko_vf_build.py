"""把 Maruko Gothic 的三个静态字重（Light / Regular / Medium）重拓扑成一份可变字体原型。

为什么需要重拓扑：Maruko 的三个字重不是同一套轮廓的插值结果——实测 31,943 个三档共有的
码位里，98.77% 的字形在不同字重之间点数/轮廓数不同（例如 "国" 117/127/133 点，"暖"
8/8/6 条轮廓）。`varLib.build` 要求同名字形在各源里点数、轮廓数、点序一一对应，直接喂
静态字重会报 `different number of points` 或产出乱形，所以必须先统一结构。

做法（每条轮廓独立处理，不改变可见笔画的增减）：
1. 各字重把字形画成稠密折线（复用 `curve_simplify.FlattenPen`），丢掉零面积残留轮廓；
2. 以轮廓数最多的字重为基准，按"面积 + 质心"贪心匹配其余字重的轮廓；某字重缺这条轮廓时
   补一条退化轮廓（所有点落在基准质心），让它从零面积长出来，而不是把整字从 VF 里剔除；
3. 每条轮廓在"从质心沿固定角度射线穿过轮廓"的位置取同一个起点，按弧长等分成 K 段
   （K 取各字重里最长那条所需的段数），每段用一段二次贝塞尔拟合，控制点取两端切线交点；
   直线段也照样发一段二次曲线（控制点=中点），保证三档结构完全一致；
4. 用 `fontTools.varLib.build` 合成 wght 300–500 的可变字体。

边界：这是研究原型。等弧长重参数化会轻微改变曲率分布（弦高误差打印在报告里），退化轮廓
补位意味着某些细节在 Light 端可能被"压没"再"长出来"，不等于上游设计师的真实插值意图。

用法：
    python3 tools/maruko_vf_build.py --light Light.ttf --regular Regular.ttf --medium Medium.ttf \
        --chars "国回电了" --out Proto.ttf [--seg-len 28] [--min-area 2.0]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from fontTools import subset
from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import build as varlib_build

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curve_simplify import FlattenPen  # noqa: E402

WEIGHT_LOCATIONS = {"light": 300, "regular": 400, "medium": 500}


def polygon_area(points):
    n = len(points)
    if n < 3:
        return 0.0
    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    return float(0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def polygon_centroid(points):
    pts = np.asarray(points, dtype=float)
    return pts.mean(axis=0)


def contour_length(points):
    pts = np.asarray(points, dtype=float)
    d = np.diff(np.vstack([pts, pts[:1]]), axis=0)
    return float(np.sum(np.hypot(d[:, 0], d[:, 1])))


def draw_contours(glyph_set, gname):
    pen = FlattenPen(glyph_set, seg_len=4.0)
    glyph_set[gname].draw(pen)
    out = []
    for contour in pen.contours:
        pts = [(float(x), float(y)) for x, y in contour]
        if len({(round(x, 3), round(y, 3)) for x, y in pts}) < 3:
            continue
        if abs(polygon_area(pts)) < 0.5:
            continue
        out.append(pts)
    return out


def start_point(contour):
    """轮廓上离质心最远的点，作为参数化起点。

    骨架方向原来用"质心射线求交"，但对圆角方块这类对称轮廓，射线与两侧的交点几乎等距，
    取哪一侧完全由数值噪声决定——两个字重可能从对角的两侧起步，中间字重就会拧成一团
    （实测 回/田 在 wght 350/450 炸开，而 300/500 两头完全正常）。
    """
    pts = np.asarray(contour, dtype=float)
    c = polygon_centroid(contour)
    d = np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])
    return pts[int(np.argmax(d))]


def resample_from(contour, k, start_xy):
    """从 ``start_xy`` 处起步、按轮廓自身走向等弧长取 k 个点。"""
    pts = np.asarray(contour, dtype=float)
    dists = np.hypot(pts[:, 0] - start_xy[0], pts[:, 1] - start_xy[1])
    i0 = int(np.argmin(dists))
    closed = np.vstack([pts[i0:], pts[:i0], pts[i0]])
    seg = np.diff(closed, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = float(cum[-1])
    if total <= 0:
        return [tuple(pts[i0])] * k
    out = []
    for t in total * np.arange(k) / k:
        j = int(np.searchsorted(cum, t, side="right") - 1)
        j = min(max(j, 0), len(seg_len) - 1)
        span = seg_len[j] if seg_len[j] > 0 else 1.0
        local = min(max((t - cum[j]) / span, 0.0), 1.0)
        p = closed[j] + local * seg[j]
        out.append((float(p[0]), float(p[1])))
    return out


def align_to_reference(points, ref_points):
    """把采样序列循环平移、必要时整体反向，使它与基准序列逐点对齐。

    两个字重虽然画的是同一笔，但轮廓起点和绕行方向可能不同；不先对齐就直接插值，两端
    字重各自完整、中间会互相穿过（这就是 350/450 出现黑块和碎片的来源）。
    """
    pts = np.asarray(points, dtype=float)
    ref = np.asarray(ref_points, dtype=float)
    n = len(pts)
    candidates = []

    def best_shift(candidate):
        best = None
        for shift in range(n):
            rolled = np.roll(candidate, -shift, axis=0)
            cost = float(np.mean(np.hypot(*(rolled - ref).T)))
            if best is None or cost < best[0]:
                best = (cost, rolled)
        return best

    candidates.append(best_shift(pts))
    reversed_pts = pts[::-1]
    candidates.append(best_shift(reversed_pts))
    cost, aligned = min(candidates, key=lambda c: c[0])
    return [(float(x), float(y)) for x, y in aligned], cost


def start_angle(contour):
    """保留旧接口：返回 start_point 相对的极角，仅供调试输出。"""
    sp = start_point(contour)
    c = polygon_centroid(contour)
    return math.atan2(sp[1] - c[1], sp[0] - c[0])


def resample(contour, k, angle):
    """把闭合折线按弧长重采样成 k 个点，起点取 angle 方向射线与轮廓的交点。

    走一圈必须能正确绕过首尾：早先版本用单调指针找累计长度，绕回起点后会把剩下的点全部
    钳到最后一个采样点（实测 12 个点里有 8 个重合），形状直接崩掉；这里改成对累计长度
    取模 + searchsorted，环绕处由模运算处理。
    """
    c = polygon_centroid(contour)
    d = np.array([math.cos(angle), math.sin(angle)])
    pts = np.asarray(contour, dtype=float)
    rel = pts - c
    proj = rel @ d
    perp = rel @ np.array([-d[1], d[0]])
    best = None
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        if proj[i] > 0 >= proj[j] or proj[j] > 0 >= proj[i]:
            denom = proj[i] - proj[j]
            t = proj[i] / denom if abs(denom) > 1e-12 else 0.0
            hit = pts[i] + t * (pts[j] - pts[i])
            norm = np.array([-d[1], d[0]])
            dist = abs(float((hit - c) @ norm))
            if best is None or dist < best[0]:
                best = (dist, hit)
    start = pts[0] if best is None else best[1]

    closed = np.vstack([pts, pts[:1]])
    seg = np.diff(closed, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = float(cum[-1])
    if total <= 0:
        return [tuple(start)] * k

    dists = np.hypot(pts[:, 0] - start[0], pts[:, 1] - start[1])
    s0 = float(cum[int(np.argmin(dists))])
    targets = (s0 + total * np.arange(k) / k) % total
    out = []
    for t in targets:
        j = int(np.searchsorted(cum, t, side="right") - 1)
        j = min(max(j, 0), len(seg_len) - 1)
        span = seg_len[j] if seg_len[j] > 0 else 1.0
        local = min(max((t - cum[j]) / span, 0.0), 1.0)
        p = closed[j] + local * seg[j]
        out.append((float(p[0]), float(p[1])))
    return out


def _intersect(p, d, q, e):
    """两条参数直线交点；平行或退化返回 None。"""
    denom = d[0] * e[1] - d[1] * e[0]
    if abs(denom) < 1e-9:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / denom
    return p + t * d


def resample_dense(contour, k, angle):
    """按弧长等分成 k 段，返回 k+1 个点（首点重复在末尾，便于逐段取切线）。"""
    pts = resample(contour, k, angle)
    return pts + [pts[0]]


def build_quadratic_contour(points):
    """等弧长点 -> (起点, [(控制点, 终点), ...])，段数恒等于 len(points)。

    控制点取该段两端切线的交点；两端切线近乎平行（直线段）时取中点，此时二次曲线
    退化成直线，形状不变。所有字重走同一段数、同一顺序，varLib 才能插值。
    """
    n = len(points)
    segs = []
    for i in range(n):
        p0 = np.asarray(points[i], dtype=float)
        p1 = np.asarray(points[(i + 1) % n], dtype=float)
        prev = np.asarray(points[(i - 1) % n], dtype=float)
        nxt = np.asarray(points[(i + 2) % n], dtype=float)
        d0 = p1 - prev
        d1 = nxt - p0
        mid = 0.5 * (p0 + p1)
        control = mid
        if np.linalg.norm(d0) > 1e-6 and np.linalg.norm(d1) > 1e-6:
            hit = _intersect(p0, d0 / np.linalg.norm(d0), p1, -d1 / np.linalg.norm(d1))
            if hit is not None:
                # 交点离段中点太远说明该段接近拐角，夹到 1.5 段长内，避免外翻尖刺
                limit = 1.5 * float(np.linalg.norm(p1 - p0))
                if np.linalg.norm(hit - mid) <= limit:
                    control = hit
        segs.append((tuple(control), tuple(p1)))
    return tuple(points[0]), segs


def _match_cost(ref_contour, cand):
    """配对代价：质心距离 + 面积比的对数（面积差用比值，避免细字重被直接判死）。"""
    ref_area = abs(polygon_area(ref_contour)) or 1.0
    cand_area = abs(polygon_area(cand)) or 1.0
    area_cost = abs(math.log(cand_area / ref_area))
    cent_cost = float(np.linalg.norm(polygon_centroid(cand) - polygon_centroid(ref_contour))) / 400.0
    winding_cost = 0.0 if (polygon_area(ref_contour) > 0) == (polygon_area(cand) > 0) else 5.0
    return area_cost + cent_cost + winding_cost


def match_contours(ref, others):
    """把每个字重的轮廓一一配到基准轮廓上；数量不等时多出来的那个字重的轮廓才补退化。

    用最小代价二分匹配，不用"代价超过阈值就丢"的贪心：单轮廓字形（了/乙/也）只有一个候选，
    直接判死会让整个字形在某个字重里变成空壳（实测 Medium 这三字 IoU=0）。
    """
    assignments = [{"ref": c, "assigned": {}} for c in ref]
    stats = {}
    for name, contours in others.items():
        if not contours:
            stats[name] = (0, len(ref))
            continue
        costs = np.zeros((len(ref), len(contours)))
        for i, r in enumerate(ref):
            for j, c in enumerate(contours):
                costs[i, j] = _match_cost(r, c)
        rows, cols = linear_sum_assignment(costs)
        paired = 0
        for i, j in zip(rows, cols):
            assignments[i]["assigned"][name] = contours[j]
            paired += 1
        stats[name] = (paired, max(0, len(ref) - paired))
    return assignments, stats


def retopologize(fonts, glyph_sets, gname, seg_len):
    contours = {name: draw_contours(glyph_sets[name], gname) for name in fonts}
    if any(not c for c in contours.values()):
        return None, "empty"
    ref_name = max(contours, key=lambda n: len(contours[n]))
    ref = contours[ref_name]
    others = {n: c for n, c in contours.items() if n != ref_name}
    assignments, stats = match_contours(ref, others)

    strokes = {name: [] for name in fonts}
    align_costs = []
    for item in assignments:
        members = {ref_name: item["ref"], **item["assigned"]}
        k = 8
        for pts in members.values():
            k = max(k, int(math.ceil(contour_length(pts) / seg_len)))
        k = min(k, 240)
        ref_start = start_point(item["ref"])
        ref_pts = resample_from(item["ref"], k, ref_start)
        for name in fonts:
            if name in members:
                cand = resample_from(members[name], k, start_point(members[name]))
                aligned, cost = align_to_reference(cand, ref_pts)
                align_costs.append(cost)
            else:
                c = polygon_centroid(item["ref"])
                aligned = [tuple(c)] * k
            start, segs = build_quadratic_contour(aligned)
            strokes[name].append((start, segs))
    glyphs = {}
    for name in fonts:
        pen = TTGlyphPen(None)
        for start, segs in strokes[name]:
            pen.moveTo((round(start[0]), round(start[1])))
            for control, end in segs:
                pen.qCurveTo((round(control[0]), round(control[1])), (round(end[0]), round(end[1])))
            pen.closePath()
        glyphs[name] = pen.glyph()
    padded = sum(v[1] for v in stats.values())
    mean_align = float(np.mean(align_costs)) if align_costs else 0.0
    status = "ok" if not padded else f"padded:{padded}"
    return glyphs, f"{status};align={mean_align:.1f}"


def subset_font(src, chars, glyph_names):
    font = TTFont(src)
    options = subset.Options()
    options.glyph_names = True
    options.notdef_glyph = True
    options.notdef_outline = True
    options.name_IDs = ["*"]
    options.layout_features = ["*"]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=chars)
    subsetter.subset(font)
    order = [".notdef"] + [n for n in glyph_names if n in font.getGlyphOrder()]
    font.setGlyphOrder(order)
    return font


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--light", required=True)
    ap.add_argument("--regular", required=True)
    ap.add_argument("--medium", required=True)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seg-len", type=float, default=28.0)
    args = ap.parse_args(argv)

    paths = {"light": args.light, "regular": args.regular, "medium": args.medium}
    fonts = {name: TTFont(path) for name, path in paths.items()}
    glyph_sets = {name: f.getGlyphSet() for name, f in fonts.items()}
    cmaps = {name: f.getBestCmap() for name, f in fonts.items()}

    chars = []
    skipped = []
    for ch in dict.fromkeys(args.chars):
        cp = ord(ch)
        if not all(cp in cmaps[name] for name in fonts):
            skipped.append((ch, "missing"))
            continue
        names = {name: cmaps[name][cp] for name in fonts}
        if len(set(names.values())) != 1:
            skipped.append((ch, "glyph-name-mismatch"))
            continue
        chars.append(ch)
    glyph_names = [cmaps["regular"][ord(ch)] for ch in chars]

    subsets = {name: subset_font(paths[name], "".join(chars), glyph_names) for name in fonts}
    rebuilt = []
    dropped = []
    align_scores = []
    for ch in chars:
        gname = cmaps["regular"][ord(ch)]
        glyphs, status = retopologize(fonts, glyph_sets, gname, args.seg_len)
        if glyphs is None:
            dropped.append((ch, status))
            continue
        if status.startswith("padded"):
            # 某字重缺这条轮廓时只能补一个退化轮廓，细节在那一端会被压没再长出来。
            # 原型阶段宁可少收字也不发这种字形，如实记进报告。
            dropped.append((ch, status))
            continue
        for name in fonts:
            subsets[name]["glyf"][gname] = glyphs[name]
        rebuilt.append(ch)
        if "align=" in status:
            align_scores.append(float(status.split("align=")[1]))

    rebuilt_set = set(rebuilt)
    for name, font in subsets.items():
        # glyf 里留着未重拓扑的原始轮廓会让各源的点数对不上，直接把丢弃的字形从字体里删掉，
        # 不只是从 cmap 摘掉（只摘 cmap 会留下 maxp/glyphOrder 数量不一致，varLib 报 AssertionError）。
        for ch in chars:
            if ch in rebuilt_set:
                continue
            gname = cmaps["regular"][ord(ch)]
            if gname in font.getGlyphOrder() and gname != ".notdef":
                del font["glyf"].glyphs[gname]
                for table in font["cmap"].tables:
                    table.cmap.pop(ord(ch), None)
                for tag in ("GDEF", "GSUB", "GPOS"):
                    if tag in font:
                        # 删字形后这些表里还留着旧 glyph id，留着 varLib 会 KeyError；
                        # 原型只验证字重插值，不携带排印特性（见报告限制）。
                        del font[tag]

    for name, font in subsets.items():
        font["head"].unitsPerEm = 1000
        font["OS/2"].usWeightClass = WEIGHT_LOCATIONS[name]
        font["name"].setName(name.title(), 2, 3, 1, 0x409)
    order = [".notdef"] + [cmaps["regular"][ord(ch)] for ch in rebuilt]
    for font in subsets.values():
        font.setGlyphOrder(order)

    ds = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name = "Weight"
    axis.tag = "wght"
    axis.minimum = 300
    axis.default = 400
    axis.maximum = 500
    ds.addAxis(axis)
    for name, font in subsets.items():
        path = Path(args.out).with_suffix(f".{name}.ttf")
        font.save(path)
        src = SourceDescriptor()
        src.path = str(path)
        src.name = name
        src.familyName = "Maruko Proto"
        src.location = {"Weight": WEIGHT_LOCATIONS[name]}
        ds.addSource(src)

    vf, _, _ = varlib_build(ds)
    vf.save(args.out)
    if align_scores:
        arr = sorted(align_scores)
        mean = sum(arr) / len(arr)
        p95 = arr[int(0.95 * (len(arr) - 1))]
        print(f"align RMS: mean={mean:.1f} fu p95={p95:.1f} fu max={arr[-1]:.1f} fu")
    print(f"requested={len(chars) + len(skipped)} rebuilt={len(rebuilt)} "
          f"dropped={len(dropped)} skipped={len(skipped)} -> {args.out}")
    if dropped[:8]:
        print("dropped sample:", dropped[:8])
    with open(Path(args.out).with_suffix(".report.tsv"), "w", encoding="utf-8") as handle:
        handle.write("char\tstatus\n")
        for ch in rebuilt:
            handle.write(f"{ch}\tok\n")
        for ch, status in dropped:
            handle.write(f"{ch}\t{status}\n")
        for ch, status in skipped:
            handle.write(f"{ch}\t{status}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
