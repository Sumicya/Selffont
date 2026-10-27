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

# 母版把两笔连成一笔、二创要断开的地方：(要断开处, 从这里往后保留)。
# `天`：撇的起笔从顶横中点垂下来接住顶横，是 Maruko 的设计；主人要求顶横
# 独立、平，所以在顶横处切断，撇从中横上沿起笔（穿过中横，是「天」的本形）。
DETACH = {0x5929: [((494.0, 709.0), (494.0, 490.0))]}


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
            if not cur:                     # 没有 moveTo 的孤立段，跳过
                continue
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


def _fold_hook(pts, hw, flat=0.35, need=3.0):
    """这条笔画是不是「横折弯钩」：笔身里有一段够长的横。

    只判「末端竖直」会把竖钩（丁/了/子/手）也当折弯钩，那些字去钩后该直着收笔，
    不能捺。横折弯钩的标志是**先横后竖**，所以查笔身里有没有够长的水平段。
    末端的弯不参与判断：Maruko 的钩在底部会先往下再向右上卷 180°，切完之后
    剩下的末段已经是水平的，按末段判会漏。
    """
    P = np.asarray(pts, float)
    if len(P) < 8:
        return False
    d = np.diff(P, axis=0)
    seg = np.hypot(*d.T)
    best = run = 0.0
    for (dx, dy), ln in zip(d, seg):
        run = run + ln if abs(dy) <= flat * abs(dx) else 0.0
        best = max(best, run)
    # 横不能是整条笔画的主体：`也` 的「乚」横段占 64%，那是笔画本身，
    # 不是折弯钩的横，切掉它等于把乚砍成一根斜线。
    return best >= need * hw and best <= 0.5 * float(np.sum(seg))


def _flat_run(pts, hw, at_start, flat=0.35, reach=6.0):
    """从这一端出发，笔身保持水平的弧长。"""
    P = np.asarray(pts, float)
    if not at_start:
        P = P[::-1]
    if len(P) < 4:
        return 0.0
    step = np.hypot(*np.diff(P, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(step)])
    run = 0.0
    for i in range(len(P) - 1):
        if cum[i] > reach * hw:
            break
        dx, dy = P[i + 1] - P[i]
        if abs(dy) > flat * abs(dx):
            break
        run += float(step[i])
    return run


def _na_right(pts, hw):
    """捺往哪一侧落：横是起笔那一端，从它指向带钩的那一端就是书写方向。"""
    a, b = np.asarray(pts[0], float), np.asarray(pts[-1], float)
    if _flat_run(pts, hw, True) >= _flat_run(pts, hw, False):
        return bool((b - a)[0] > 0)
    return bool((a - b)[0] > 0)


def _cut_leg(P, hw, at_start, flat=0.35, run=3, vert=4.0, reach=20.0):
    """从末端往回切到「笔身竖直」的地方，返回要切掉的点数（0 = 没找到竖段）。

    `trim_end` 按累计转角只削掉钩前面那 65°，钩的**斜段**还留在笔身上：
    `九` 切完的那一截方向已经是 (0.87,-0.5)，再按捺势转 60° 就走成了月牙。
    折弯钩的钩是往右上卷的，往回走到出现连续竖直的笔身才是钩真正的根。
    """
    Q = np.asarray(P, float)
    if not at_start:
        Q = Q[::-1]
    if len(Q) < 12:
        return 0
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(Q, axis=0).T))])
    ok = []
    for i in range(1, len(Q) - 1):
        if cum[i] > reach * hw:
            break
        d = Q[i + 1] - Q[i - 1]
        ok.append(abs(d[0]) <= flat * abs(d[1]))
    for i in range(len(ok) - run + 1):
        if all(ok[i:i + run]):
            j = i
            while j < len(ok) and ok[j]:
                j += 1
            # 这段竖直要够长才算真的竖段：`乙` 的钩后面是一条长斜撇，
            # 斜段里偶尔有十几个单位恰好竖直，按那点切会把右半整条切掉。
            if cum[j] - cum[i] >= vert * hw:
                return i + 1
    return 0


def _cut_leg(P, hw, at_start, flat=0.35, run=3, vert=4.0, reach=20.0):
    """从末端往回切到「笔身竖直」的地方，返回要切掉的点数（0 = 没找到竖段）。

    `trim_end` 按累计转角只削掉钩前面那 65°，钩的**斜段**还留在笔身上：
    `九` 切完的那一截方向已经是 (0.87,-0.5)，再按捺势转 60° 就走成了月牙。
    折弯钩的钩是往右上卷的，往回走到出现连续竖直的笔身才是钩真正的根。
    """
    Q = np.asarray(P, float)
    if not at_start:
        Q = Q[::-1]
    if len(Q) < 12:
        return 0
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(Q, axis=0).T))])
    ok = []
    for i in range(1, len(Q) - 1):
        if cum[i] > reach * hw:
            break
        d = Q[i + 1] - Q[i - 1]
        ok.append(abs(d[0]) <= flat * abs(d[1]))
    for i in range(len(ok) - run + 1):
        if all(ok[i:i + run]):
            j = i
            while j < len(ok) and ok[j]:
                j += 1
            # 这段竖直要够长才算真的竖段：`乙` 的钩后面是一条长斜撇，
            # 斜段里偶尔有十几个单位恰好竖直，按那点切会把右半整条切掉。
            if cum[j] - cum[i] >= vert * hw:
                return i + 1
    return 0


def _cut_to_flat(P, hw, at_start, flat=0.18, need=6.0, reach=40.0):
    """从钩那一端往回切到最近一段**长横的折点**，返回 (切掉的点数, 横的书写方向)。

    主人 2026-10-27 对 `九` 的要求是「横 + 捺」接笔：折弯钩整段（折、竖、钩）都不要，
    横收笔后直接接一段捺。所以这里找的不是竖直段而是横段——往回扫，跳过钩，
    遇到第一段够长（≥6×半笔宽）且真的水平（|dy| ≤ 0.18|dx|）的笔身就切到折点。

    0.18 这个角度是按 `九` 的钩底量的：钩底那一小段斜到 |dy/dx|≈0.27，
    用 0.35 会把钩底当横，切在钩上，捺就从钩底斜出去，等于没改。

    方向按「自由端 → 折点」给：横的书写永远是从自由端走向折点，和链条点序
    正反无关（`九` 的链是从钩走到横左端，`也` 的竖弯钩是从竖顶走到钩）。
    """
    Q = np.asarray(P, float)
    if not at_start:
        Q = Q[::-1]
    if len(Q) < 12:
        return 0, None
    step = np.hypot(*np.diff(Q, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(step)])
    run_start = None
    for i in range(len(Q) - 1):
        if cum[i] > reach * hw:
            break
        dx, dy = Q[i + 1] - Q[i]
        if abs(dy) <= flat * abs(dx):
            if run_start is None:
                run_start = i
            continue
        if run_start is not None and cum[i] - cum[run_start] >= need * hw:
            # Q[run_start] 靠钩（折点），Q[i] 远（自由端）：书写方向是自由端 → 折点
            right = bool((Q[run_start] - Q[i])[0] > 0)
            return run_start, right
        run_start = None
    if run_start is not None and cum[-1] - cum[run_start] >= need * hw:
        right = bool((Q[run_start] - Q[-1])[0] > 0)
        return run_start, right
    return 0, None


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


def measure_halfwidth(mask, rs, s, r_hint):
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
                x = int(round((q[0] - BOX[0]) * SS))
                y = int(round((BOX[3] - q[1]) * SS))
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


def _hook_to_na(pts, hw, at_start, box=None, right=True, tail=4.0, angle_deg=30.0):
    """把末端的钩换成一段捺：从切口沿 −30° 直走一截，长度到墨迹框为止。

    比「按半径 2hw 的圆弧旋转」可靠：圆弧要占掉两个半笔宽，在字底（`乙`/`九`
    的钩就在墨迹底边）根本没有那个空间，一转身就掉到框外；直尾只占一个长度，
    转折交给描边的 round join 和样条本身去圆。
    """
    P = np.asarray(pts, float)
    if len(P) < 6:
        return P
    tip = P[0] if at_start else P[-1]
    ang = math.radians(-angle_deg) if right else math.radians(180.0 + angle_deg)
    t = np.array([math.cos(ang), math.sin(ang)])
    length = tail * hw
    if box is not None:
        lim = []
        for k, hi, lo in ((0, box[2], box[0]), (1, box[3], box[1])):
            if t[k] > 1e-6:
                lim.append((hi - tip[k]) / t[k])
            elif t[k] < -1e-6:
                lim.append((lo - tip[k]) / t[k])
        if lim:
            length = max(0.0, min(length, min(lim)))
    n = max(2, int(length / 4.0))
    seg = np.asarray([tip + t * (length * i / n) for i in range(1, n + 1)], float)
    return np.vstack([seg[::-1], P]) if at_start else np.vstack([P, seg])


def bezier_strokes(path: Path, cp: int, hw=None, hook_deg=65.0, detach=(),
                   detach_hw=2.4, dot_r=None):
    """读一个字 → 每条笔画的贝塞尔中线 + 该字实测半宽 + 交叉点圆盘。

    与 `strokes()` 的区别只在末端：这里不把断口补到墨迹极值、也不拉直，
    因为圆端头描边本来就会自然补出半个圆；拉直反而让中线偏离笔身，描边后偏细。

    `detach` 是「在这里把笔画切断」的坐标（母版把两笔连成了一笔、二创要断开，
    例如 `天` 的撇上提到顶横）。`dot_r` 非空时，每个交叉点额外输出一个圆盘
    中线：T 字路口靠它把上沿补成圆弧，不补就是凹口。
    """
    r = analyze(path, cp)
    if r is None:
        return None
    hint = float(r["half_width"]) if hw is None else float(hw)
    mask = np.asarray(r["mask"])
    coords, adj = _graph(r["skeleton"])
    chains, joints = _assemble(coords, adj, hint)
    if not chains:
        return None
    ys, xs = np.nonzero(mask)
    # 捺的中线可走范围 = 母版墨迹框**内缩** 1.1hw。圆端头还会向外加一个 hw，
    # 所以中线收到这里，描边后的尖刚好落在母版墨迹边缘——既不缺墨，也不掉出格子
    # （实测：不内缩时乙/九/几的捺会往右下各多伸 40–50 单位）。
    inset = 1.1 * hint
    ink = (xs.min() / SS + BOX[0] + inset, BOX[3] - ys.max() / SS + inset,
           xs.max() / SS + BOX[0] - inset, BOX[3] - ys.min() / SS - inset)

    raw, probes = [], []
    for c in chains:
        rs, s = _smooth_chain(c, hint)
        L = float(s[-1])
        if L < 1.4 * hint:
            continue
        raw.append((rs, s, L))
        if L > 2.0 * hint:
            probes.append(measure_halfwidth(mask, rs, s, hint))
    if not raw:
        return None
    half = float(np.median(probes)) if probes else hint
    out = []
    for rs, s, L in raw:
        lo, hi = 0.0, L
        # ① 交接断开：端点落在 detach 点附近就把这一截切掉（圆头还会加一个 hw，
        #    所以按 detach_hw 多让一点，切完才真有空隙）。
        for at_start in (True, False):
            tip = np.asarray(rs[0] if at_start else rs[-1], float)
            for spec in detach:
                src = np.asarray(spec[0], float)
                if float(np.hypot(*(tip - src))) > 2.0 * half:
                    continue
                if len(spec) > 1 and spec[1] is not None:
                    k = int(np.argmin(np.hypot(*(rs - np.asarray(spec[1], float)).T)))
                    cut = float(s[k])
                else:
                    d = np.hypot(*(rs - src).T)
                    ok = np.nonzero(d >= detach_hw * half)[0]
                    if not len(ok):
                        continue
                    cut = float(s[ok[0] if at_start else ok[-1]])
                if at_start:
                    lo = max(lo, cut)
                else:
                    hi = min(hi, cut)
        # ② 去钩：切口按累计转角找，切不掉就说明这不是钩。
        cut = {True: False, False: False}
        for at_start in (True, False):
            if (lo > 1e-6) if at_start else (hi < L - 1e-6):
                continue                       # 这一端已经按 detach 切过
            seq = rs if at_start else rs[::-1]
            k = trim_end(seq, half, deg=hook_deg, max_len=5.0)
            if k > 0:
                cut[at_start] = True
                if at_start:
                    lo = max(lo, k)
                else:
                    hi = min(hi, L - k)
        # 短笔画（点）两头都判成钩时会把整条切没：`方` 顶上那一点 200 长，
        # 两端各切 152/68，剩下 −20，笔画直接消失。短到 2.5hw 以下就只切较大的一端。
        if hi - lo < 2.5 * half:
            a_len, b_len = lo, L - hi
            if max(a_len, b_len) > 0 and L - max(a_len, b_len) >= 2.5 * half:
                if b_len >= a_len:
                    lo = 0.0
                else:
                    hi = L
            else:
                lo, hi = 0.0, L
        if hi - lo < 1.0 * half:
            continue
        keep = (s >= lo - 1e-6) & (s <= hi + 1e-6)
        pts = np.asarray(rs, float)[keep]
        if len(pts) < 6:
            continue
        # ③ 收笔：折弯钩去掉钩之后要往右下捺，不能原地竖着收（那样等于钩没去干净）。
        for at_start in (True, False):
            if cut[at_start] and _fold_hook(pts, half):
                k = _cut_leg(pts, half, at_start)
                if k > 0:
                    p2 = pts[k:] if at_start else pts[:-k]
                    body = -_body_dir(p2, half, at_start)
                    # 切完必须真的落在竖直笔身上；`乙` 的钩后面接的是斜下的长撇，
                    # 没有竖段，这种情况退回普通去钩。
                    if abs(body[1]) < 0.8 or len(p2) < 8:
                        k = 0
                if k > 0:
                    # 竖段一直延到字底，整段切掉会明显缩水（`九` 缩 358）。切口
                    # 只放到「捺还走得开」的高度：距墨迹底 3×半笔宽。
                    need_y = ink[1] + 3.0 * half
                    if (pts[0] if at_start else pts[-1])[1] > need_y:
                        side = pts[:k, 1] if at_start else pts[-k:, 1]
                        cand = np.nonzero(side <= need_y)[0]
                        if len(cand):
                            k = int(cand[-1]) + 1 if at_start else k - int(cand[0])
                    pts = pts[k:] if at_start else pts[:-k]
                    if len(pts) >= 8:
                        pts = _hook_to_na(pts, half, at_start, box=ink,
                                          right=_na_right(pts, half))
                        cut[at_start] = False   # 已经按捺收过，别再拉直/补墨
        for at_start in (True, False):
            if not cut[at_start]:
                continue
            # 去钩不等于削短：沿笔身反方向把端头补回母版墨迹的极值（限 2hw）。
            origin = pts[0] if at_start else pts[-1]
            body, d = _tip_out(pts, half, at_start)
            if abs(float(body @ d) - 1.0) > 1e-3:
                pts = _hook_to_na(pts, half, at_start, box=ink,
                                  right=bool(body[0] > 0))
                cut[at_start] = False
                continue
            if abs(body[1]) > 0.6:
                # 竖直收笔不补墨：竖钩的钩是往**侧面**走的，沿着竖方向补只会把
                # 端头拖出一个小圆球（`丁` 实测比母版多凸 25 单位）。
                continue
            body, d = _tip_out(pts, half, at_start)
            ext = min(_ink_reach(mask, origin, d, half, 2.0 * half), 2.0 * half)
            if ext >= 0.3 * half:
                tip = (np.asarray(origin, float) + d * ext)[None, :]
                pts = np.vstack([tip, pts]) if at_start else np.vstack([pts, tip])
        segs = spline_beziers(pts)
        if segs:
            out.append({"closed": False,
                        "segs": [[tuple(round(float(q), 1) for q in pt) for pt in seg]
                                 for seg in segs]})
    if dot_r:
        for j in joints:
            c = (round(float(j[0]), 1), round(float(j[1]), 1))
            out.append({"closed": False, "segs": [[c, c, c, c]]})
    return dict(half_width=half, strokes=out)


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
        p = pathops.Path()
        p.moveTo(*segs[0][0])
        for seg in segs:
            p.cubicTo(*seg[1], *seg[2], *seg[3])
        if closed:
            p.close()
        p.stroke(2 * hw, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
        p.convertConicsToQuads(0.1)
        acc.addPath(p)
    acc.simplify(fix_winding=True, keep_starting_points=False)
    return acc


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/maruko.ttf"
    chars = sys.argv[2] if len(sys.argv) > 2 else "乙了子九"
    for ch in chars:
        out = bezier_strokes(Path(src), ord(ch),
                             detach=DETACH.get(ord(ch), ()), dot_r=True)
        if out is None:
            print(f"{ch}: 无字形")
            continue
        print(f'    "{ord(ch):04X}": {{"hw": {out["half_width"]:.2f}, "strokes": [')
        for st in out["strokes"]:
            print(f"        {st!r},")
        print("    ]},")
