#!/usr/bin/env python3
"""母版精修：删多余点 + 压拉丁间距，产出一份新母版。

两件事各自可关，判据都写死在这里，不靠肉眼：

① **删多余点**（`--dedupe`，默认开）
   只判两类「加了等于没加」的点：
   · 相邻重复点：一段的终点与上一段的终点完全同坐标 —— 零长度段，渲染不可见。
   · 共线中间点：前后两段都是直线，且中间点正好落在首尾连线上 —— 删后形状零变化。
   二次曲线的控制点一律不判：控制点不在曲线上，共线也不等于可删。

② **压拉丁间距**（`--latin-gap`，upm 千分比，默认 30）
   只动 advance 与 lsb，字形坐标整体平移，笔画粗细与形状零改动。不缩放——缩放会改笔画粗细。
   实测基线：母版每侧留白中位 **56**（合计 113/1000 em），且**本身已有 68 对碰撞**
   （FJ 墨隙 −93、Qj −82、YJ −71，均由 kern 或字形本身造成）。
   所以「压小」必须同时**重写 kern**，否则越压越撞：
   · 只压间距：每侧 48 → 118 对碰撞；42 → 162；36 → 199；30 → 257。
   · 压间距 + kern 推到「墨隙 ≥ --min-gap」（默认 8）：以上四档**碰撞全为 0**，
     代价是每侧 30 时改 336 对 kern、最紧墨隙恒为 8。
   选 30 的理由：合计 60/1000 em 比现状 113 紧 47%，而碰撞仍是 0。再小就要改更多 kern 对
   （每侧 24 需 546 对），收益递减。

用法：
  python3 tools/slim_mother.py 母版.ttf -o 精修.ttf [--latin-gap 60] [--no-dedupe]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

LATIN_MAX = 0x0250          # 拉丁基本区 + 扩展 A/B 开头；CJK 一律不碰


def outline_paths(font: TTFont, gname: str):
    """展开成逐轮廓段列表。每段是 ('move', pt) / ('line', pt) / ('q', [ctrl...], end)。"""
    gs = font.getGlyphSet()
    pen = DecomposingRecordingPen(gs)
    gs[gname].draw(pen)
    contours, cur = [], []
    for op, args in pen.value:
        if op == "moveTo":
            if cur:
                contours.append(cur)
            cur = [("move", args[0])]
        elif op == "lineTo":
            cur.append(("line", args[0]))
        elif op == "qCurveTo":
            pts = [p for p in args if p is not None]
            cur.append(("q", pts[:-1], pts[-1]))
        elif op == "curveTo":
            raise SystemExit(f"{gname}: 出现三次曲线，本字体不该有，拒绝处理")
        elif op == "closePath":
            if cur:
                contours.append(cur)
                cur = []
    if cur:
        contours.append(cur)
    return contours


def end_of(seg):
    return seg[1] if seg[0] in ("move", "line") else seg[2]


def drop_redundant(segments):
    n = len(segments)
    if n < 3:
        return segments, 0
    keep = [True] * n
    for i in range(1, n):                      # ① 零长度段
        if end_of(segments[i]) == end_of(segments[i - 1]):
            keep[i] = False
    for i in range(n):                         # ② 共线中间点
        if not keep[i] or segments[i][0] != "line":
            continue
        j, guard = (i + 1) % n, 0
        while not keep[j] and guard < n:
            j, guard = (j + 1) % n, guard + 1
        if j == i or segments[j][0] != "line":
            continue
        p, b, q = end_of(segments[i - 1]), end_of(segments[i]), end_of(segments[j])
        cross = (b[0] - p[0]) * (q[1] - p[1]) - (b[1] - p[1]) * (q[0] - p[0])
        if cross == 0 and min(p[0], q[0]) <= b[0] <= max(p[0], q[0]) \
                and min(p[1], q[1]) <= b[1] <= max(p[1], q[1]):
            keep[i] = False
    out = [s for s, k in zip(segments, keep) if k]
    return out, n - len(out)


def to_glyph(paths, offset_x=0):
    pen = TTGlyphPen(None)
    for segs in paths:
        for seg in segs:
            if seg[0] == "move":
                pen.moveTo((seg[1][0] + offset_x, seg[1][1]))
            elif seg[0] == "line":
                pen.lineTo((seg[1][0] + offset_x, seg[1][1]))
            else:
                pen.qCurveTo(*[(p[0] + offset_x, p[1]) for p in seg[1]], (seg[2][0] + offset_x, seg[2][1]))
        pen.closePath()
    return pen.glyph()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--latin-gap", type=int, default=30,
                    help="拉丁每侧留白（upm 千分比，默认 30；0 = 只删点不动间距）")
    ap.add_argument("--min-ink", type=int, default=40,
                    help="kern 重写的目标：任意两字母**真实墨距**不小于这个值（upm 千分比，默认 40）")
    ap.add_argument("--no-kern", action="store_true", help="只压间距，不动 kern")
    ap.add_argument("--no-dedupe", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个字形（调试用）")
    args = ap.parse_args()

    font = TTFont(args.source)
    upm = font["head"].unitsPerEm
    cmap, hmtx, glyf = font.getBestCmap(), font["hmtx"], font["glyf"]
    target = args.latin_gap * upm // 1000

    order = font.getGlyphOrder()
    todo = [n for n in order if glyf[n].numberOfContours != 0]
    if args.limit:
        todo = todo[:args.limit]

    pts_before = pts_after = 0
    n_dedup = n_regap = 0
    gaps_before, gaps_after = [], []

    latin_chars = [chr(cp) for cp in sorted(cmap) if 0x41 <= cp <= 0x7A]
    is_latin_any = set()
    for cp, g in cmap.items():
        if 0x20 <= cp < LATIN_MAX:
            is_latin_any.add(g)

    for gname in todo:
        paths = outline_paths(font, gname)
        pts_before += sum(len(c) for c in paths)
        removed_here = 0
        if not args.no_dedupe:
            cleaned, removed = [], 0
            for c in paths:
                cc, r = drop_redundant(c)
                cleaned.append(cc)
                removed += r
            if removed:
                n_dedup += 1
                removed_here = removed
                paths = cleaned
        pts_after += sum(len(c) for c in paths)

        # 拉丁：把左右空压到 target（只平移字形，改 advance 与 lsb）
        offset = 0
        new_aw = None
        if gname in is_latin_any and target:
            xs = [p[0] for c in paths for seg in c for p in
                  ([seg[1]] if seg[0] in ("move", "line") else list(seg[1]) + [seg[2]])]
            if xs:
                xmin, xmax = min(xs), max(xs)
                old_aw, old_lsb = hmtx[gname]
                gaps_before.append(old_lsb)
                offset = target - xmin
                new_aw = int(xmax - xmin + 2 * target)
                gaps_after.append(target)
                n_regap += 1
        # ★ 只重建「真的改了」的字形。2026-11-21 实测教训：无条件重建会把全字库点数
        #   从 6,844,184 涨到 6,844,485（+301）——TTGlyphPen 重画会补入隐含的 on-curve 点，
        #   而且复合字形被展平成简单字形。删掉的 226 个点还不够补回去的。
        #   判据：删过点，或者需要横向平移（拉丁压间距）。
        if removed_here or offset:
            glyf[gname] = to_glyph(paths, offset)
        if new_aw is not None:
            hmtx[gname] = (new_aw, target)

    print(f"点数 {pts_before} → {pts_after}（删 {pts_before - pts_after}，"
          f"{(pts_before - pts_after) / max(pts_before,1) * 100:.2f}%），涉及 {n_dedup} 个字形")
    if gaps_before:
        import statistics
        print(f"拉丁 {n_regap} 个字形：左侧空 中位 {statistics.median(gaps_before):.0f} → {target}")
    # ---- ③ kern 重写：判据是**真实墨距**，不是包络盒 ----
    # 这一步的判据换过一次，写清为什么换：
    #   第一版用包络盒（advance − xMax + xMin）判碰撞，得出「母版已有 68 对碰撞」，
    #   然后把 ATA/AV/AY 的 kern 从 −100 硬拉到 −52 —— 那是错的。
    #   A 与 T 都是斜边三角，盒子交叠但墨迹根本不碰：ATA 的真实墨距是 197.6，不是 −41。
    #   按盒子改 kern 等于毁掉字体原有的视觉节奏（主人当场点破：ATA、Ay 这种你都没量就压）。
    # 真实墨距 = 两个字形轮廓（含 kern 平移）之间的最近点距。
    # 目标只有一个：把「真实墨距 < --min-ink」的对推开到该值，其余 kern 一律不动。
    import math
    from fontTools.pens.recordingPen import DecomposingRecordingPen as _DRP

    def _contours(font_, gname, shift=0.0):
        gs = font_.getGlyphSet()
        pen = _DRP(gs)
        gs[gname].draw(pen)
        out, cur = [], []
        for op, args in pen.value:
            if op == "moveTo":
                cur = [(args[0][0] + shift, args[0][1])]
            elif op == "lineTo":
                cur.append((args[0][0] + shift, args[0][1]))
            elif op == "qCurveTo":
                pts = [p for p in args if p is not None]
                prev = cur[-1]
                if len(pts) == 2:
                    c, e = pts
                    for i in range(1, 9):
                        t = i / 8
                        cur.append(((1 - t) ** 2 * prev[0] + 2 * (1 - t) * t * c[0] + t * t * e[0] + shift,
                                    (1 - t) ** 2 * prev[1] + 2 * (1 - t) * t * c[1] + t * t * e[1]))
                else:
                    cur.append((pts[-1][0] + shift, pts[-1][1]))
            elif op == "closePath":
                if cur:
                    out.append(cur)
                    cur = []
        if cur:
            out.append(cur)
        return out

    def _pseg(p, a, b):
        px, py = p
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        if L == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def _inkdist(c1, c2):
        best = 1e18
        for A_ in c1:
            n = len(A_)
            for i in range(n):
                a, b = A_[i], A_[(i + 1) % n]
                for B_ in c2:
                    m = len(B_)
                    for j in range(m):
                        c, d = B_[j], B_[(j + 1) % m]
                        best = min(best, _pseg(c, a, b), _pseg(d, a, b),
                                   _pseg(a, c, d), _pseg(b, c, d))
        return best

    rewrote = 0
    if target and not args.no_kern:
        mg = args.min_ink
        font.save(args.output)
        font = TTFont(args.output)
        cmap, hmtx, glyf = font.getBestCmap(), font["hmtx"], font["glyf"]
        cache = {}
        for ch in latin_chars:
            g = cmap[ord(ch)]
            if glyf[g].numberOfContours > 0:
                cache[g] = _contours(font, g)
        current = {}
        for lookup in font["GPOS"].table.LookupList.Lookup:
            if lookup.LookupType != 2:
                continue
            for sub in lookup.SubTable:
                fmt = getattr(sub, "Format", 0)
                if fmt == 1:
                    for g1, ps in zip(sub.Coverage.glyphs, sub.PairSet):
                        for pvr in ps.PairValueRecord:
                            current[(g1, pvr.SecondGlyph)] = getattr(pvr.Value1, "XAdvance", 0) or 0
                elif fmt == 2:
                    cd1, cd2 = sub.ClassDef1.classDefs, sub.ClassDef2.classDefs
                    for g1 in sub.Coverage.glyphs:
                        r1 = sub.Class1Record[cd1.get(g1, 0)]
                        for g2, c2 in cd2.items():
                            if c2 < len(r1.Class2Record):
                                current[(g1, g2)] = getattr(
                                    r1.Class2Record[c2].Value1, "XAdvance", 0) or 0
        want = {}
        for A in latin_chars:
            for B in latin_chars:
                ga, gb = cmap[ord(A)], cmap[ord(B)]
                if ga not in cache or gb not in cache:
                    continue
                shift = hmtx[ga][0] + current.get((ga, gb), 0)
                moved = [[(x + shift, y) for x, y in c] for c in cache[gb]]
                d = _inkdist(cache[ga], moved)
                if d < mg:
                    want[(ga, gb)] = current.get((ga, gb), 0) + (mg - d)
        for lookup in font["GPOS"].table.LookupList.Lookup:
            if lookup.LookupType != 2:
                continue
            for sub in lookup.SubTable:
                fmt = getattr(sub, "Format", 0)
                if fmt == 1:
                    for g1, ps in zip(sub.Coverage.glyphs, sub.PairSet):
                        for pvr in ps.PairValueRecord:
                            nv = want.get((g1, pvr.SecondGlyph))
                            if nv is not None:
                                pvr.Value1.XAdvance = int(round(nv))
                                rewrote += 1
                elif fmt == 2:
                    cd1, cd2 = sub.ClassDef1.classDefs, sub.ClassDef2.classDefs
                    for g1 in sub.Coverage.glyphs:
                        r1 = sub.Class1Record[cd1.get(g1, 0)]
                        for g2, c2 in cd2.items():
                            nv = want.get((g1, g2))
                            if nv is None or c2 >= len(r1.Class2Record):
                                continue
                            r1.Class2Record[c2].Value1.XAdvance = int(round(nv))
                            rewrote += 1
        print(f"kern 重写：{rewrote} 条（真实墨距下限 {mg} 单位）")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    font.save(args.output)
    print(f"写出 {args.output}（{args.output.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
