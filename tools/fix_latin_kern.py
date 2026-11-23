#!/usr/bin/env python3
"""按真实墨距重算拉丁字偶距，写进母版 GPOS。

为什么要有这一步：`tools/slim_mother.py` 压完侧距后只能改**母版已有**的 kern 条目，
新产生的近对（`QA`、`qj`、`Qz`…）母版本无记录，于是压得越紧撞得越多。这个脚本
对 52 个字母的两两组合（2,704 对）逐个量真实最小墨距，重建 PairPos。

量法（与 `tools/slim_mother.py` 的 kern 重写同一把尺）：把两字的轮廓按
`advance + kern` 摆好，逐段求最小点段距离。不是 bbox 相减——`AV`/`AT` 这种斜边
相让的组合 bbox 重叠但轮廓不碰，用 bbox 会把它们误判成碰撞。

写法：替换 GPOS 里所有 PairPos lookup，改成一个 Format 1 的 PairPos，只写非零对。
`--min-ink` 是下限，`--max-ink` 是上限（母版里 `HH`、`oo` 本来就该松，不许被压）。

    .venv/bin/python tools/fix_latin_kern.py 母版.ttf -o 修好.ttf --min-ink 40
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib.tables import otTables as ot

LETTERS = [chr(c) for c in range(0x41, 0x7B) if chr(c).isalpha()]
STEPS = 10          # 二次曲线展开成折线的段数


def flatten(glyphset, gname: str) -> np.ndarray:
    """轮廓展平成线段数组 (N, 4)，行 = (x0, y0, x1, y1)。"""
    rp = RecordingPen()
    glyphset[gname].draw(rp)
    segs = []
    start = last = None

    def emit(a, b):
        if a is not None and b is not None and (a[0] != b[0] or a[1] != b[1]):
            segs.append((a[0], a[1], b[0], b[1]))

    for op, args in rp.value:
        if op == "moveTo":
            start = last = args[0]
        elif op == "lineTo":
            emit(last, args[0]); last = args[0]
        elif op == "qCurveTo":
            pts = list(args)
            end = pts[-1] if pts[-1] is not None else start
            prev = last
            for c in pts[:-1]:
                if c is None:
                    continue
                for i in range(1, STEPS + 1):
                    t = i / STEPS
                    x = (1-t)**2*prev[0] + 2*(1-t)*t*c[0] + t*t*end[0]
                    y = (1-t)**2*prev[1] + 2*(1-t)*t*c[1] + t*t*end[1]
                    emit(prev, (x, y)); prev = (x, y)
            emit(prev, end); last = end
        elif op == "closePath":
            emit(last, start); last = start
    return np.array(segs, dtype=np.float64).reshape(-1, 4)


BAND = 10          # 逐带量水平间距的带宽（upm 千分比 10 = 1% em）


def bands(a: np.ndarray) -> dict:
    """逐 BAND 单位水平带的 (xMin, xMax)。按带比按点更接近「看起来挤不挤」：
    斜边的笔尖只有一点接触，但整条斜边在水平上可以大面积叠住。"""
    x, y = a[:, [0, 2]], a[:, 1]
    lo, hi = int(y.min()), int(y.max())
    out = {}
    for y0 in range(lo - (lo % BAND), hi + 1, BAND):
        m = (y >= y0) & (y < y0 + BAND)
        if m.any():
            out[y0] = (float(x[m].min()), float(x[m].max()))
    return out


def band_gap(pa: dict, pb: dict, adv: float):
    """后字平移后，两字在同一带上的水平净距：返回 (最小, 平均, 重叠带数, 共同带数)。

    重叠带（净距 < 0）说明两条墨边在水平方向互相穿插——这才是「挤」的定义。
    只取共同有墨的带：A 的右上角与 V 的左下角本来就不共处一个高度，不该参与比较。
    """
    gaps = []
    for y, (al, ar) in pa.items():
        if y in pb:
            bl = pb[y][0] + adv
            gaps.append(bl - ar)
    if not gaps:
        return None
    g = np.array(gaps)
    return float(g.min()), float(g.mean()), int((g < 0).sum()), len(g)


def read_kern(font: TTFont) -> dict:
    """母版现有 kern 值（只看 PairPos）。"""
    out = {}
    if "GPOS" not in font:
        return out
    for lk in font["GPOS"].table.LookupList.Lookup:
        if lk.LookupType != 2:
            continue
        for s in lk.SubTable:
            sub = s.ExtSubTable if isinstance(s, ot.ExtensionSubst) else s
            if not isinstance(sub, ot.PairPos):
                continue
            if sub.Format == 1:
                for g1, ps in zip(sub.Coverage.glyphs, sub.PairSet):
                    for r in ps.PairValueRecord:
                        out[(g1, r.SecondGlyph)] = getattr(r.Value1, "XAdvance", 0) or 0
            elif sub.Format == 2:
                c1, c2 = sub.ClassDef1.classDefs, sub.ClassDef2.classDefs
                for g1 in sub.Coverage.glyphs:
                    r1 = sub.Class1Record[c1.get(g1, 0)]
                    for g2, cls in c2.items():
                        if cls < len(r1.Class2Record):
                            out[(g1, g2)] = getattr(r1.Class2Record[cls].Value1, "XAdvance", 0) or 0
    return out


def write_kern(font: TTFont, deltas: dict) -> int:
    """把三个 kern lookup 摊平成**一个**，再逐对写绝对值。

    母版把 kern 拆成 3 个 PairPos lookup（0 / 4 / 5），都挂在同一个 `kern` feature 上，
    OpenType 会依次累加。上一版分别给每个 lookup 加差值，等于同一对加了两三遍。
    摊平之后只剩一个 lookup，`deltas` 里的值就是最终值，不会重复。
    """
    gpos = font["GPOS"].table

    pairs: dict = {}
    kern_idx = []
    for i, lk in enumerate(gpos.LookupList.Lookup):
        if lk.LookupType != 2:
            continue
        kern_idx.append(i)
        for s in lk.SubTable:
            sub = s.ExtSubTable if hasattr(s, "ExtSubTable") else s
            if not isinstance(sub, ot.PairPos):
                continue
            if sub.Format == 1:
                for g1, ps in zip(sub.Coverage.glyphs, sub.PairSet):
                    for r in ps.PairValueRecord:
                        pairs[(g1, r.SecondGlyph)] = getattr(r.Value1, "XAdvance", 0) or 0
            elif sub.Format == 2:
                c1, c2 = sub.ClassDef1.classDefs, sub.ClassDef2.classDefs
                for g1 in sub.Coverage.glyphs:
                    r1 = sub.Class1Record[c1.get(g1, 0)]
                    for g2, cls in c2.items():
                        if cls < len(r1.Class2Record):
                            pairs[(g1, g2)] = getattr(r1.Class2Record[cls].Value1, "XAdvance", 0) or 0

    changed = 0
    for key, v in deltas.items():
        if pairs.get(key) != v:
            changed += 1
        pairs[key] = v

    # 只留第一个 kern lookup，其余从 LookupList 与 feature 里摘掉
    keep = kern_idx[0]
    gpos.LookupList.Lookup[keep].SubTable = [_to_format1(pairs, font)]
    gpos.LookupList.Lookup[keep].SubTableCount = 1
    drop = set(kern_idx[1:])
    # LookupList 重排：删掉多余 lookup，并把 feature 里的索引改到新位置
    remap, newl = {}, []
    for i, lk in enumerate(gpos.LookupList.Lookup):
        if i in drop:
            continue
        remap[i] = len(newl)
        newl.append(lk)
    gpos.LookupList.Lookup = newl
    gpos.LookupList.LookupCount = len(newl)
    for fr in gpos.FeatureList.FeatureRecord:
        if fr.FeatureTag == "kern":
            fr.Feature.LookupListIndex = sorted({remap[i] for i in fr.Feature.LookupListIndex if i in remap})
            fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
        else:
            fr.Feature.LookupListIndex = [remap[i] for i in fr.Feature.LookupListIndex if i in remap]
            fr.Feature.LookupCount = len(fr.Feature.LookupListIndex)
    return changed


def _to_format1(pairs: dict, font=None):
    by_first: dict[str, list] = {}
    for (g1, g2), v in pairs.items():
        by_first.setdefault(g1, []).append((g2, v))
    pp = ot.PairPos()
    pp.Format = 1
    pp.ValueFormat1 = 0x0004      # XAdvance
    pp.ValueFormat2 = 0
    pp.Coverage = ot.Coverage()
    order = font.getGlyphOrder() if font is not None else None
    keys = sorted(by_first, key=(order.index if order else None)) if order else sorted(by_first)
    pp.Coverage.glyphs = keys
    pp.PairSet = []
    for g1 in pp.Coverage.glyphs:
        ps = ot.PairSet()
        ps.PairValueRecord = []
        seq = by_first[g1]
        if order:
            seq = sorted(seq, key=lambda p: order.index(p[0]))
        else:
            seq = sorted(seq)
        for g2, v in seq:
            rec = ot.PairValueRecord()
            rec.SecondGlyph = g2
            rec.Value1 = ot.ValueRecord()
            rec.Value1.XAdvance = int(round(v))
            ps.PairValueRecord.append(rec)
        pp.PairSet.append(ps)
    pp.PairSetCount = len(pp.PairSet)
    return pp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--min-ink", type=float, default=40,
                    help="任何一对的带最小间距不小于这个值（upm 千分比，默认 40）")
    ap.add_argument("--tighten-ratio", type=float, default=0.0,
                    help="把宽于「同首字母中位 × 该系数」的对收回来（0 = 不收，试 1.6）")
    args = ap.parse_args()

    font = TTFont(args.source)
    upm = font["head"].unitsPerEm
    floor = args.min_ink * upm / 1000
    gs = font.getGlyphSet()
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    old = read_kern(font)

    letters = [c for c in LETTERS if ord(c) in cmap]
    flat = {}
    for c in letters:
        g = cmap[ord(c)]
        if g not in flat:
            flat[g] = flatten(gs, g)

    band_of = {g: bands(a) for g, a in flat.items() if len(a)}
    XMIN = {g: float(a[:, [0, 2]].min()) for g, a in flat.items() if len(a)}
    XMAX = {g: float(a[:, [0, 2]].max()) for g, a in flat.items() if len(a)}
    deltas, tight, missing = {}, [], []
    for a in letters:
        for b in letters:
            ga, gb = cmap[ord(a)], cmap[ord(b)]
            if ga not in flat or gb not in flat:
                continue
            cur = old.get((ga, gb), 0)
            r = band_gap(band_of[ga], band_of[gb], hmtx[ga][0] + cur)
            if r is None:
                continue
            mn, mean, overlap, n = r
            if overlap > 0 or mn < floor:
                # 每多重叠 1 单位，kern 涨 1 单位；同时保底 floor
                need = max(floor - mn, -mn + floor if mn < 0 else 0)
                deltas[(ga, gb)] = cur + need
                tight.append((a + b, mn, mean, overlap))
                if (ga, gb) not in old:
                    missing.append((a + b, mn, overlap))
            # 只往紧的方向修。母版里本来就松的对（HH、oo）保持原样——
            # 上一版加过「过松就压」的分支，把 FO/RO/SC/CO 的 kern 压到 −299，
            # 直接把这三个词弄成穿插，已删。

    # 第二轮：同首字母里明显偏宽的对收回。
    # 为什么需要：A 的右斜腿与圆体（C/G/O/Q）之间天然空一块，`AC` 182 而同字母
    # 中位才 69；这一层不是「碰撞」，是比例不匀，得靠相对量判断，不能用绝对阈值。
    if args.tighten_ratio > 0:
        by_first = {}
        for a in letters:
            for b in letters:
                ga, gb = cmap[ord(a)], cmap[ord(b)]
                if ga not in band_of or gb not in band_of:
                    continue
                cur = deltas.get((ga, gb), old.get((ga, gb), 0))
                r = band_gap(band_of[ga], band_of[gb], hmtx[ga][0] + cur)
                if r is not None:
                    by_first.setdefault(a, []).append((ga, gb, r[0], cur))
        n_loose = 0
        for a, items in by_first.items():
            med = sorted(x[2] for x in items)[len(items) // 2]
            cap = med * args.tighten_ratio
            for ga, gb, mn, cur in items:
                if mn <= cap:
                    continue
                # 只收母版已经有 kern 条目的对。没有条目的宽对是字形结构决定的
                # （F 的右上悬空、L 的右下空档、j 的左出），硬塞负 kern 会把两个
                # 字形推到一起——1.9 档试过，Fu/Fy/Lj 直接叠住。
                if (ga, gb) not in old:
                    continue
                # 硬底线：kern 后的 advance 不能小于前字自身墨宽 + 后字左空，
                # 否则后字会画进前字的怀里（1.9 档试过，Fu 的 advance 掉到 175，
                # 而 F 自己就宽 540，u 直接被 F 盖住）。
                # 底线只看「后字左缘不能压进前字墨迹」这一条，不用「整字宽 + floor」：
                # 斜边字（A/V/W）墨宽本来就撑满 advance，用整字宽当底线会让所有
                # A 系修正被挡掉（实测 AC 收不动）。真正要防的是后字画进前字怀里。
                cand = cur - (mn - cap)
                if hmtx[ga][0] + cand < XMAX[ga] - XMIN[ga]:
                    cand = (XMAX[ga] - XMIN[ga]) - hmtx[ga][0]
                if cand >= cur:
                    continue
                deltas[(ga, gb)] = cand
                n_loose += 1
        print(f"按同首字母中位 ×{args.tighten_ratio} 收回 {n_loose} 对")

    print(f"压紧 {len(tight)} 对（带最小低于 {floor:.0f} 或有水平重叠），"
          f"母版无条目 {len(missing)} 对")
    for p, mn, mean, ov in sorted(tight, key=lambda r: r[1])[:10]:
        print(f"    {p}  带最小 {mn:7.1f}  带平均 {mean:7.1f}  重叠带 {ov}")
    for p, mn, ov in sorted(missing, key=lambda r: r[1])[:8]:
        print(f"    [缺条目] {p}  带最小 {mn:7.1f}  重叠带 {ov}")

    changed = write_kern(font, deltas)
    print(f"改写 {changed} 条 kern（只动已有的对，mark/mkmk 与 GSUB 未碰）")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    font.save(args.output)
    print(f"写出 {args.output}（{args.output.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
