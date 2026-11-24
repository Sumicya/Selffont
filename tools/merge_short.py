"""去多余点：删掉过短的碎段留下的接缝点。

母版为什么会碎
--------------
母版轮廓是「描边 → 道格拉斯-普克简化 → 三次贝塞尔拟合 → 拆二次曲线」四步下来的
（见 `tools/smooth_outline.py` 的说明）。最后一步「拆二次」按误差逐段细分：一条弧被
切成多少段由误差决定，跟「看起来需不需要」无关，于是直边附近会切出一堆只有几个
单位长的碎段。屏幕上就是「日 的右上角拐到左下角」那一串小点。

实测母版（upm 1000，字格 1000）：

| 段长 | 段数 | 占比 |
|---|---|---|
| ≤2 单位 | 25,929 | 0.4% |
| 2~4 | 116,528 | 1.7% |
| 4~8 | 407,157 | 6.1% |
| 8~15 | 969,679 | 14.6% |
| 15~25 | 1,332,875 | 20.0% |
| 25~40 | 1,288,272 | 19.3% |
| >40 | 2,520,793 | 37.8% |

短于 8 单位（0.8% em，800 px 渲染下不到 1 px）的段共 1,519,592 个。

关键约束：**只删点，绝不重建**
------------------------------
上一版栽在这里：把环解析成「on/off 严格交替」再写回，点数不减反增
（`exclam` 22 → 28）。原因是母版用「连续 off 点 + 隐含中点」编码，一条圆角只要 4 个
真 on 点加 8 个真 off 点；一展开成交替写法就要 8 个 on 点加 8 个 off 点。

所以这里**只在原数组上做删除**：算出要删的下标，`np.delete` 掉，其它点一个不动、
顺序一个不改。点数只减不增是构造保证的，不靠事后检查。

判据（硬要求，不许放宽）
------------------------
1. **只删点**：坐标数组原样保留被留下的点，flags 同理。
2. **形状实测把关**：新旧轮廓各展成稠密折线，算**点到线段**的双向最大距离
   （不是点到点——采样疏密不同会把同一条曲线算成差几十单位，实测同一外框被判 205）。
   超过 `--tol` 的字形**整个回退**。
3. **真折角不动**：相邻三点的转角超过 `--corner`（默认 35°）的中间点强制保留。
4. **不删控制点**：只删 on-curve 点里夹在共线/近共线之间的那些，以及零长度重复点。

用法
----
    python tools/merge_short.py 母版.ttf -o 本版.ttf
    python tools/merge_short.py 母版.ttf -o 本版.ttf --min-len 12
    python tools/merge_short.py 母版.ttf -o 本版.ttf --dry-run
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import flagOnCurve

DENSE = 6


def ring_slice(g, start, end):
    """环 → 坐标数组 (N,2)、on 掩码 (N,)。"""
    c = g.coordinates
    f = g.flags
    pts = np.array([[float(c[i][0]), float(c[i][1])] for i in range(start, end + 1)])
    on = np.array([bool(f[i] & flagOnCurve) for i in range(start, end + 1)])
    return pts, on


def densify(pts, on, step=DENSE):
    """环 → 稠密折线。按 TrueType 规则：连续 off 之间补隐含中点。"""
    n = len(pts)
    if n < 2:
        return pts.astype(float)
    s = int(np.argmax(on)) if not on.all() else 0
    idx = [(s + k) % n for k in range(n)]
    out = [pts[idx[0]]]
    k = 1
    while k <= n:
        i = idx[k % n]
        if on[i]:
            out.append(pts[i])
            k += 1
            continue
        # 收集连续 off
        ctrl = []
        j = k
        while j < k + n and not on[idx[j % n]]:
            ctrl.append(pts[idx[j % n]])
            j += 1
        nxt_on = pts[idx[j % n]] if j < n + k else out[0]
        cur = np.array(out[-1], float)
        for m_, cp in enumerate(ctrl):
            b = (cp + ctrl[m_ + 1]) / 2 if m_ + 1 < len(ctrl) else np.asarray(nxt_on, float)
            t = np.linspace(0, 1, step)[1:, None]
            q = (1 - t) ** 2 * cur + 2 * (1 - t) * t * cp + t ** 2 * b
            out.extend(q)
            cur = b
        k = j
    arr = np.array(out, float)
    while len(arr) > 1 and np.hypot(*(arr[-1] - arr[0])) < 1e-6:
        arr = arr[:-1]
    return arr


def _pt_seg_dist(p, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    L2 = float(ab @ ab)
    if L2 < 1e-12:
        return np.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, float((p - a) @ ab) / L2))
    return float(np.hypot(*(p - (a + t * ab))))


def _one_way(src, dst):
    best = 0.0
    for p in src:
        d = min(_pt_seg_dist(p, dst[i], dst[(i + 1) % len(dst)]) for i in range(len(dst)))
        best = max(best, d)
    return best


def hausdorff(a, b):
    if len(a) == 0 or len(b) == 0:
        return float("inf")
    return max(_one_way(a, b), _one_way(b, a))


def candidates(pts, on, min_len, corner_deg):
    """返回可删的 on-curve 点下标集合。

    删的是「夹在两个相邻 on 点之间、且这一段只是一条直边的中间点」，
    也就是把一条直边切成几截的那些接缝点。
    """
    n = len(pts)
    if n < 4:
        return set()
    drop = set()
    ons = [i for i in range(n) if on[i]]
    if len(ons) < 3 and not on.all():
        return set()

    def nxt_on(i):
        for k in range(1, n + 1):
            j = (i + k) % n
            if on[j]:
                return j
        return i

    def prv_on(i):
        for k in range(1, n + 1):
            j = (i - k) % n
            if on[j]:
                return j
        return i

    for i in ons:
        p = prv_on(i)
        q = nxt_on(i)
        if p == i or q == i:
            continue
        a, b, c = pts[p], pts[i], pts[q]
        seg1 = float(np.hypot(*(b - a)))
        seg2 = float(np.hypot(*(c - b)))
        chord = float(np.hypot(*(c - a)))
        if seg1 >= min_len and seg2 >= min_len:
            continue
        # 转角保护
        v1, v2 = b - a, c - b
        n1, n2 = float(np.hypot(*v1)), float(np.hypot(*v2))
        if n1 > 1e-9 and n2 > 1e-9:
            cos = float(v1 @ v2 / (n1 * n2))
            ang = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
            if ang > corner_deg:
                continue
        # 中间点到弦的距离必须很小（说明它本来就在这条直边上）
        if chord > 1e-9:
            d = abs((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / chord
        else:
            d = 0.0
        if d <= 2.0:
            drop.add(i)
    return drop


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--min-len", type=float, default=8.0,
                    help="短于这个长度（字体单位）的段尝试合并，默认 8 = 0.8%% em")
    ap.add_argument("--tol", type=float, default=2.0,
                    help="允许的最大形状偏差（字体单位，默认 2 = 0.2%% em）")
    ap.add_argument("--corner", type=float, default=35.0,
                    help="转角超过这个度数就当折角，不动，默认 35")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个字形（调试）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = ap.parse_args()

    font = TTFont(args.source)
    glyf = font["glyf"]
    todo = [n for n in font.getGlyphOrder() if glyf[n].numberOfContours > 0]
    if args.limit:
        todo = todo[:args.limit]

    before = after = 0
    changed = rejected = same = 0
    worst = 0.0

    for gname in todo:
        g = glyf[gname]
        n0 = len(g.coordinates)
        before += n0

        drop_all = set()
        ok = True
        st = 0
        for e in g.endPtsOfContours:
            pts, on = ring_slice(g, st, e)
            # 先粗筛：这条轮廓有没有候选点。没有就完全不做密集采样，
            # 否则 33,751 个字形 × 每条轮廓的 O(n²) 距离会跑到几小时。
            if not candidates(pts, on, args.min_len, args.corner):
                st = e + 1
                continue
            # 逐个删、每删一个就重新测：一次删一批会把一条短边整段删掉
            # （实测 edotaccent 连删 4 点，轮廓走了 86.8 单位）。
            cur_pts, cur_on, dropped = pts, on, []
            ref = densify(pts, on)
            while True:
                trial = candidates(cur_pts, cur_on, args.min_len, args.corner)
                best = None
                for i in sorted(trial):
                    keep = [k for k in range(len(cur_pts)) if k != i]
                    if len(keep) < 3:
                        continue
                    d = hausdorff(ref, densify(cur_pts[keep], cur_on[keep]))
                    if d <= args.tol and (best is None or d < best[0]):
                        best = (d, i)
                if best is None:
                    break
                d, i = best
                worst = max(worst, d)
                dropped.append(i)
                cur_pts = np.delete(cur_pts, i, axis=0)
                cur_on = np.delete(cur_on, i)
            if dropped:
                # 把局部下标映射回整字形的下标
                idx = list(range(len(pts)))
                for dlt in dropped:
                    idx.pop(dlt)
                # 用「保留集合」反推被删的原始下标
                kept = set(idx)
                drop_all |= {st + i for i in range(len(pts)) if i not in kept}
            st = e + 1

        if not ok:
            rejected += 1
            after += n0
            continue
        if not drop_all:
            same += 1
            after += n0
            continue

        keep = [i for i in range(n0) if i not in drop_all]
        new_coords = [tuple(g.coordinates[i]) for i in keep]
        new_flags = [g.flags[i] for i in keep]
        # 重算每条轮廓的 endPts
        new_ends = []
        acc = -1
        st = 0
        for e in g.endPtsOfContours:
            cnt = sum(1 for i in range(st, e + 1) if i not in drop_all)
            acc += cnt
            new_ends.append(acc)
            st = e + 1

        if not args.dry_run:
            g.coordinates = type(g.coordinates)(new_coords)
            g.flags = bytearray(new_flags)
            g.endPtsOfContours = new_ends
            g.numberOfContours = len(new_ends)
            g.recalcBounds(glyf)
        after += len(new_coords)
        changed += 1

    print(f"字形 {len(todo):,} · 改动 {changed:,} · 无变化 {same:,} · 超差/回退 {rejected:,}")
    print(f"点数 {before:,} → {after:,}（减 {before - after:,}，"
          f"{(before - after) / max(before, 1) * 100:.2f}%）")
    print(f"实测最大轮廓偏移 {worst:.2f} 单位（上限 {args.tol}）")
    if not args.dry_run:
        font.save(args.output)
        print(f"写出 {args.output}（{args.output.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
