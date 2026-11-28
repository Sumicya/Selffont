"""删掉挂在字形外面的孤立小碎块（母版自带的杂质，目前全库只有 `日` 一个）。

问题长什么样
------------
`日` 在手机上右上角会多出一个小圈。它不是笔画，是母版带的一条多余闭合轮廓。
四条轮廓的实测数据：

| 轮廓 | 点数 | 面积 | bbox | 位置 |
|---|---|---|---|---|
| 0 | 9 | **4,290** | x[773,828] y[**788,833**] | 字格 80%,81%（右上角） |
| 1 | 34 | 432,945 | x[201,802] y[-10,**763**] | 外框 |
| 2 | 15 | 107,594 | x[263,737] y[414,703] | 中横 |
| 3 | 16 | 82,770 | x[263,737] y[49,354] | 底横 |

轮廓 1 是外框，最高只到 y=763；轮廓 0 整条都在 y=788~833，**离外框还有 25 单位空隙**。
字形要画的三条（外框 + 中横 + 底横）已经齐了，第 4 条纯属挂件。

对照 `目` 同样的 4 条轮廓：面积 436,832 / 57,236 / 29,106 / 52,487，全部贴在外框内部、
数量级一致——那才是正常的「外框 + 三条横」。

同一种碎块出现了 5 次（`日` `论` `攺` `䐴` `饦`）
-----------------------------------------------
把每个字里被怀疑的那条轮廓**单独画出来**（去掉其它轮廓），5 个字的碎块长得一模一样：

| 字 | 碎块位置 | 尺寸 | 点数 | 离主体 |
|---|---|---|---|---|
| 日 | 右上角外 | 55×45 | 9 | 25 |
| 论 | 左下角外 | 52×55 | 9 | 18 |
| 攺 | 左下角外 | 55×52 | 9 | 13 |
| 䐴 | 左侧外 | 75×55 | 9 | 16 |
| 饦 | 左下角外 | 60×62 | 8 | 30 |

归一化形状也一致：8–9 点多边形，末尾带一个内缩点（收笔时自交留下的小环）。
这不是任何笔画末梢该有的样子，是母版生成时溅出来的同一颗碎块，随机落在字形附近。

判据（三条同时满足，缺一不删）
------------------------------
1. **点数 8–9**：全库扫描下来这一档只有这 5 个命中，没有误伤。
2. **尺寸 30–80 单位**：宽和高都落在这个区间（0.03–0.08 em）。
3. **与最近的其它轮廓有空隙 0.5–40 单位**：这个空隙是碎块与笔画之间的脱离间隙。
   必须用「到最近的**单个**轮廓」算距离，不能用「到其余轮廓的并集 bbox」——
   `论` 的 `仑` 一直伸到 y=−41，把并集撑大了，那颗碎块就会被判成「贴着」而漏掉
   （第一版就是这么漏的）。

**不做位置判断**：碎块落在右上角（`日`）、左下角（`论`/`攺`/`饦`）、左侧（`䐴`）都有，
按角落筛会漏掉一半。

用法
----
    python tools/drop_stray_ring.py 母版.ttf -o 本版.ttf
    python tools/drop_stray_ring.py 母版.ttf -o 本版.ttf --dry-run
    python tools/drop_stray_ring.py 母版.ttf -o 本版.ttf --scan   # 全库扫一遍看还有没有
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont

DEFAULT_ONLY = ""   # 空 = 全库自动按判据处理


def cjk(cp):
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF


def rings_of(g):
    c = g.coordinates
    out, st = [], 0
    for e in g.endPtsOfContours:
        out.append(np.array([[c[i][0], c[i][1]] for i in range(st, e + 1)], float))
        st = e + 1
    return out


def area(r):
    return abs(float(np.sum(r[:-1, 0] * r[1:, 1] - r[1:, 0] * r[:-1, 1]))) / 2


def bbox(r):
    return r[:, 0].min(), r[:, 1].min(), r[:, 0].max(), r[:, 1].max()


def gap(a, b):
    """两个 bbox 的距离。>0 表示分开。"""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return float(np.hypot(dx, dy))


def ptdist(a, b):
    """两条折线最近两点的距离。bbox 相交时 gap=0，这个还能量出真空隙。"""
    d = 1e9
    for p in a:
        m = float(np.min(np.hypot(b[:, 0] - p[0], b[:, 1] - p[1])))
        if m < d:
            d = m
    return d


def stray_rings(g, max_share=0.04, min_gap=0.5, max_gap=40.0):
    """返回该字形里应删的轮廓下标。

    判据：8–9 点 + 尺寸 30–80 单位 + 与最近轮廓的空隙在 0.5–40 单位之间。
    """
    rs = rings_of(g)
    if len(rs) < 2:
        return [], rs
    ars = [area(r) for r in rs]
    kill = []
    for i, r in enumerate(rs):
        others = [j for j in range(len(rs)) if j != i]
        oa = sum(ars[j] for j in others)
        if oa <= 0 or ars[i] / oa > max_share:
            continue
        rb = bbox(r)
        w, h = rb[2] - rb[0], rb[3] - rb[1]
        if not (30 <= w <= 100 and 30 <= h <= 100):
            continue
        # ★ 分支二（2026-11-27，主人指出「谚」左下角那颗）：整条轮廓落在字身框外
        #   （基线以下 / 顶线以上 / 左右框外）。正常汉字笔画不会**完全**落在字身框外
        #    yet 只有 30–80 单位大。这一类不能套用分支一的「点数 8–9」和「空隙 0.5–40」：
        #   它们往往贴着主笔画末端（bbox 相交 → 空隙 0），且收笔自交环多两个点（10–11 点）。
        #   「谚」U+8C1A 的 r6 就是：11 点、52×49、y[-52,-3]、空隙 0.0、占比 0.79%。
        #   全库扫描这一分支另命中 14 个同类（㓰  㮣  墫 巽 挀  瑨 甆 謜 钾 锂 鶌），
        #   与分支一的 5 个零重叠；非汉字码位（如 U+2592/2593 的 shade 符号也落在基线下）
        #   由 main() 的 cjk() 过滤挡住，不处理。
        if rb[3] < 0 or rb[1] > 880 or rb[2] < 0 or rb[0] > 1000:
            kill.append(i)
            continue
        # ★ 分支三（2026-11-27，主人指出「让」左下角那颗）：bbox 和讠的钩子相交
        #   （gap=0）所以分支一漏；yMax=34 没完全在基线以下所以分支二漏。
        #   点到点 32 单位、10 点、94×83。只收左下（yMin<0、yMax<50、xMax<280），
        #   全库这一支 10 个（让 谦 㓪 䥻 䦀 钛 钜 ＋ 已在分支二的 甆钾锂）。
        if (8 <= len(r) <= 12 and rb[1] < 0 and rb[3] < 50 and rb[2] < 280
                and 5 < min(ptdist(r, rs[j]) for j in others) < 40):
            kill.append(i)
            continue
        # 分支一（原判据）：游离在字形外的小圈。
        if len(r) > 9 or w > 80 or h > 80:
            continue
        # 到最近的**单个**轮廓，不是到并集
        nearest = min(gap(rb, bbox(rs[j])) for j in others)
        if not (min_gap < nearest < max_gap):
            continue
        kill.append(i)
    return kill, rs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--only", default=DEFAULT_ONLY,
                    help="只处理这些字（默认空 = 全库按判据自动处理）")
    ap.add_argument("--scan", action="store_true",
                    help="全库扫一遍，列出所有命中判据的字（不写文件）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    font = TTFont(args.source)
    glyf = font["glyf"]
    cmap = font.getBestCmap()

    seen = set()
    targets = []
    for cp in sorted(cmap):
        ch = chr(cp)
        if not cjk(cp) or cmap[cp] in seen:
            continue
        if not args.scan and args.only and ch not in args.only:
            continue
        seen.add(cmap[cp])
        g = glyf[cmap[cp]]
        if g.numberOfContours < 2:
            continue
        kill, rs = stray_rings(g)
        if not kill:
            continue
        targets.append((cp, cmap[cp], kill, [round(area(rs[i])) for i in kill],
                        len(rs), [len(rs[i]) for i in kill]))

    print(f"命中 {len(targets)} 个字")
    for cp, gn, kill, ars, nring, npts in targets:
        print(f"  {chr(cp)} U+{cp:04X} {gn:12s} 轮廓 {nring} 条 → 删 {kill} "
              f"（面积 {ars} · 点数 {npts}）")
    if not targets:
        return 0
    if args.scan or args.dry_run:
        return 0

    for cp, gn, kill, *_ in targets:
        g = glyf[gn]
        c, f = g.coordinates, g.flags
        bounds, st = [], 0
        for e in g.endPtsOfContours:
            bounds.append((st, e))
            st = e + 1
        keep = [i for i in range(len(bounds)) if i not in kill]
        new_c, new_f, new_ends = [], [], []
        for i in keep:
            s, e = bounds[i]
            new_c.extend([tuple(c[j]) for j in range(s, e + 1)])
            new_f.extend([f[j] for j in range(s, e + 1)])
            new_ends.append(len(new_c) - 1)
        g.coordinates = type(g.coordinates)(new_c)
        g.flags = bytearray(new_f)
        g.endPtsOfContours = new_ends
        g.numberOfContours = len(new_ends)
        g.recalcBounds(glyf)

    # ★ lsb 必须跟着 xMin 走。删掉的那条碎块可能就是整个字形最左边的墨迹：
    #   `䐴` 的 xMin 从 34 变成 125，`攺` 从 44 变成 112，而 hmtx 的 lsb 还停在旧值。
    #   advance 不动（那 5 个字都是 1000，全角字格不该因为删了一颗碎块就变宽）。
    #   不修这一步，验收里的「lsb ≠ xMin 的字 0 个」就会红。
    hmtx = font["hmtx"]
    for cp, gn, *_ in targets:
        g = glyf[gn]
        if g.numberOfContours <= 0:
            continue
        aw, lsb = hmtx[gn]
        if lsb != g.xMin:
            hmtx[gn] = (aw, g.xMin)

    font.save(args.output)
    print(f"写出 {args.output}（{args.output.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
