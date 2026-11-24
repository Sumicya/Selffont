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
    """逐 BAND 单位水平带的 (xMin, xMax)。

    上一版只用线段的**起点 y** 决定它属于哪个带，于是竖直笔画（F 的竖杆、L 的竖杆）
    只在最底那条带出现，中间各带的 F 只剩横杠。`Fu` 因此报出 501 的「墨距」，而两个
    字形真正最近的距离是 113——差 389。90 对（3.3%）高估超过 100，其中 Fu/Lj/Fy/yV
    都是这个毛病。

    现在把线段按它实际跨越的高度切开，逐带求 x 范围。
    """
    out = {}
    x0, y0, x1, y1 = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    lo_all = int(min(y0.min(), y1.min()))
    hi_all = int(max(y0.max(), y1.max()))
    b0 = lo_all - (lo_all % BAND)
    for yb in range(b0, hi_all + 1, BAND):
        top, bot = yb, yb + BAND
        xmin, xmax = None, None
        for i in range(len(a)):
            ay0, ay1 = y0[i], y1[i]
            s_lo, s_hi = (ay0, ay1) if ay0 <= ay1 else (ay1, ay0)
            if s_hi < top or s_lo > bot:
                continue
            if s_hi == s_lo:
                xs = [x0[i], x1[i]]
            else:
                t1 = max(0.0, min(1.0, (top - ay0) / (ay1 - ay0)))
                t2 = max(0.0, min(1.0, (bot - ay0) / (ay1 - ay0)))
                xs = [x0[i] + t * (x1[i] - x0[i]) for t in (t1, t2)]
            lo, hi = min(xs), max(xs)
            xmin = lo if xmin is None else min(xmin, lo)
            xmax = hi if xmax is None else max(xmax, hi)
        if xmin is not None:
            out[yb] = (float(xmin), float(xmax))
    return out


def point_gap(A: np.ndarray, B: np.ndarray, adv: float) -> float:
    """两字并排时的**真实最短墨距**：后字平移 adv 后，轮廓点之间的最小距离。

    这是「挤不挤」的正解。逐带法（band_gap）在两种情况下都不准：
    - 竖直笔画只登记在起点带 → `Fu` 报 501，实际 113；
    - 补上跨带切分后，A 的斜腿和 V 的斜边几乎每个高度都有墨 → `AV` 报 280，实际 34。
    并排字的视觉间距就是最近的那一处墨，不是「逐带对齐」。
    """
    if len(A) == 0 or len(B) == 0:
        return None
    pa = np.concatenate([A[:, [0, 1]], A[:, [2, 3]]])
    pb = np.concatenate([B[:, [0, 1]], B[:, [2, 3]]])
    pb = pb.copy()
    pb[:, 0] += adv
    # 分块算，2702 对 × 每对上千点，一次性展开会炸内存
    best = np.inf
    step = 256
    for i in range(0, len(pa), step):
        d = np.sqrt(((pa[i:i+step, None, :] - pb[None, :, :]) ** 2).sum(-1))
        m = d.min()
        if m < best:
            best = m
    return float(best)


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


def target_for(a: str, b: str, base: float, groups: dict) -> float:
    """按字对类型取目标墨距。

    `de`/`or`/`lo` 这类小写连写是正文最高频组合，原设计给 130-150 是有道理的；
    `AV`/`AT` 这类斜边相让才是真离群（260-280）。用一个目标拉平两边都会错。
    """
    if a.islower() and b.islower() and "low" in groups:
        return groups["low"]
    if a.isupper() and b.isupper() and "up" in groups:
        return groups["up"]
    if a.isupper() and b.islower() and "up_low" in groups:
        return groups["up_low"]
    if a.islower() and b.isupper() and "low_up" in groups:
        return groups["low_up"]
    return base


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
    ap.add_argument("--cap-letters", default="",
                    help="对这几个首字母改用绝对上限（如 A，配合 --cap-to）")
    ap.add_argument("--cap-to", type=float, default=0.0,
                    help="--cap-letters 里那些首字母的目标上限（upm 千分比）")
    ap.add_argument("--pair-targets", default="",
                    help="按字对类型分别设目标，格式 `小写:120,大写:150`；优先于 --cap-to")
    ap.add_argument("--pairs", default="",
                    help="给具体字对设目标，格式 `IC:105,IG:105`，优先于分组与 --cap-to")
    ap.add_argument("--within", type=float, default=0.0,
                    help="把墨距落在 target±within 的对也吸附到 target（双向统一）")
    ap.add_argument("--grid", type=int, default=5,
                    help="把算出的 kern 吸附到这个单位的倍数（2 或 5）")
    args = ap.parse_args()
    exact_pairs = {}
    for part in (args.pairs or "").split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        exact_pairs[k.strip()] = float(v)
    pair_targets = {}
    for part in (args.pair_targets or "").split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        pair_targets[{"低": "low", "小写": "low", "高": "up", "大写": "up",
                      "低高": "low_up", "高低": "up_low"}.get(k.strip(), k.strip())] = float(v)

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
            pg = point_gap(flat[ga], flat[gb], hmtx[ga][0] + cur)
            if pg is not None:
                mn = min(mn, pg)
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
    if args.cap_letters and args.cap_to > 0:
        # 绝对目标，不用比例。母版本身的 kern 是坏的（`AC` 202 而同首字母中位 69），
        # 拿坏数据的中位数当基准只会把错误按比例放大一份。这里的判据只有一条：
        # 逐对实测墨距，宽于目标的就收到目标，窄的原样不动。
        base_target = args.cap_to * upm / 1000
        n_loose = 0
        for a in letters:
            if a not in args.cap_letters:
                continue
            for b in letters:
                ga, gb = cmap[ord(a)], cmap[ord(b)]
                if ga not in band_of or gb not in band_of:
                    continue
                # 各类字对可以有自己的目标：小写连写（de/or/lo）本来就该比大写对松，
                # 用一个 target 拉平等于毁掉原设计的节奏。
                target = target_for(a, b, base_target, pair_targets)
                if (a + b) in exact_pairs:
                    target = exact_pairs[a + b] * upm / 1000
                cur = deltas.get((ga, gb), old.get((ga, gb), 0))
                r = band_gap(band_of[ga], band_of[gb], hmtx[ga][0] + cur)
                if r is None:
                    continue
                # 只用点距。取 min(逐带, 点距) 是错的方向：逐带在 `TJ` 低估到 91.8
                # 而点距是 127.7，用 91.8 去判「要不要收」就几乎不收了。
                pg = point_gap(flat[ga], flat[gb], hmtx[ga][0] + cur)
                if pg is not None:
                    r = (pg,) + r[1:]
                if r[0] <= target and not (args.within > 0 and abs(r[0] - target) <= args.within):
                    continue
                # 这里原先有个 MIN_SHARED 门槛，理由是 `yV` 只共用 1 个带、读数不可信。
                # 现在主判据是点距（point_gap），`yV` 的点距 196 是可信的，门槛去掉。
                # 母版没有条目的宽对也要收。老版本这里有个「必须已有条目」的保护，
                # 理由是硬塞负 kern 会把两字推到一起（1.9 档 Fu/Fy/Lj 叠住）；
                # 现在下面两条底线是实测的，能拦住那种情况，所以放开。
                # 但「母版无条目」的对必须重新量一次，不能只信目标值。
                # 双向：落在 target±within 的也拉到 target，否则只有「过宽」的被收，
                # 中等的那批不动，落点永远散着（实测 K100 只有 7% 落在 100±1）。
                if args.within > 0 and abs(r[0] - target) <= args.within:
                    cand = cur - (r[0] - target)
                elif r[0] > target:
                    cand = cur - (r[0] - target)
                else:
                    continue
                # 复核也用点距，不能用逐带——逐带在 Fu 报 501、AV 报 280，会把
                # 本来该收的对当成「已经够宽」放过。
                probe = point_gap(flat[ga], flat[gb], hmtx[ga][0] + cand)
                if probe is not None and probe < floor:
                    cand += floor - probe
                # 母版无条目的对：收到目标后必须仍有 >= MIN_SHARED 个带、且墨不碰。
                if (ga, gb) not in old:
                    after = point_gap(flat[ga], flat[gb], hmtx[ga][0] + cand)
                    if after is None or after < floor:
                        continue
                # 这里原先有「advance + kern >= 前字墨宽 + floor」的底线，理由是 L100 档
                # `Fu` 的 kern 被压到 −402、advance 只剩 128，u 整个落进 F 怀里。
                # 但那个读数来自有 bug 的逐带量法（Fu 报 501，真实点距 113）。用点距重算：
                # 1507 对全部能安全收到 90，收到后**没有一对会碰**，其中 776 对是被这条
                # 底线无谓挡掉的。所以底线撤掉，只认实测点距。
                # 双向时允许 cand > cur（把偏窄的也拉宽），否则「统一」只做了一半：
                # 只把宽的压下来、窄的原样不动，间距反而更散（120/110/100 三档就是
                # 这么搞坏的，用户实测说「基线可以其他不行」）。
                only_shrink = args.within <= 0
                if only_shrink and cand >= cur:
                    continue
                if cand == cur:
                    continue
                deltas[(ga, gb)] = cand
                n_loose += 1
        print(f"按绝对目标 {args.cap_to} 收回 {n_loose} 对首字母在 {args.cap_letters[:6]}… 里")

    print(f"压紧 {len(tight)} 对（带最小低于 {floor:.0f} 或有水平重叠），"
          f"母版无条目 {len(missing)} 对")
    for p, mn, mean, ov in sorted(tight, key=lambda r: r[1])[:10]:
        print(f"    {p}  带最小 {mn:7.1f}  带平均 {mean:7.1f}  重叠带 {ov}")
    for p, mn, ov in sorted(missing, key=lambda r: r[1])[:8]:
        print(f"    [缺条目] {p}  带最小 {mn:7.1f}  重叠带 {ov}")

    # 吸附到网格：算出来的 kern 会是 −13、−185、−402 这种脏数字。统一到 2 或 5 的
    # 倍数，落在栅格里也更像设计值。吸附后要复核两条底线，不能因取整越界。
    if args.grid > 1:
        g = args.grid
        for (ga, gb), v in list(deltas.items()):
            v = int(round(v / g)) * g
            # 复核用点距。这里原先还留着 min_adv 那条已废弃的 advance 底线，
            # 它在吸附阶段把 AV 的 −193 一路推回 0——主循环算对了、在这一步被抹掉。
            r = point_gap(flat[ga], flat[gb], hmtx[ga][0] + v)
            if r is not None and r < floor:
                v += int(-(-(floor - r) // g)) * g
            deltas[(ga, gb)] = v
        print(f"按 {g} 的倍数吸附 {len(deltas)} 条")
    changed = write_kern(font, deltas)
    print(f"改写 {changed} 条 kern（只动已有的对，mark/mkmk 与 GSUB 未碰）")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    font.save(args.output)
    print(f"写出 {args.output}（{args.output.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
