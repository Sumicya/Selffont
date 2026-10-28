"""从 Maruko 字形读出真实骨架，作为二创的唯一坐标来源。

为什么不再手估坐标
------------------
前几轮我按「猜」的骨架点写坐标，IoU 只有 0.22–0.49：包围盒对齐了，笔画却放在
错误的位置。二创的母版是 Maruko，骨架必须从它本身读出来。

流程
----
高分辨率栅格化（字腔留空）→ 距离变换（顺便得到每处的半笔宽）→ 中轴骨架 →
交叉点处一次分解成「臂」、方向相反的臂接回成一条穿过去的笔画 → 交叉点补半径=半宽的
圆盘 → 按 2×半笔宽、圆端头、圆转角描边 → 并集。笔画照母版原样取，不切钩。

为什么这样画出来不会有「小角度」
--------------------------------
描边用的是 round join + round cap：轮廓是折线的闵可夫斯基和（与半径 33 的圆的并），
拐角与端头在构造上就是圆弧，没有需要事后修的折角；母版自己的钩也照原样保留。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from fontTools.pens.recordingPen import DecomposingRecordingPen, RecordingPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from skimage.morphology import skeletonize

UPM = 1000
SS = 1                      # 栅格化倍率（1 = 每单位 1 像素；邻居阈值 1.5/SS 跟着走）
BOX = (-40, -160, 1040, 900)
HW = 33.0                   # 半笔宽：Maruko「一」竖切实测笔宽 66/67





def _flatten(pen_value, steps=8):
    """pen 命令流 → 折线（每个轮廓一条），二次/三次曲线都按弧长细分。

    两个坑：TrueType 的闭合轮廓可以**没有 moveTo**，直接以 qCurveTo 起笔，
    缺省起点是首尾两个控制点的中点；而 pathOps 描完边吐的是三次 curveTo。
    早先两种都没接住，圆端头（全是三次曲线）于是在栅格里整段消失，
    量出来的面积与 IoU 全都偏低——判断好坏之前先把量尺修准。
    """
    polys, cur = [], []

    def push():
        nonlocal cur
        if len(cur) > 2:
            polys.append(list(cur))
        cur = []

    def quad(a, c, b):
        for k in range(1, steps + 1):
            t = k / steps
            u = 1 - t
            cur.append((u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
                        u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]))

    def cubic(a, c1, c2, b):
        for k in range(1, steps + 1):
            t = k / steps
            u = 1 - t
            cur.append((u ** 3 * a[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * b[0],
                        u ** 3 * a[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * b[1]))

    for op, args in pen_value:
        if op == "moveTo":
            push()
            cur = [args[0]]
        elif op == "lineTo":
            if not cur:
                cur = [args[-1]]
            else:
                cur.append(args[-1])
        elif op == "curveTo":
            if not cur:
                cur = [args[0]]
            start = cur[-1]
            for i in range(0, len(args) - 2, 3):
                cubic(start, args[i], args[i + 1], args[i + 2])
                start = args[i + 2]
        elif op == "qCurveTo":
            pts = list(args)
            closed = pts[-1] is None
            if closed:
                pts = pts[:-1]
            if not cur:                     # 省了 moveTo 的闭合轮廓
                cur = [((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)]
                closed = True
            if closed:
                pts.append(cur[0])
            start = cur[-1]
            for i in range(len(pts) - 1):
                end = pts[i + 1] if i == len(pts) - 2 else (
                    (pts[i + 1][0] + pts[i][0]) / 2, (pts[i + 1][1] + pts[i][1]) / 2)
                quad(start, pts[i], end)
                start = end
        elif op in ("closePath", "endPath"):
            push()
    push()
    return polys   # 保持字体单位，缩放由调用方统一做一次（重复缩放会把字形推出画布）


def _area(poly):
    a = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        a += x0 * y1 - x1 * y0
    return a * 0.5


_FONT_CACHE = {}


def _font(path):
    """同一进程里每个字体只解析一次（全表解码约 0.1 s/字，20k 字就是半小时）。"""
    key = str(path)
    if key not in _FONT_CACHE:
        font = TTFont(key)
        _FONT_CACHE[key] = (font, font.getBestCmap(), font.getGlyphSet())
    return _FONT_CACHE[key]


def rasterize(path: Path, cp: int, box=None):
    """字形 → 布尔位图。

    字腔（`口`/`日`/`田` 的内圈、`路` 里那个「口」）**必须留空**。早先每个轮廓都按
    实心填，字腔被填满，骨架于是塌成一个半径 330 的小团，围框字全部取不出笔画。
    轮廓的绕向不能靠「最大面积」去猜（多部件字里各部件的绕向并不一致，`路` 的
    「口」就会被挖空），所以先用 pathOps 按 nonzero 规则求并——它输出的就是最终
    墨迹区域，绕向也已经规范化——再逐个轮廓填充。
    """
    import pathops

    font, cmap, glyphs = _font(path)
    if cp not in cmap:
        return None, None
    # 必须用会拆复合字形的笔：`Á`/`ü` 这类字是「基字 + 重音符」的组合字形，
    # 普通 RecordingPen 只转手一条 addComponent，pathOps 没有字形表可拆，
    # 直接抛 TypeError，整类带重音西文就都取不出来。
    pen = DecomposingRecordingPen(glyphs)
    glyphs[cmap[cp]].draw(pen)
    pp = pathops.Path()
    pen.draw(pp.getPen())
    pp.simplify(fix_winding=True, keep_starting_points=False)
    spen = RecordingPen()
    pp.draw(spen)
    polys = _flatten(spen.value)
    if not polys:
        return None, None
    # 只栅格化这个字的包围盒（外扩 30 单位）：整框 4.6M 像素里有六成是空白，
    # 而骨架化与距离变换都是按像素数计费的。
    if box is None:
        bx0 = min(min(x for x, _ in q) for q in polys) - 30
        bx1 = max(max(x for x, _ in q) for q in polys) + 30
        by0 = min(min(y for _, y in q) for q in polys) - 30
        by1 = max(max(y for _, y in q) for q in polys) + 30
        box = (max(BOX[0], bx0), max(BOX[1], by0), min(BOX[2], bx1), min(BOX[3], by1))
    x0, y0, x1, y1 = box
    img = Image.new("L", (max(1, int(round((x1 - x0) * SS))), max(1, int(round((y1 - y0) * SS)))), 0)
    d = ImageDraw.Draw(img)
    # simplify 已经把绕向规范化：最大面积那个定「外」的方向，同向填实、反向挖空。
    areas = [abs(_area(q)) for q in polys]
    sign = 1.0 if _area(polys[max(range(len(polys)), key=lambda k: areas[k])]) > 0 else -1.0
    for k in sorted(range(len(polys)), key=lambda k: -areas[k]):
        fill = 255 if _area(polys[k]) * sign > 0 else 0
        d.polygon([((x - x0) * SS, (y1 - y) * SS) for x, y in polys[k]], fill=fill)
    return img, box


def analyze(path: Path, cp: int, box=None):
    """栅格化 + 距离变换 + 骨架，返回字体单位下的骨架点与实测半笔宽。

    `box` 留空时只栅格化这个字的包围盒（快 1.6 倍）；要跟整框对齐的位图就传 BOX。
    """
    from scipy import ndimage
    img, box = rasterize(path, cp, box)
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


def _graph(points, radius=None):
    """骨架点 → 8 邻接图（只连像素的 8 邻居，不用笔宽，避免捷径短路）。

    阈值必须跟着栅格化倍率走：SS=2 时邻居距离 0.5 / 0.707，取 1.5/SS（=对角距离的 1.06 倍）
    对角邻居；写死 0.75 的话 SS=1.5 的对角距离 0.943 连不上，骨架退化成 4 连通、
    笔画断成一截一截（实测墨量比掉到 0.19）。
    """
    from scipy.spatial import cKDTree
    if radius is None:
        radius = 1.5 / SS
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


def _bucket(vec):
    """向量 → 8 个方向桶（_ring_walk 选直走用）。"""
    return int(round(math.atan2(vec[1], vec[0]) / (math.pi / 4.0))) % 8


def _junctions(coords, adj, hw):
    """交叉点像素聚成若干个圆心（笔画交叉处，半径 hw 的圆盘要补在这里）。"""
    deg = {i: len(v) for i, v in adj.items()}
    js = [i for i in adj if deg[i] >= 3]
    if not js:
        return []
    pts = np.asarray([coords[i] for i in js], float)
    used = np.zeros(len(pts), bool)
    out = []
    for i in range(len(pts)):
        if used[i]:
            continue
        grp = [i]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j in range(len(pts)):
                if used[j]:
                    continue
                if np.min(np.hypot(*(pts[grp] - pts[j]).T)) < 2.0 * hw:
                    grp.append(j)
                    used[j] = True
                    changed = True
        out.append(tuple(pts[grp].mean(axis=0)))
    return out


def _path_between(pts, adj, a, b):
    """a→b 的最短路径（BFS）。"""
    from collections import deque

    prev = {a: None}
    q = deque([a])
    while q:
        u = q.popleft()
        if u == b:
            break
        for v in adj[u]:
            if v in prev:
                continue
            prev[v] = u
            q.append(v)
    if b not in prev:
        return []
    path, cur = [], b
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def _ring_walk(pts, comp, adj, start=None):
    """沿闭合环走一圈（每步选没走过的邻居）。"""
    start = start if start is not None else comp[0]
    path, seen = [start], {start}
    cur = start
    while True:
        nxt = [v for v in adj[cur] if v not in seen]
        if not nxt:
            # 回到起点则收尾
            if start in adj[cur] and len(path) > 3:
                path.append(start)
            break
        # 8 邻接里优先「直走」，避免在环上锯齿
        if len(path) >= 2:
            d0 = np.asarray(pts[cur], float) - np.asarray(pts[path[-2]], float)
            b0 = _bucket(d0)
            nxt.sort(key=lambda v: min(abs(_bucket(np.asarray(pts[v], float) - np.asarray(pts[cur], float)) - b0),
                                       8 - abs(_bucket(np.asarray(pts[v], float) - np.asarray(pts[cur], float)) - b0)))
        cur = nxt[0]
        seen.add(cur)
        path.append(cur)
    return path


def arm_paths(coords, adj, hw):
    """按交叉点把骨架一次分解成若干条「臂」，返回 (arms, junction_points)。

    为什么不能用「迭代取最长路径再删除」：交叉处一小片像素被多条笔画共享，
    取走一条就把别的笔画删断了（实测 `丁` 的横被切成 5 段、`天` 的撇和捺被并成
    一条 1264 单位的大绕行）。一次分解不会互相破坏：
      1. 交叉点像素（度 ≥ 3）先摘掉，剩下的连通分量天然就是一条条笔画；
      2. 端点挨着交叉点的臂，把端点沿切线延长到交叉点圆心；
      3. 交叉点补半径 hw 的圆盘 —— 等宽圆体的交叉本来就该是这个形状，
         圆盘一补，T 字路口的上沿就是圆弧，不会凹下去。
    """
    deg = {i: len(v) for i, v in adj.items()}
    js = {i for i in adj if deg[i] >= 3}
    alive = {i for i in adj if i not in js}
    comps, seen = [], set()
    for st in sorted(alive):
        if st in seen:
            continue
        comp, stack = [], [st]
        seen.add(st)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v in alive and v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(comp)
    arms = []
    for comp in comps:
        cs = set(comp)
        sub = {i: {j for j in adj[i] if j in cs} for i in comp}
        ring = len(comp) > 8 and all(len(sub[i]) == 2 for i in comp)
        if ring:
            arms.append(dict(path=_ring_walk(coords, comp, sub), ring=True,
                             anchor_a=None, anchor_b=None))
            continue
        ends = [i for i in comp if len(sub[i]) <= 1]
        if len(ends) >= 2:
            path = _path_between(coords, sub, ends[0], ends[1])
        else:
            path = _longest_path(coords, sub) if len(comp) > 2 else None
        if not path or len(path) < 3:
            continue
        a = [j for j in adj[path[0]] if j in js]
        b = [j for j in adj[path[-1]] if j in js]
        arms.append(dict(path=path, ring=False, anchor_a=a, anchor_b=b))
    return arms, js


def _arm_dir(coords, path, at_start, hw, reach=3.0):
    """臂端朝内的方向（从交叉点指向臂身）。

    取「沿弧长 3×半笔宽处」而不是端点附近的前几个点：8 邻接骨架在交叉点内侧
    会先沿对角线走二三十个单位（`天` 的中横右段前 60 个点全是 45° 斜走），
    拿近端点估方向会把横判成斜笔，直穿配对就配错。
    """
    pts = np.asarray([coords[i] for i in path], float)
    if len(pts) < 6:
        return None
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
    L = float(cum[-1])
    if L < 1.0:
        return None
    want = min(reach * hw, L)
    if at_start:
        d = pts[int(np.searchsorted(cum, want))] - pts[0]
    else:
        d = pts[int(np.searchsorted(cum, L - want))] - pts[-1]
    n = float(np.hypot(*d))
    return d / n if n > 1e-9 else None


def _assemble(coords, adj, hw, straight_deg=145.0):
    """骨架 → 若干条笔画。返回 (chains, joints)。

    分两步：
      1. `arm_paths` 在交叉点处把骨架一次切开，得到互不破坏的「臂」；
      2. 同一交叉点上，方向几乎相反的两条臂属于同一条**穿过去**的笔画，接回去。
         剩下的臂（T 字的那一竖、十字的一条）就在交叉点收笔——收笔是半圆，
         和半径 hw 的圆盘重合，所以路口是圆的，不是凹的。

    为什么要「一次切开」：交叉处那一小片像素被多条笔画共用，旧办法「取一条最
    长路再删掉」会把别人的笔画删断（`丁` 的横碎成 5 段、`天` 的撇捺并成一条
    1264 单位的大绕行），断口再补就是凹口与斜撇的来源。
    """
    arms, jpix = arm_paths(coords, adj, hw)
    # 交叉点内被切出来的碎屑（长几到几十单位）没有笔画身份：参与配对会抢走
    # 真正的臂（实测 `天` 的中横左段被一块 6 单位碎屑配到了捺上）。统一交给圆盘。
    keep = []
    for a in arms:
        p = np.asarray([coords[i] for i in a["path"]], float)
        if float(np.sum(np.hypot(*np.diff(p, axis=0).T))) >= 1.5 * hw:
            keep.append(a)
    arms = keep
    if not arms:
        return [], []
    joints = _junctions(coords, adj, hw) if jpix else []

    def joint_of(end):
        if not end or not joints:
            return None
        q = np.mean([coords[i] for i in end], axis=0)
        d = [float(np.hypot(*(np.asarray(c, float) - q))) for c in joints]
        k = int(np.argmin(d))
        return k if d[k] < 3.0 * hw else None

    ends = {}
    for i, a in enumerate(arms):
        for tag, key in (("a", "anchor_a"), ("b", "anchor_b")):
            j = joint_of(a[key])
            if j is None:
                continue
            d = _arm_dir(coords, a["path"], tag == "a", hw)
            if d is not None:
                ends[(i, tag)] = dict(joint=j, dir=d)

    # 同一交叉点内两两配「直穿」：方向越接近相反越先配（贪心，避免交叉配对）
    lim = math.cos(math.radians(180.0 - straight_deg))
    pairs = {}
    for j in range(len(joints)):
        es = [(i, t, v) for (i, t), v in ends.items() if v["joint"] == j]
        cand = []
        for x in range(len(es)):
            for y in range(x + 1, len(es)):
                c = float(es[x][2]["dir"] @ es[y][2]["dir"])
                if c < lim:
                    cand.append((c, x, y))
        cand.sort()
        got = set()
        for _, x, y in cand:
            if x in got or y in got:
                continue
            got |= {x, y}
            pairs[(es[x][0], es[x][1])] = (es[y][0], es[y][1])
            pairs[(es[y][0], es[y][1])] = (es[x][0], es[x][1])

    used, chains = set(), []

    def walk(i, enter):
        seq, cur, ent = [], i, enter
        while cur not in used:
            a = arms[cur]
            p = list(a["path"])
            if ent == "b":
                p = p[::-1]
            seq.extend(coords[k] for k in p)
            used.add(cur)
            nxt = pairs.get((cur, "b" if ent == "a" else "a"))
            if nxt is None:
                break
            cur, ent = nxt
        return seq

    for i in range(len(arms)):
        for t in ("a", "b"):
            if (i, t) in pairs or i in used:
                continue
            chains.append(np.asarray(walk(i, t), float))
    for i in range(len(arms)):          # 整条都配对的环（口/日 的内环）
        if i not in used:
            chains.append(np.asarray(walk(i, "a"), float))
    return chains, [np.asarray(c, float) for c in joints]


def mask_of(r):
    return np.asarray(r["mask"])


def _smooth_chain(chain, hw):
    """把骨架像素链整理成可以拟合的中线：平滑 → 等距重采样。"""
    return _resample(smooth(np.asarray(chain, float), k=33), 4.0)


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


def measure_halfwidth(mask, rs, s, r_hint, box=BOX):
    """笔画中段横截面半宽的中位数。

    骨架的距离变换在端头附近偏小，直接拿它的中位数当半宽会把笔画画细 2–3 单位
    （6× 放大时母版灰边会从四周露出来）。这里改成量横截面：沿笔身每 8 单位取一点，
    垂直切线量两侧墨迹边界的距离，取 (左+右)/2 的中位数。
    """
    rs = np.asarray(rs, float)
    s = np.asarray(s, float)
    L = float(s[-1])
    vals = []
    for a in np.arange(2.0 * r_hint, L - 2.0 * r_hint, 8.0):
        i = int(np.searchsorted(s, a))
        i = min(max(i, 2), len(rs) - 3)
        t = rs[i + 2] - rs[i - 2]
        n = np.hypot(*t)
        if n < 1e-9:
            continue
        t = t / n
        nrm = np.array([-t[1], t[0]])
        origin = rs[i]
        lr = []
        for sgn in (1.0, -1.0):
            d = 0.0
            while d < 2.0 * r_hint:
                q = origin + nrm * sgn * (d + 0.5)
                x = int(round((q[0] - box[0]) * SS))
                y = int(round((box[3] - q[1]) * SS))
                if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]) or not mask[y, x]:
                    break
                d += 0.5
            lr.append(d)
        if lr[0] + lr[1] > 0.6 * r_hint:
            vals.append(0.5 * (lr[0] + lr[1]))
    return float(np.median(vals)) if vals else r_hint


def spline_beziers(points, smooth_units=1.0, k=3):
    """中线点列 → 三次贝塞尔段（每段 4 个控制点，首尾相接）。

    先用平滑 B 样条拟合（总残差上界 n·smooth_units²，即平均每点偏 ≤1 单位），
    再把内部节点补到 k 重，于是每段的 4 个控制点直接就是贝塞尔控制点。
    中线因此 G1 连续——描边后不会留下折线拼接的波纹，这正是前几版「不平滑」的来源。
    """
    from scipy.interpolate import BSpline, splprep

    P = np.asarray(points, float)
    if len(P) < k + 1:
        return None
    d = np.hypot(*(np.diff(P, axis=0).T))
    P = P[np.concatenate([[True], d > 1e-9])]
    if len(P) < k + 1:
        return None
    tck, _ = splprep([P[:, 0], P[:, 1]], s=len(P) * smooth_units ** 2, k=k)
    t, c, kk = tck
    bs = BSpline(np.asarray(t), np.asarray(c).T, kk)
    uq, mult = np.unique(t, return_counts=True)
    for u, m in zip(uq, mult):
        if u <= t[kk] + 1e-9 or u >= t[-kk - 1] - 1e-9:
            continue
        for _ in range(max(0, kk - int(m))):
            bs = bs.insert_knot(float(u))
    nctrl = len(bs.t) - kk - 1
    if (nctrl - 1) % kk:
        return None
    return [np.asarray(bs.c[i * kk:i * kk + kk + 1], float)
            for i in range((nctrl - 1) // kk)]


def _body_dir(pts, hw, at_start, span=3.0):
    """端部一小段的主方向（指向笔画内部）。"""
    n = len(pts)
    k = max(3, min(int(span * hw / 4.0), n - 1))
    seg = np.asarray(pts[:k + 1] if at_start else pts[-k - 1:], float)
    anchor = seg[0] if at_start else seg[-1]
    c = seg.mean(axis=0)
    w, v = np.linalg.eigh((seg - c).T @ (seg - c))
    d = v[:, int(np.argmax(w))]
    if d @ (anchor - c) < 0:
        d = -d
    return -d                              # d 指向端头，取反后恒指「朝笔画内部」


def _ink_reach(mask, origin, d, hw, limit):
    """从 origin 沿 d 走，宽 2.4hw 走廊内墨迹的最远投影（不超过 limit）。"""
    nrm = np.array([-d[1], d[0]])
    best = 0.0
    for t in np.arange(0.0, limit, 1.0):
        for lat in np.arange(-1.2 * hw, 1.2 * hw + 1e-9, 1.5):
            q = origin + d * t + nrm * lat
            x = int(round((q[0] - BOX[0]) * SS))
            y = int(round((BOX[3] - q[1]) * SS))
            if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x]:
                best = max(best, t)
                break
    return best


def _tip_out(pts, hw, at_start):
    """去钩后往哪收笔：返回 (笔身当前末向, 目标收笔方向)。

    目标方向与笔身末向接近时就是「顺着收窄」，否则说明是折弯钩的横段——
    折弯钩去掉钩之后要收成捺势（右下 32°），不能还是一根平横
    （主人 2026-10-27 点过这条）。两个方向分开返回，才能用圆弧把中线从前者转到后者。
    """
    body = -np.asarray(_body_dir(pts, hw, at_start), float)   # 笔身指的「朝外」
    n = np.hypot(*body)
    if n < 1e-9:
        return np.array([0.0, -1.0]), np.array([0.0, -1.0])
    body = body / n
    target = body
    # 只有**水平**笔身的收笔才转捺势。阈值放到 0.35：竖钩（`了`/`子`/`手`）切完
    # 钩剩下的末段常带 40° 左右的斜，0.8 会把它们也判成横段，转出一条向左下的
    # 假捺（`了` 的竖钩实测被拉到 x=335）。
    if abs(body[0]) > 1e-9 and abs(body[1] / body[0]) < 0.35:
        ang = math.radians(-35.0) if body[0] > 0 else math.radians(180.0 + 35.0)
        target = np.array([math.cos(ang), math.sin(ang)])
    return body, target


def _split_sharp(rs, s, hw, deg=88.0, max_parts=3):
    """按锐角把一条链切段：母版把两笔的角接在一起时（`几`/`凡` 的撇与横折），
    骨架是一条链，不切就永远分不出两笔。返回 [(i0, i1), ...]。"""
    P = np.asarray(rs, float)
    k = max(2, int(1.5 * hw / 4.0))
    cuts = []
    for i in range(k + 1, len(P) - k - 1):
        a = P[i] - P[i - k]
        b = P[i + k] - P[i]
        na, nb = np.hypot(*a), np.hypot(*b)
        if na < 1e-9 or nb < 1e-9:
            continue
        turn = math.degrees(math.acos(float(np.clip(a @ b / (na * nb), -1, 1))))
        if turn >= deg:
            if not cuts or i - cuts[-1] > 2 * k:
                cuts.append(i)
        if len(cuts) >= max_parts - 1:
            break
    if not cuts:
        return [(0, len(P) - 1)]
    out, prev = [], 0
    for c in cuts:
        out.append((prev, c))
        prev = c
    out.append((prev, len(P) - 1))
    return out


def bezier_strokes(path: Path, cp: int, hw=None, dot_r=None, probe=True, r=None):
    """读一个字 → 每条笔画的贝塞尔中线 + 该字实测半宽 + 交叉点圆盘。

    笔画**照母版骨架原样**取：不切钩、不改收笔、不断开交接。上一版的「去钩 /
    折弯钩改横捺」整条路线已放弃（主人 2026-10-27：放弃去钩转向扩字集），
    因为去钩要逐字判钩根、还要逐字过目白名单，扩不动字集；而母版本身的钩
    只是端点处的一小段回卷，圆头描边照原样画出来就是 Maruko 的写法。

    `dot_r` 非空时每个交叉点额外输出一个圆盘中线：T 字路口靠它把上沿补成圆弧。
    """
    if r is None:                       # 调用方已经栅格过就把结果传进来，别重栅
        r = analyze(path, cp)
    if r is None:
        return None
    hint = float(r["half_width"]) if hw is None else float(hw)
    coords, adj = _graph(r["skeleton"])
    chains, joints = _assemble(coords, adj, hint)
    raw, probes = [], []
    for c in chains:
        rs, s = _smooth_chain(c, hint)
        L = float(s[-1])
        if L < 1.4 * hint:
            continue
        raw.append((rs, s, L))
        if probe and L > 2.0 * hint:
            probes.append(measure_halfwidth(mask_of(r), rs, s, hint, r["box"]))
    half = float(np.median(probes)) if probes else hint
    out = []
    for rs, s, L in raw:
        # 闭合环（口/日/田 的内外圈）：首尾相接的一整圈，必须 close() 收口，
        # 否则接缝处会留一个笔宽的豁口。
        if float(np.hypot(*(np.asarray(rs[0], float) - np.asarray(rs[-1], float)))) < 1.5 * half \
                and L > 3.0 * half:
            pts = np.vstack([np.asarray(rs, float), np.asarray(rs, float)[:3]])
            segs = spline_beziers(pts)
            if segs:
                out.append({"closed": True,
                            "segs": [[tuple(round(float(v), 1) for v in pt) for pt in seg]
                                     for seg in segs]})
            continue
        for i0, i1 in _split_sharp(rs, s, half):
            pts = np.asarray(rs[i0:i1 + 1], float)
            if len(pts) < 6:
                continue
            if float(np.sum(np.hypot(*np.diff(pts, axis=0).T))) < 1.4 * half:
                continue
            segs = spline_beziers(pts)
            if segs:
                out.append({"closed": False,
                            "segs": [[tuple(round(float(v), 1) for v in pt) for pt in seg]
                                     for seg in segs]})
    if dot_r:
        for j in joints:
            c = (round(float(j[0]), 1), round(float(j[1]), 1))
            out.append({"closed": False, "dot": True, "segs": [[c, c, c, c]]})
    out.extend(_dot_blobs(r, raw, han=is_han(cp)))
    out, _ = split_ring_tail(out)
    if not out:
        return None
    return dict(half_width=half, strokes=out)


def split_ring_tail(strokes, tol=45.0, min_arm=150.0, min_loop=500.0):
    """把「绕过一圈、又接着走出去」的一条笔画拆成「闭合环 + 独立尾笔」。

    为什么需要：`_assemble` 在交叉点把骨架切成臂、再把方向相反的臂接回一条穿过去的笔画。
    笔画自己绕成环（`日`/`田`/`口` 的外框）时，环上的臂会跟穿过它的撇、竖发生「直穿」配对，
    于是环和穿过它的笔画接成同一条：`暑` 的撇因此顺着 `日` 的外框走了一圈再出去，撇被拉成
    环的一部分，收笔的圆头也没了（主人 2026-10-28：「暑的撇拉完了」）。

    判据只看数据本身，不看是哪个字：折线上任意两点（相隔足够远、绕行长度 ≥ 0.5 em）回到
    tol 以内，两侧各自还有不短的路，就在**回头点**把这条链拆成「环」与「尾」两段。
    拆分只动拓扑、不动几何：环段按 closed 收口（两端相距 ≤ tol，接缝落在笔画自身的圆头里），
    尾段单独成笔、两端各有圆头。三档共用同一份中线，拆完仍然逐一对应。
    """
    import math
    out, split = [], 0
    for stroke in strokes:
        segs = stroke.get("segs") or []
        if stroke.get("closed") or stroke.get("dot") or len(segs) < 8:
            out.append(stroke)
            continue
        pts = [segs[0][0]] + [seg[3] for seg in segs]
        n = len(pts)
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        best = None
        for i in range(2, n - 4):
            for j in range(i + 4, n):
                if cum[j] - cum[i] < min_loop:
                    continue
                head, tail = cum[i], cum[-1] - cum[j]
                if head < min_arm and tail < min_arm:
                    continue
                gap = math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1])
                if gap > tol:
                    continue
                if best is None or gap < best[2]:
                    best = (i, j, gap)
        if best is None:
            out.append(stroke)
            continue
        i, j, _ = best
        ring = dict(stroke)
        ring["segs"], ring["closed"] = segs[i:j], True
        head = {k: v for k, v in stroke.items() if k != "closed"}
        tail = {k: v for k, v in stroke.items() if k != "closed"}
        pieces = []
        if i > 0:
            head["segs"] = segs[:i]
            pieces.append(head)
        if j < n - 1:
            tail["segs"] = segs[j:]
            pieces.append(tail)
        out.append(ring)
        out.extend(pieces)
        split += 1
    return out, split


def is_han(cp: int) -> bool:
    """汉字（含扩展区）：决定「孤立碎墨」该不该当脏污清掉。"""
    return (0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF
            or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x3FFFF)


def _dot_blobs(r, chains, han=False):
    """把没被中线盖住的墨团补成圆点。

    `.` `:` `!` 的字点、`ü` 的两点、以及 `让` 左下角那个小点，骨架只有十几个像素，
    「短线一律丢弃」的那几条阈值会把它们整团扔掉，于是字库里就少一个点
    （2026-10-28 主人指出的正是 `让` 左下角）。判据是「近圆形且没有中线穿过」，
    只补这种纯墨团，不会给 `日` 的内腔或正常笔画添油。
    """
    from scipy import ndimage
    from scipy.spatial import cKDTree

    mask, box = r["mask"], r["box"]
    if not mask.any():
        return []
    x0, y0, x1, y1 = box
    samples = []
    for rs, s, L in chains:
        a = np.asarray(rs, float)
        if len(a) > 40:
            a = a[:: len(a) // 40]
        samples.append(np.column_stack((a[:, 0] - x0, y1 - a[:, 1])))
    tree = cKDTree(np.vstack(samples)) if samples else None
    lab, n = ndimage.label(mask)
    dist = r["dist"]
    dots = []
    for k in range(1, n + 1):
        comp = lab == k
        rp = float(dist[comp].max())
        area = int(comp.sum())
        # 面积上下界把「细长条」和「大片墨」都排掉，只留圆点/方点。
        if rp < 2.0 or not 2.2 * rp * rp <= area <= 4.8 * rp * rp:
            continue
        ys, xs = np.nonzero(comp)
        d = dist[comp]
        px, py = float(xs[d >= rp - 1e-9][0]), float(ys[d >= rp - 1e-9][0])
        if tree is not None and tree.query([px, py])[0] <= rp * 0.8:
            continue        # 有中线穿过：那是笔画的一部分，不是孤立的点
        # 汉字里的孤立碎墨：母版 `让` 左下角有一团 78×69 的墨（整字 0.078 em），
        # 同族的 `认·说·话·语·讠` 都没有，位置又在基线下方、与讠和上都断开——
        # 是母版自带的墨点脏污。照抄进字库就是一个凭空多出来的小点（主人 2026-10-28
        # 指出的正是它）。汉字里真正的「点」画法至少 0.11 em（母版 `.` `·` `:` 实测
        # 111～120），所以 0.10 em 以下、又与所有中线都不相交的独立墨团，按脏污清掉。
        # **非汉字一律不动**：`Ǡ` `Ȧ` 头上那种 0.087 em 的重音点是真的点，西文、标点、
        # 假名里的小圆点也都可能比它更小，尺子量不出真假，就不去动它们。
        # 整字只有这一团墨的（`.` `·` 这类标点）也不动：那是这个字的全部墨迹。
        long_side = max(max(xs) - min(xs), max(ys) - min(ys)) / SS
        if han and chains and long_side < 0.10 * 1000:
            continue
        c = (round(px + x0, 1), round(y1 - py, 1))
        dots.append({"closed": False, "dot": True, "hw": round(rp / SS, 2), "segs": [[c, c, c, c]]})
    return dots


def stroke_outline(bezier_list, hw=HW):
    """贝塞尔中线 → 轮廓：2×半宽、圆端头、圆转角，再并成一条路径。

    圆端头 + 圆转角意味着轮廓是「中线与半径 hw 的圆的闵可夫斯基和」，
    拐角和收笔在构造上就是圆弧，没有需要事后修的折角或小角度。
    """
    import pathops

    acc = pathops.Path()
    for item in bezier_list:
        if isinstance(item, dict):
            segs, closed = item["segs"], item.get("closed", False)
        else:
            segs, closed = item, False
        own = item.get("hw") if isinstance(item, dict) else None
        p = pathops.Path()
        p.moveTo(*segs[0][0])
        for seg in segs:
            p.cubicTo(*seg[1], *seg[2], *seg[3])
        if closed:
            p.close()
        p.stroke(2 * (hw if own is None else own),
                 pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
        p.convertConicsToQuads(0.1)
        acc.addPath(p)
    acc.simplify(fix_winding=True, keep_starting_points=False)
    return acc


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/maruko.ttf"
    chars = sys.argv[2] if len(sys.argv) > 2 else "乙了子九"
    for ch in chars:
        out = bezier_strokes(Path(src), ord(ch), dot_r=True)
        if out is None:
            print(f"{ch}: 无字形")
            continue
        print(f'    "{ord(ch):04X}": {{"hw": {out["half_width"]:.2f}, "strokes": [')
        for st in out["strokes"]:
            print(f"        {st!r},")
        print("    ]},")
