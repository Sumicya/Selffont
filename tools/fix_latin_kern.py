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


def ink_gap(a: np.ndarray, b: np.ndarray) -> float:
    """两组线段之间的最小距离（负值表示真重叠）。"""
    a0 = a[:, 0:2][:, None, :]; a1 = a[:, 2:4][:, None, :]
    b0 = b[:, 0:2][None, :, :]; b1 = b[:, 2:4][None, :, :]

    def pt_seg(p, s0, s1):
        d = s1 - s0
        L = (d * d).sum(-1)
        L = np.where(L == 0, 1, L)
        t = np.clip(((p - s0) * d).sum(-1) / L, 0, 1)
        return np.sqrt(((p - (s0 + t[..., None] * d)) ** 2).sum(-1))

    # 端点投影不足以判「线段相交」：额外用一次分离轴判定
    cross = (a1[..., 0] - a0[..., 0]) * (b0[..., 1] - a0[..., 1]) - \
            (a1[..., 1] - a0[..., 1]) * (b0[..., 0] - a0[..., 0])
    cross2 = (a1[..., 0] - a0[..., 0]) * (b1[..., 1] - a0[..., 1]) - \
             (a1[..., 1] - a0[..., 1]) * (b1[..., 0] - a0[..., 0])
    cross3 = (b1[..., 0] - b0[..., 0]) * (a0[..., 1] - b0[..., 1]) - \
             (b1[..., 1] - b0[..., 1]) * (a0[..., 0] - b0[..., 0])
    cross4 = (b1[..., 0] - b0[..., 0]) * (a1[..., 1] - b0[..., 1]) - \
             (b1[..., 1] - b0[..., 1]) * (a1[..., 0] - b0[..., 0])
    hit = (cross * cross2 < 0) & (cross3 * cross4 < 0)
    if hit.any():
        return -1.0
    return float(min(pt_seg(a0, b0, b1).min(), pt_seg(a1, b0, b1).min(),
                     pt_seg(b0, a0, a1).min(), pt_seg(b1, a0, a1).min()))


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
    """只改现有 PairPos 里已有的对；Format 2 的类对展开成 Format 1 才能逐对改。

    `deltas`: {(g1, g2): 该加多少}。返回改了多少条。
    """
    changed = 0
    for lk in font["GPOS"].table.LookupList.Lookup:
        if lk.LookupType != 2:
            continue
        for si, s in enumerate(list(lk.SubTable)):
            if s.Format == 2:
                # 类对 → 逐对：ClassDef 里出现的所有组合都要摊开
                pairs = {}
                c1, c2 = s.ClassDef1.classDefs, s.ClassDef2.classDefs
                for g1 in s.Coverage.glyphs:
                    r1 = s.Class1Record[c1.get(g1, 0)]
                    for g2, cls in c2.items():
                        if cls < len(r1.Class2Record):
                            v = getattr(r1.Class2Record[cls].Value1, "XAdvance", 0) or 0
                            d = deltas.get((g1, g2))
                            pairs[(g1, g2)] = v if d is None else d
                            if d is not None:
                                changed += 1
                lk.SubTable[si] = _to_format1(pairs, font)
            elif s.Format == 1:
                hit = 0
                # 先把整张表摊成字典，改完再编回去（新增条目要重排 Coverage）
                pairs = {}
                pairs_by_first = {}
                for g1, ps in zip(s.Coverage.glyphs, s.PairSet):
                    pairs_by_first[g1] = set()
                    for r in ps.PairValueRecord:
                        pairs[(g1, r.SecondGlyph)] = getattr(r.Value1, "XAdvance", 0) or 0
                for (g1, g2), v in deltas.items():
                    if g1 not in pairs_by_first and g1 not in s.Coverage.glyphs:
                        pairs_by_first.setdefault(g1, set())
                    if (g1, g2) in pairs or g1 in pairs_by_first:
                        if pairs.get((g1, g2)) != v:
                            pairs[(g1, g2)] = v
                            hit += 1
                if hit:
                    lk.SubTable[si] = _to_format1(pairs, font)
                changed += hit
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
                    help="任何一对的真实最小墨距不小于这个值（upm 千分比，默认 40）")
    ap.add_argument("--max-ink", type=float, default=200,
                    help="超过这个值的不收（母版本来就松的对保持原样，默认 200）")
    args = ap.parse_args()

    font = TTFont(args.source)
    upm = font["head"].unitsPerEm
    floor = args.min_ink * upm / 1000
    ceil = args.max_ink * upm / 1000
    gs = font.getGlyphSet()
    cmap, hmtx = font.getBestCmap(), font["hmtx"]
    old = read_kern(font)

    letters = [c for c in LETTERS if ord(c) in cmap]
    flat = {}
    for c in letters:
        g = cmap[ord(c)]
        if g not in flat:
            flat[g] = flatten(gs, g)
    XMIN = {g: float(a[:, [0, 2]].min()) for g, a in flat.items() if len(a)}
    XMAX = {g: float(a[:, [0, 2]].max()) for g, a in flat.items() if len(a)}

    deltas, tight, loose, missing = {}, [], [], []
    for a in letters:
        for b in letters:
            ga, gb = cmap[ord(a)], cmap[ord(b)]
            if ga not in flat or gb not in flat:
                continue
            adv = hmtx[ga][0] + old.get((ga, gb), 0)
            moved = flat[gb].copy()
            moved[:, [0, 2]] += adv
            gap = ink_gap(flat[ga], moved)
            if gap < floor:
                # kern_new 只取决于两侧留白：rsb + lsb + kern = floor
                base_bearing = (hmtx[ga][0] - XMAX[ga]) + XMIN[gb]
                deltas[(ga, gb)] = floor - base_bearing
                tight.append((a + b, gap))
                if (ga, gb) not in old:
                    missing.append((a + b, gap))
            elif gap > ceil and (ga, gb) in old:
                deltas[(ga, gb)] = old[(ga, gb)] - (gap - ceil)
                loose.append((a + b, gap))

    print(f"压紧 {len(tight)} 对（低于 {floor:.0f}），放松 {len(loose)} 对（高于 {ceil:.0f}），"
          f"母版无条目 {len(missing)} 对")
    for p, g in sorted(tight, key=lambda r: r[1])[:8]:
        print(f"    {p}  原墨距 {g:.1f}")
    for p, g in sorted(missing, key=lambda r: r[1])[:8]:
        print(f"    [缺条目] {p}  墨距 {g:.1f}")

    changed = write_kern(font, deltas)
    print(f"改写 {changed} 条 kern（只动已有的对，mark/mkmk 与 GSUB 未碰）")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    font.save(args.output)
    print(f"写出 {args.output}（{args.output.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
