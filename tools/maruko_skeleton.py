"""从 Maruko 字形读出真实骨架，作为二创的唯一坐标来源。

为什么不再手估坐标
------------------
前几轮我按「猜」的骨架点写坐标，IoU 只有 0.22–0.49：包围盒对齐了，笔画却放在
错误的位置。二创的母版是 Maruko，骨架必须从它本身读出来。

流程
----
高分辨率栅格化 → 距离变换（顺便得到每处的半笔宽）→ 中轴骨架 → 骨架拆分支 →
在每个**自由端**上找回卷钩并按转角逐点切掉 → 沿切线把断口补回到原墨迹的极值 →
按 2×半笔宽、圆端头、圆转角描边 → 并集。

为什么这样画出来不会有「小角度」
--------------------------------
描边用的是 round join + round cap：轮廓是折线的闵可夫斯基和（与半径 33 的圆的并），
拐角与端头在构造上就是圆弧，没有需要事后修的折角。二创要的「去掉钩、收笔是半圆」
也正是这一步自然的结果。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from skimage.morphology import skeletonize

UPM = 1000
SS = 2                      # 超采样
BOX = (-40, -160, 1040, 900)
HW = 33.0                   # 半笔宽：Maruko「一」竖切实测笔宽 66/67


def _flatten(pen_value):
    polys, cur = [], []

    def push():
        nonlocal cur
        if len(cur) > 2:
            polys.append(list(cur))
        cur = []

    for op, args in pen_value:
        if op == "moveTo":
            push()
            cur = [args[0]]
        elif op == "lineTo":
            cur.append(args[0])
        elif op == "qCurveTo":
            pts = list(args)
            if pts[-1] is None:
                pts = pts[:-1] + [cur[0]]
            n = len(pts) - 1
            start = cur[-1]
            for i in range(n):
                ctrl = pts[i]
                end = pts[i + 1] if i == n - 1 else (
                    (pts[i + 1][0] + ctrl[0]) / 2, (pts[i + 1][1] + ctrl[1]) / 2)
                for k in range(1, 9):
                    t = k / 8
                    cur.append(((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * ctrl[0] + t * t * end[0],
                                (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * ctrl[1] + t * t * end[1]))
                start = end
        elif op in ("closePath", "endPath"):
            push()
    push()
    return polys   # 保持字体单位，缩放由调用方统一做一次（重复缩放会把字形推出画布）


def rasterize(path: Path, cp: int, box=BOX):
    font = TTFont(str(path))
    cmap = font.getBestCmap()
    if cp not in cmap:
        font.close()
        return None, None
    pen = RecordingPen()
    font.getGlyphSet()[cmap[cp]].draw(pen)
    font.close()
    x0, y0, x1, y1 = box
    img = Image.new("L", (int((x1 - x0) * SS), int((y1 - y0) * SS)), 0)
    d = ImageDraw.Draw(img)
    for poly in _flatten(pen.value):
        d.polygon([((x - x0) * SS, (y1 - y) * SS) for x, y in poly], fill=255)
    return img, box


def analyze(path: Path, cp: int):
    """栅格化 + 距离变换 + 骨架，返回字体单位下的骨架点与实测半笔宽。"""
    from scipy import ndimage
    img, box = rasterize(path, cp)
    if img is None:
        return None
    a = np.asarray(img) > 128
    dist = ndimage.distance_transform_edt(a)
    sk = skeletonize(a)
    ys, xs = np.nonzero(sk)
    x0, y0, x1, y1 = box
    pts = [((x / SS) + x0, (y1 - (y / SS))) for x, y in zip(xs, ys)]
    half = float(np.median(dist[sk])) / SS      # 像素半径 → 字体单位
    return dict(skeleton=pts, half_width=half, mask=a, box=box, dist=dist)


def _graph(points, radius=0.75):
    """骨架点 → 8 邻接图（半径 0.75 = 只连像素的 8 邻居，不用笔宽，避免捷径短路）。"""
    from scipy.spatial import cKDTree
    pts = np.asarray(points, dtype=float)
    pairs = cKDTree(pts).query_pairs(radius, output_type="ndarray")
    adj = {i: set() for i in range(len(pts))}
    for a, b in pairs:
        adj[int(a)].add(int(b))
        adj[int(b)].add(int(a))
    return pts, adj


def branches(pts, adj):
    """把骨架拆成端点/分叉点之间的链。返回 [(索引链, 两端是否自由端)]。"""
    free = {i for i in adj if len(adj[i]) == 1}
    nodes = {i for i in adj if len(adj[i]) != 2}
    seen, out = set(), []

    def key(a, b):
        return (a, b) if a < b else (b, a)

    def walk(a, b):
        chain = [a, b]
        seen.add(key(a, b))
        prev, cur = a, b
        while cur not in nodes:
            nxt = next(v for v in adj[cur] if v != prev)
            seen.add(key(cur, nxt))
            chain.append(nxt)
            prev, cur = cur, nxt
        return chain

    for n in sorted(nodes):
        for m in sorted(adj[n]):
            if key(n, m) not in seen:
                out.append(walk(n, m))
    # 剩下的只可能是纯闭环
    for n in sorted(adj):
        for m in sorted(adj[n]):
            if key(n, m) not in seen:
                chain = walk(n, m)
                out.append(chain)
    return [(c, (c[0] in free, c[-1] in free)) for c in out if len(c) > 1]


def smooth(poly, k=33):
    """沿折线做滑动平均，压掉骨架的像素台阶；端点保持不动。"""
    p = np.asarray(poly, dtype=float)
    if len(p) < 3 or k < 3:
        return p
    k = min(k, len(p) - 2 if len(p) % 2 == 0 else len(p) - 2)
    if k < 3:
        return p
    h = k // 2
    pad = np.concatenate([p[:1].repeat(h, 0), p, p[-1:].repeat(h, 0)])
    ker = np.ones(k) / k
    out = np.stack([np.convolve(pad[:, 0], ker, mode="valid"),
                    np.convolve(pad[:, 1], ker, mode="valid")], axis=1)
    out[0], out[-1] = p[0], p[-1]
    return out


def chaikin(poly, n=2):
    """Chaikin 角切，把骨架折线的锯齿磨掉（端点不动）。"""
    p = [tuple(map(float, q)) for q in poly]
    for _ in range(n):
        if len(p) < 3:
            break
        out = [p[0]]
        for a, b in zip(p[:-1], p[1:]):
            out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        out.append(p[-1])
        p = out
    return p


def simplify(points, tol=6.0):
    """RDP 折线化简。"""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 3:
        return pts.tolist()

    def rdp(lo, hi, keep):
        if hi <= lo + 1:
            return
        a, b = pts[lo], pts[hi]
        ab = b - a
        n = np.hypot(*ab)
        if n < 1e-9:
            d = np.hypot(*(pts[lo + 1:hi] - a).T)
        else:
            d = np.abs(ab[0] * (pts[lo + 1:hi, 1] - a[1]) - ab[1] * (pts[lo + 1:hi, 0] - a[0])) / n
        i = int(np.argmax(d))
        if d[i] > tol:
            idx = lo + 1 + i
            keep.add(idx)
            rdp(lo, idx, keep)
            rdp(idx, hi, keep)

    keep = {0, len(pts) - 1}
    rdp(0, len(pts) - 1, keep)
    return [pts[i].tolist() for i in sorted(keep)]


def _dir(a, b):
    v = np.asarray(b, dtype=float) - np.asarray(a, dtype=float)
    n = float(np.hypot(*v))
    return v / n if n > 1e-9 else np.array([0.0, 0.0])


def _len(poly):
    d = np.diff(np.asarray(poly, dtype=float), axis=0)
    return float(np.sum(np.hypot(d[:, 0], d[:, 1])))


def _resample(poly, step):
    """按弧长等距重采样。返回 (点列, 到起点的弧长)。"""
    p = np.asarray(poly, dtype=float)
    seg = np.hypot(*np.diff(p, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] < step * 2:
        return p, s
    t = np.arange(0.0, s[-1], step)
    return np.stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])], axis=1), t


def _tangent(p, i, k):
    a, b = p[min(i + k, len(p) - 1)] - p[i], p[i] - p[max(i - k, 0)]
    n = float(np.hypot(*b))
    return b / n if n > 1e-9 else np.array([0.0, 0.0])


def trim_end(seq, hw, deg=65.0, max_len=8.0, min_len=0.5):
    """末端要切掉多长（从端点算起）。0 = 这一端是直的，没有钩。

    量的是**累计转角**：从端点往回走，转够 deg 度就算钩。
    Maruko 的两种钩都能覆盖——
      · `乙`/`九` 的钩短而急：76 单位内就转满 90°，切口落在钩根；
      · `了`/`子` 的尾长而缓：要 250 单位才转完 90°，切口落在尾部收进竖的地方。
    局部曲率判不出后者（它的曲率只比笔画弓形高一点），单点方向判不出前者
    （差一点点角度就漏），累计转角对两者都成立。
    超过 max_len×半笔宽 还没转够，说明这是字本身的骨架而不是钩，不切。
    """
    p = np.asarray(seq, dtype=float)
    n = len(p)
    if n < 8:
        return 0.0
    acc, total, cut = 0.0, 0.0, None
    for i in range(1, n - 1):
        u, v = p[i] - p[i - 1], p[i + 1] - p[i]
        nu, nv = np.hypot(*u), np.hypot(*v)
        if nu > 1e-9 and nv > 1e-9:
            acc += math.degrees(math.acos(float(np.clip(np.dot(u, v) / (nu * nv), -1, 1))))
        total += float(nu)
        if acc >= deg:
            cut = total
            break
        if total > max_len * hw:
            break
    if cut is None or cut < min_len * hw:
        return 0.0
    return cut


def straighten_end(poly, hw, at_end=True, keep=0.9, body=5.0):
    """把切口后剩下的一小截弯尾拉直。

    切口落在肘部，切口处的切线还带着钩的残余角度（`了` 的尾一收就是斜的），
    直接在那儿收半圆会得到斜切的端头。这里用**身体段的主轴**（PCA，取
    0.8×半笔宽 到 body×半笔宽 之间的点）当收笔方向，把末端 keep×半笔宽
    的一截换成沿主轴的直线。收笔就垂直于笔画，是正半圆——和 Maruko 自己
    的圆端头同一种几何。
    """
    p = np.asarray(poly, dtype=float)
    if len(p) < 6:
        return p
    if not at_end:
        return straighten_end(p[::-1], hw, True, keep, body)[::-1]
    seg = np.hypot(*np.diff(p, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    L = float(cum[-1])
    i_cut = int(np.searchsorted(cum, L - keep * hw))
    i_lo = int(np.searchsorted(cum, L - body * hw))
    i_hi = int(np.searchsorted(cum, L - 0.8 * hw))
    i_cut = min(max(i_cut, 2), len(p) - 3)
    if i_hi - i_lo < 3:
        return p
    q = p[i_lo:i_hi]
    q = q - q.mean(axis=0)
    w, v = np.linalg.eigh(q.T @ q)
    d = v[:, int(np.argmax(w))]
    if d @ (p[-1] - p[i_cut]) < 0:
        d = -d
    return np.vstack([p[: i_cut + 1], p[i_cut] + d * float(L - cum[i_cut])])


def extend_to_ink(poly, mask, box, hw, at_end=True, lookback=2.0, max_extend=3.0):
    """把切口沿笔画自己的方向补回原墨迹的极值：去钩之后笔画不该缩水。"""
    p = np.asarray(poly, dtype=float)
    if len(p) < 3:
        return poly
    if at_end:
        anchor, acc, i = p[-1], 0.0, len(p) - 1
        while i > 1 and acc < lookback * hw:
            acc += float(np.hypot(*(p[i] - p[i - 1])))
            i -= 1
        d = _dir(p[i], anchor)
    else:
        anchor, acc, i = p[0], 0.0, 0
        while i < len(p) - 2 and acc < lookback * hw:
            acc += float(np.hypot(*(p[i + 1] - p[i])))
            i += 1
        d = _dir(p[i], anchor)
    if not np.any(d):
        return poly
    ys, xs = np.nonzero(mask)
    x0, y0, x1, y1 = box
    mx = (xs / SS) + x0
    my = y1 - (ys / SS)
    # 只看「笔画延长线附近」的墨迹：不然斜向延长会一头扎到字的另一个角上
    lateral = np.abs((mx - anchor[0]) * d[1] - (my - anchor[1]) * d[0])
    near = lateral <= hw
    if not np.any(near):
        return poly
    proj = mx[near] * d[0] + my[near] * d[1]
    tip = float(anchor @ d)
    want = min(float(proj.max()) - hw, tip + max_extend * hw)
    if want <= tip + 0.3 * hw:
        return poly
    new = anchor + d * (want - tip)
    return np.vstack([p, new]) if at_end else np.vstack([new, p])


def _longest_path(pts, adj):
    """图里的最长路径（两次 BFS）。"""
    from collections import deque
    if not adj:
        return []

    def bfs(start):
        dist, prev = {start: 0.0}, {start: None}
        q, far, far_d = deque([start]), start, 0.0
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v in dist:
                    continue
                dist[v] = dist[u] + float(np.hypot(*(pts[v] - pts[u])))
                prev[v] = u
                if dist[v] > far_d:
                    far, far_d = v, dist[v]
                q.append(v)
        return far, prev

    a, _ = bfs(next(iter(adj)))
    b, prev = bfs(a)
    path, cur = [], b
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def strokes(path: Path, cp: int, hw=HW, tol=3.0, step=4.0):
    """读一个字 → 若干条等宽笔画的中线（已去钩、已补到墨迹极值）。

    做法是「剥面条」：在骨架图里反复取最长路径，取一条就从图里去掉一条。
    每条路径都先按弧长等距重采样，切口与补墨都用弧长表示，不再和像素下标
    纠缠（前几轮的越界与切反全出在这里）。
    """
    r = analyze(path, cp)
    if r is None:
        return None
    coords, adj = _graph(r["skeleton"])
    alive = set(adj)
    out, removed = [], np.zeros((0, 2))
    while alive:
        sub = {i: {j for j in adj[i] if j in alive} for i in alive}
        sub = {i: v for i, v in sub.items() if v}
        if not sub:
            break
        idx = _longest_path(coords, sub)
        if len(idx) < 6:
            break
        rs, s = _resample(smooth([coords[i] for i in idx]), step)
        L = float(s[-1])
        if L < 1.4 * hw:
            break

        def far(q):
            return 1e9 if not len(removed) else float(np.min(np.hypot(*(removed - q).T)))

        lo, hi = 0.0, L
        cut_a = cut_b = False
        if far(rs[0]) > 1.2 * hw:
            k = trim_end(rs, hw)
            if k > 0:
                lo, cut_a = k, True
        if far(rs[-1]) > 1.2 * hw:
            k = trim_end(rs[::-1], hw)
            if k > 0:
                hi, cut_b = L - k, True
        if hi - lo < 0.8 * hw:
            removed = np.vstack([removed, coords[idx]])
            alive -= set(idx)
            continue
        keep = rs[(s >= lo - 1e-6) & (s <= hi + 1e-6)]
        if cut_b:
            keep = straighten_end(keep, hw, at_end=True)
            keep = extend_to_ink(keep, r["mask"], r["box"], hw, at_end=True)
        if cut_a:
            keep = straighten_end(keep, hw, at_end=False)
            keep = extend_to_ink(keep, r["mask"], r["box"], hw, at_end=False)
        simp = simplify(chaikin(simplify(keep, tol=tol), 2), 1.2)
        if len(simp) >= 2:
            out.append([(round(x, 1), round(y, 1)) for x, y in simp])
        removed = np.vstack([removed, coords[idx]])
        alive -= set(idx)
    return dict(strokes=out, half_width=hw, measured=r["half_width"], box=r["box"])


def stroke_outline(stroke_list, hw=HW):
    """中线 → 轮廓：2×半宽、圆端头、圆转角，再并成一条路径。

    圆端头 + 圆转角意味着轮廓是「中线的闵可夫斯基和（与半径 hw 的圆）」，
    拐角和收笔在构造上就是圆弧，没有需要事后修的折角或小角度。
    """
    import pathops
    acc = pathops.Path()
    for st in stroke_list:
        p = pathops.Path()
        p.moveTo(*st[0])
        for x, y in st[1:]:
            p.lineTo(x, y)
        p.stroke(2 * hw, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
        p.convertConicsToQuads(0.2)
        acc.addPath(p)
    acc.simplify(fix_winding=True, keep_starting_points=False)
    return acc


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/maruko.ttf"
    chars = sys.argv[2] if len(sys.argv) > 2 else "乙了子九"
    for ch in chars:
        s = strokes(Path(src), ord(ch))
        if s is None:
            print(f"{ch}: 无字形")
            continue
        print(f'    "{ord(ch):04X}": {s["strokes"]!r},')
