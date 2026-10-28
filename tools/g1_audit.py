"""量轮廓的切线连续性（G1）：相邻两段在共享锚点处的切向夹角。

为什么这个量能代表"平不平滑"
--------------------------
二次贝塞尔在锚点处若两侧切向不共线，放大后就是一个折角。折角多了，肉眼看到的就是
"边缘一波一波"、"端头被压成多边形"。`curve_fit_g1.py` 已经记过：旧 RDP 拟合在
75 段里有 63 段接头不连续（中位 7.6°），这就是当时那批字形看起来粗糙的原因。

判定口径
--------
* `p50/p95/max`：所有锚点（含真角点）的角差分布。
* `n_gt2 / n_gt5`：角差超过 2°/5° 的锚点数——2° 在 1000 upm 上是 0.6 单位的偏差，
  肉眼已可见。
* 真角点（设计上故意断开的角）会拉高 max，所以同时报"平滑锚点比例"。

用法：
    python3 tools/g1_audit.py 字体.ttf --chars 九乙了子也包必電
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _contours(font, gname):
    """取字形轮廓，每段展开成 (起点, 控制点列表, 终点, 类型)。"""
    glyph = font["glyf"][gname]
    coords, ends, flags = glyph.getCoordinates(font["glyf"])
    out = []
    start = 0
    for end in ends:
        pts = [(float(coords[i][0]), float(coords[i][1]), bool(flags[i]))
               for i in range(start, end + 1)]
        out.append(pts)
        start = end + 1
    return out


def _segments(pts):
    """把一条闭合轮廓拆成段：[(p0, ctrl, p1)]，ctrl 为 None 表示直线。

    TrueType 的约定：两个 on-curve 之间如果有 1 个 off-curve，就是一端二次贝塞尔；
    有多个 off-curve 时，相邻 off-curve 的中点是隐含的 on-curve。
    """
    n = len(pts)
    # 先确定起始 on-curve 点
    first_on = next((i for i in range(n) if pts[i][2]), None)
    if first_on is None:
        return []
    seq = pts[first_on:] + pts[:first_on]
    segs = []
    cur = seq[0][:2]
    i = 1
    pending_off = []
    while i <= len(seq):
        p = seq[i % len(seq)]
        if p[2]:
            if pending_off:
                if len(pending_off) == 1:
                    segs.append((cur, [pending_off[0]], p[:2]))
                else:
                    # 多个 off-curve：相邻中点作为隐含锚点
                    for k in range(len(pending_off)):
                        nxt = (p[:2] if k == len(pending_off) - 1
                               else ((pending_off[k][0] + pending_off[k + 1][0]) / 2,
                                     (pending_off[k][1] + pending_off[k + 1][1]) / 2))
                        segs.append((cur, [pending_off[k]], nxt))
                        cur = nxt
                    pending_off = []
                    cur = p[:2]
                    i += 1
                    if i > len(seq):
                        break
                    continue
                cur = p[:2]
            else:
                segs.append((cur, None, p[:2]))
                cur = p[:2]
            pending_off = []
        else:
            pending_off.append(p[:2])
        i += 1
        if i > len(seq):
            break
    return [s for s in segs if s[0] != s[2]]


def _tangent_out(seg):
    """段在**起点**处的切向。"""
    p0, ctrl, p1 = seg
    q = ctrl[0] if ctrl else p1
    dx, dy = q[0] - p0[0], q[1] - p0[1]
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else None


def _tangent_in(seg):
    """段在**终点**处的切向。"""
    p0, ctrl, p1 = seg
    q = ctrl[-1] if ctrl else p0
    dx, dy = p1[0] - q[0], p1[1] - q[1]
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else None


def _turn(a, b):
    if a is None or b is None:
        return 0.0
    c = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(c))


def audit(font, gname):
    rows = []
    for pts in _contours(font, gname):
        segs = _segments(pts)
        if len(segs) < 2:
            continue
        for i, seg in enumerate(segs):
            prev = segs[i - 1]
            rows.append(_turn(_tangent_in(prev), _tangent_out(seg)))
    return rows


def summarize(font, chars):
    cmap = font.getBestCmap()
    out = []
    for ch in chars:
        g = cmap.get(ord(ch))
        if g is None:
            continue
        turns = audit(font, g)
        if not turns:
            continue
        import numpy as np
        a = np.asarray(turns)
        out.append(dict(
            ch=ch, n=len(a), p50=float(np.median(a)),
            p95=float(np.percentile(a, 95)), mx=float(a.max()),
            gt2=int((a > 2).sum()), gt5=int((a > 5).sum()),
            smooth=float((a <= 2).mean()),
        ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("font")
    ap.add_argument("--chars", default="九乙了子也包必電")
    args = ap.parse_args()
    font = TTFont(args.font)
    rows = summarize(font, list(args.chars))
    print(f'{"字":<3}{"锚点":>5}{"p50":>7}{"p95":>7}{"max":>7}{">2°":>5}{">5°":>5}{"平滑率":>8}')
    for r in rows:
        print(f'{r["ch"]:<3}{r["n"]:>5}{r["p50"]:>7.2f}{r["p95"]:>7.2f}'
              f'{r["mx"]:>7.2f}{r["gt2"]:>5}{r["gt5"]:>5}{r["smooth"]*100:>7.1f}%')
    tot = [r for r in rows]
    if tot:
        print(f'\n合计锚点 {sum(r["n"] for r in tot)}，'
              f'>2° {sum(r["gt2"] for r in tot)}，>5° {sum(r["gt5"] for r in tot)}，'
              f'平均平滑率 {sum(r["smooth"] for r in tot)/len(tot)*100:.1f}%')


if __name__ == "__main__":
    main()
