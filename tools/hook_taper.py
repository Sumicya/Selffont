"""按根线（骨架）去钩：钩根切、顺笔势收成横捺。

前几版的根本错误
----------------
`hook_erase.find_hooks` 返回 `(cut, removed, width)`。`removed` 是从**钩根**到**钩尖**的
骨架像素序列：`removed[0]` 是钩根（与笔身连接处），`removed[-1]` 是钩尖。而 `cut` 在
不同分支上取的位置不同——实测 `九` 的 `cut` 就**正好等于钩尖**。前几版拿 `cut` 当钩根，
等于在钩尖上开工，所以钩永远去不干净。

本版的定式
----------
1. **钩根** = `removed[0]`。
2. **笔势 d** = 从骨架上的笔身点 B（钩根往回约 0.7 倍笔宽）指向钩根的方向。
3. **半笔宽 r** = 整字骨架距离变换的中位数（钩根处的距离变换会塌成 3px，不可用）。
4. 过钩根、垂直于 d 的直线与轮廓（含曲线，de Casteljau 二分）求交，得到切口两点
   S、E；它们天然落在轮廓上，不留缝。
5. 用 (d, n) 局部坐标系建一个**收尖**：S 沿原切线出发，在轴线上距钩根 L 处收成尖，
   再回到 E。这就是"横捺"——不是接一个圆头。
6. 曲线精确分裂，不展平、不重采样。

用法：
    python3 tools/hook_taper.py 输入.ttf 输出.ttf --chars 九气也
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from scipy import ndimage
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_cut import split_contours  # noqa: E402
from hook_erase import _edges, _graph, find_hooks as raster_hooks  # noqa: E402
from hook_erase import TRIM_LENGTH_RATIO as TIP_TRIM_RATIO
from stroke_width_normalize_prototype import raster_mask  # noqa: E402

SAMPLE = 32
TAPER = 2.1        # 收尖长度 / 半笔宽
SIDE_K = 0.46      # 侧边起手控制点系数（× 弦长）
AXIS_M = 0.34      # 收尖前轴向下压系数（× 弦长）
TIP_E = 0.20       # 尖端横向错开（× 半笔宽），保证是个楔形而不是对折
FLAT_MAX = 20.0    # 切口处允许的"水平"偏差（度）
FLAT_BACK = 2.6    # 沿骨架往回最多找多远（× 半笔宽）
FLAT_MIN = 0.30    # 最近也至少离开钩根这么远（× 半笔宽）
FLAT_TURN = 25.0   # 与钩根笔势至少差这么多度，才认为钩后确实转了弯（度）


_DEBUG = bool(os.environ.get("HOOK_TAPER_DEBUG"))


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _side(p, origin, direction):
    return _cross((p[0] - origin[0], p[1] - origin[1]), direction)


def _norm(v):
    d = math.hypot(*v) or 1.0
    return (v[0] / d, v[1] / d)


def segments_of(contour):
    """把轮廓拆成 [(kind, p0, ctrls, p1, insert_at)]。

    `insert_at` 是"在 p1 处插入新 on-curve 点"时应该用的**轮廓索引**。
    连续多个 off-curve 会被拆成多段，此时 p1 是隐式中点（不在轮廓里），
    各段的插入位置各不相同 —— 之前所有段共用同一个起点索引，插入点错位，
    这就是每一版都留缺口的原因。
    """
    n = len(contour)
    on_idx = [i for i in range(n) if contour[i][2]]
    if not on_idx:
        return []
    segs = []
    for k, i in enumerate(on_idx):
        j = on_idx[(k + 1) % len(on_idx)]
        p0 = (contour[i][0], contour[i][1])
        p1 = (contour[j][0], contour[j][1])
        offs = []
        m = (i + 1) % n
        while m != j:
            offs.append(((contour[m][0], contour[m][1]), m))
            m = (m + 1) % n
        if not offs:
            segs.append(("line", p0, [], p1, j))
        elif len(offs) == 1:
            segs.append(("quad", p0, [offs[0][0]], p1, j))
        else:
            # 连续 off-curve：按 TT 隐含中点拆段，每段插入点 = 下一个 off 点的索引。
            # 起点必须是**上一段的终点**（隐式中点），不能拿下一个 off 点当起点——
            # 那样曲线整条被搬走，`乙` 左下角因此多出一个突起。
            cur = p0
            for t in range(len(offs)):
                c = offs[t][0]
                if t + 1 < len(offs):
                    nxt = offs[t + 1][0]
                    end = ((c[0] + nxt[0]) / 2, (c[1] + nxt[1]) / 2)
                    at = offs[t + 1][1]
                else:
                    end = p1
                    at = j
                segs.append(("quad", cur, [c], end, at))
                cur = end
    return segs


def _quad_at(p0, c, p1, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
            u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])


def _split_quad(p0, c, p1, t):
    a = (p0[0] + (c[0] - p0[0]) * t, p0[1] + (c[1] - p0[1]) * t)
    b = (c[0] + (p1[0] - c[0]) * t, c[1] + (p1[1] - c[1]) * t)
    m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return (p0, a, m), (m, b, p1)


def tangent_of(contour, seg_index, t):
    kind, p0, ctrls, p1, _at = segments_of(contour)[seg_index]
    if kind == "line":
        return _norm((p1[0] - p0[0], p1[1] - p0[1]))
    c = ctrls[0]
    u = 1 - t
    return _norm((2 * u * (c[0] - p0[0]) + 2 * t * (p1[0] - c[0]),
                  2 * u * (c[1] - p0[1]) + 2 * t * (p1[1] - c[1])))


def cut_points(contour, origin, direction):
    hits = []
    for si, (kind, p0, ctrls, p1, _at) in enumerate(segments_of(contour)):
        if kind == "line":
            e = (p1[0] - p0[0], p1[1] - p0[1])
            den = _cross(e, direction)
            if abs(den) < 1e-12:
                continue
            w = (origin[0] - p0[0], origin[1] - p0[1])
            t = _cross(w, direction) / den
            s = _cross(w, e) / den
            if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= s <= 1 + 1e-9:
                pt = (p0[0] + e[0] * t, p0[1] + e[1] * t)
                hits.append((_dist(pt, origin), si, t, pt))
            continue
        c = ctrls[0]
        prev = _quad_at(p0, c, p1, 0.0)
        prev_s = _side(prev, origin, direction)
        for k in range(1, SAMPLE + 1):
            t = k / SAMPLE
            pt = _quad_at(p0, c, p1, t)
            s = _side(pt, origin, direction)
            if prev_s == 0 or s == 0 or (s > 0) != (prev_s > 0):
                lo, hi = (k - 1) / SAMPLE, t
                for _ in range(48):
                    mid = (lo + hi) / 2
                    if (_side(_quad_at(p0, c, p1, mid), origin, direction) > 0) == (prev_s > 0):
                        lo = mid
                    else:
                        hi = mid
                tt = (lo + hi) / 2
                pt = _quad_at(p0, c, p1, tt)
                hits.append((_dist(pt, origin), si, tt, pt))
                break
            prev, prev_s = pt, s
    return hits


def insert_point(contour, seg_index, t):
    """在指定段的参数 t 处插入 on-curve 点，返回 (新轮廓, 新点下标)。"""
    kind, p0, ctrls, p1, at = segments_of(contour)[seg_index]
    if kind == "line":
        mid = (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
        if at >= len(contour):
            contour.append((mid[0], mid[1], True))
            return contour, len(contour) - 1
        contour.insert(at, (mid[0], mid[1], True))
        return contour, at
    left, right = _split_quad(p0, ctrls[0], p1, t)
    new = [(left[1][0], left[1][1], False), (left[2][0], left[2][1], True),
           (right[1][0], right[1][1], False)]
    if at >= len(contour):
        contour.extend(new)
        return contour, len(contour) - 2
    for k, pt in enumerate(new):
        contour.insert(at + k, pt)
    return contour, at + 1





def _nearest_on_path(path, pt):
    """返回 (弧长 s, 路径点索引 i, 插值中心线点, 切向单位向量)。"""
    best = None
    s_acc = 0.0
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L2 = ex * ex + ey * ey
        if L2 < 1e-12:
            continue
        t = ((pt[0] - a[0]) * ex + (pt[1] - a[1]) * ey) / L2
        t = max(0.0, min(1.0, t))
        qx, qy = a[0] + ex * t, a[1] + ey * t
        dd = (pt[0] - qx) ** 2 + (pt[1] - qy) ** 2
        if best is None or dd < best[0]:
            seg_len = math.sqrt(L2)
            best = (dd, s_acc + seg_len * t, i, t, seg_len)
        s_acc += math.sqrt(L2)
    dd, s_, i_, t_, _sl = best
    a, b = path[i_], path[i_ + 1]
    q = (a[0] + (b[0] - a[0]) * t_, a[1] + (b[1] - a[1]) * t_)
    e = _norm((b[0] - a[0], b[1] - a[1]))
    return s_, math.sqrt(dd), q, e


def _turn_at(path, i, span):
    """骨架在 path[i] 处的折返角（度）：笔尖→这点 与 这点→笔身 的夹角。

    0° = 笔直延续（撇、横的起笔端），180° = 整个折回来。
    这是钩与普通笔画端头最干净的分界：实测普通端头 1–47°，
    真钩 68–124°（`九` 124、`了` 底 76、`子` 底 68）。
    """
    a = path[max(0, i - span)] if i - span >= 0 else path[0]
    b = path[i]
    c = path[min(len(path) - 1, i + span)]
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def find_tip_curls(mask, skeleton=None, distance=None, trim=TIP_TRIM_RATIO,
                   min_body=3.0, min_turn=55.0):
    """按**笔画末端 + 折返角**找钩：只有真的折回来的末端才算钩。

    为什么不沿用 `hook_erase.find_hooks` 的位置
    --------------------------------------------
    它给的两类命中在这 8 个字上分不开：
      · 真钩挂在笔画末端（`九` 16.0W、`也` 9.9W、`包` 14.6W、`必` 8.7W、`電` 11.1W）；
      · 假钩是骨架在撇/竖转角处分叉出来的**短刺**，只有 1.1–1.25W
        （`了` 1.25W、`子` 1.11W）。在那种地方下刀就是切笔画的转角，
        `了` 的横撇左端因此被整块吃掉（xmin 94 → 266）。

    所以这里只认「一端是骨架笔尖、另一端是分叉点、整条边 ≥ min_body 倍笔宽、
    且末端折返角 ≥ min_turn」的边：从笔尖往内 trim 处下刀。两端都是笔尖的
    独立笔画（点/撇/捺）不碰。

    返回格式与 `find_hooks` 一致：[(cut_point, removed_path, width_px)]，
    路径是笔尖 → 切点方向。
    """
    skeleton = skeletonize(mask) if skeleton is None else skeleton
    distance = ndimage.distance_transform_edt(mask) if distance is None else distance
    width_px = float(np.median(distance[skeleton]) * 2)
    if not np.isfinite(width_px) or width_px <= 1.0:
        return []
    _pixels, adjacency = _graph(skeleton)
    _nodes, edges = _edges(adjacency)
    span = max(2, int(0.5 * width_px))
    out = []
    for edge in edges:
        for path in (edge, list(reversed(edge))):
            if len(adjacency[path[0]]) != 1:
                continue
            if len(path) < min_body * width_px:
                continue
            if len(adjacency[path[-1]]) == 1:
                continue            # 两端都是笔尖：点/撇/捺，不碰
            trimmed = min(len(path) - 1, max(2, int(trim * width_px)))
            if _turn_at(path, trimmed, span) < min_turn:
                continue
            out.append((path[trimmed - 1], path[:trimmed], width_px))
            break
    return out


def _dense(contour, step=2.5):
    """把轮廓按弧长细分成折线，返回 [(x, y, seg_index, t)]。

    只用于**搜索**候选横截面；最终切点用 de Casteljau 在原曲线上精确定位，
    所以细分不影响输出精度。
    """
    out = []
    for si, (kind, p0, ctrls, p1, _at) in enumerate(segments_of(contour)):
        if kind == "line":
            length = _dist(p0, p1)
        else:
            length = _dist(p0, ctrls[0]) + _dist(ctrls[0], p1)
        n = max(2, min(80, int(length / step) + 1))
        for k in range(n):
            t = k / n
            if kind == "line":
                out.append((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t, si, t))
            else:
                q = _quad_at(p0, ctrls[0], p1, t)
                out.append((q[0], q[1], si, t))
    return out


def best_cut_at_tip(contour, tip, r, radius_tol=0.28, chord_tol=0.16):
    """以**笔尖**为基准找横截面：半径 = 笔尖处的局部半笔宽。

    这是「只去钩」的正确做法。钩在骨架上不分叉，是笔画末端的外扬；从笔尖往外找
    弦长 = 2r、两端等距的那条线，被它切掉的弧长实测 **3.1–3.7r**，正好是钩的长度。
    旧做法从钩根往里切，弧长 9.8r，把笔身也带走了（`乙` 因此看着还有钩）。

    返回与 `best_cut` 同构：(C, u, (siS,tS,pS), (siE,tE,pE), chord, 0.0, r)。
    """
    n_ = len(contour)
    if n_ < 4:
        return None
    from scipy.spatial import cKDTree

    dense = _dense(contour, 2.0)
    pts = np.array([(d[0], d[1]) for d in dense], dtype=float)
    smp2 = _samples(contour)
    nsm2 = len(smp2)
    cum2 = [0.0]
    for _i in range(nsm2):
        cum2.append(cum2[-1] + _dist(smp2[_i][2], smp2[(_i + 1) % nsm2][2]))
    per2 = cum2[-1]

    def _sidx_arr(pt):
        return min(range(nsm2), key=lambda _i: _dist(smp2[_i][2], pt))

    cum = np.zeros(len(pts))
    for i in range(1, len(pts)):
        cum[i] = cum[i - 1] + float(np.hypot(*(pts[i] - pts[i - 1])))
    per = cum[-1] + float(np.hypot(*(pts[0] - pts[-1])))
    tree = cKDTree(pts)
    Q = np.array(tip, dtype=float)
    near = tree.query_ball_point(Q, 1.4 * r)
    best = None
    for a in near:
        da = float(np.hypot(*(pts[a] - Q)))
        if abs(da - r) > radius_tol * r:
            continue
        tgt = Q + (Q - pts[a]) / da * r
        _dt, b = tree.query(tgt)
        db = float(np.hypot(*(pts[b] - Q)))
        if abs(db - r) > radius_tol * r:
            continue
        ua, ub = (pts[a] - Q) / da, (pts[b] - Q) / max(db, 1e-9)
        if float(ua @ ub) > -0.72:          # 必须几乎正对
            continue
        # 两端必须都在笔尖附近（1.9r 内）。不加这条时，配对会跨到整字另一头，
        # `必`/`電` 的包围盒因此跳过 675/748——那不是钩，是别的笔画。
        # 1.9r 是上限：笔尖处的横截面本来就不完全对称（`必` 一侧 31、另一侧 40）。
        if max(da, db) > 1.9 * r:
            continue
        chord = float(np.hypot(*(pts[b] - pts[a])))
        err = abs(chord - 2 * r) / (2 * r)
        sym = abs(da - db) / r
        score = err + sym
        if err > chord_tol:
            continue
        d_ab = cum[max(a, b)] - cum[min(a, b)]
        del_len = min(d_ab, per - d_ab)
        # 被删的必须是**小段**：钩 3–4r。放宽到 1.2–6r，超出说明配对跨了笔身。
        if not (1.2 * r <= del_len <= 6.0 * r):
            continue
        if best is not None and score >= best[0]:
            continue
        d0 = _norm((float(pts[b][0] - pts[a][0]), float(pts[b][1] - pts[a][1])))
        hits = cut_points(contour, (float(pts[a][0]), float(pts[a][1])), d0)
        if len(hits) < 2:
            continue
        h1 = min(hits, key=lambda h: _dist(h[3], (pts[a][0], pts[a][1])))
        h2 = min(hits, key=lambda h: _dist(h[3], (pts[b][0], pts[b][1])))
        if h1 is h2:
            continue
        pA, pB = h1[3], h2[3]
        exact = _dist(pA, pB)
        if abs(exact - 2 * r) > 0.20 * 2 * r:
            continue
        C = ((pA[0] + pB[0]) / 2, (pA[1] + pB[1]) / 2)
        u = _norm((pB[0] - pA[0], pB[1] - pA[1]))
        # S→E 必须顺着**轮廓参数方向**指向要删的那一小块。这里直接用采样索引
        # （`sidx`，与 `process` 里判定 S/E 用的是同一套）定顺序：从 h1 沿轮廓
        # 走到 h2 的那段如果更短，就是 S=h1、E=h2。
        # 不定顺序时 `kept` 会保留 6 个点、整个字被切掉（`必` 的包围盒跳 675）。
        i1, i2 = _sidx_arr(h1[3]), _sidx_arr(h2[3])
        forward = (cum2[i2] - cum2[i1]) % per2
        if forward <= per2 - forward:
            hS_, hE_ = h1, h2
        else:
            hS_, hE_ = h2, h1
        best = (score, C, u, (hS_[1], hS_[2], hS_[3]), (hE_[1], hE_[2], hE_[3]),
                exact, 0.0, exact / 2)
    return None if best is None else best[1:]


def best_cut(contour, path, tip, r, hook_pts=None, widths=None):
    """沿骨架找**真正的横截面**：过骨架点、两端到它都等于局部半笔宽的那条线。

    为什么不是「骨架切向的垂线」：骨架切向是**局部**的，在弯段上不等于横截面法向。
    实测 `九` 差约 25°，弦被拉长到 1.11×2r，端头就比笔身宽 11%（脓包）；正圆还有
    一半悬在笔画外（`也` 的圆内墨迹只剩 22.5%，那就是缺口）。

    为什么这样找才快：以前逐度射线求交，每次求交都要遍历全部曲线段并二分，一个字
    要 10 秒以上。横截面有个等价定义——**轮廓上到骨架点等距（= r）的一对点**——所以
    可以先按弧长细分轮廓建 KD 树，再从每个候选骨架点出发查「对面 r 处的点」，
    复杂度从 180×段数 降到 点对数。

    `path` 是从钩根往笔身走的一串骨架点，`widths` 是各点的局部半笔宽（字体单位）。
    """
    n_ = len(path)
    if n_ < 4:
        return None
    from scipy.spatial import cKDTree

    arc = [0.0]
    for i in range(n_ - 1):
        arc.append(arc[-1] + _dist(path[i], path[i + 1]))
    dense = _dense(contour, 2.5)
    pts = np.array([(d[0], d[1]) for d in dense], dtype=float)
    cum = np.zeros(len(pts))
    for i in range(1, len(pts)):
        cum[i] = cum[i - 1] + float(np.hypot(*(pts[i] - pts[i - 1])))
    per = cum[-1] + float(np.hypot(*(pts[0] - pts[-1])))
    tree = cKDTree(pts)

    def arc_between(i, j):
        d = cum[j] - cum[i] if j >= i else per - (cum[i] - cum[j])
        return d, per - d

    best = None
    for i in range(n_):
        # 切点必须在**钩之外**：从钩根往笔身里走 0.2–2.2 倍半宽。
        if not (0.2 * r <= arc[i] <= 2.2 * r):
            continue
        rl = widths[i] if widths else r
        if rl < 0.45 * r or rl > 1.5 * r:
            continue
        Q = np.array(path[i], dtype=float)
        near = tree.query_ball_point(Q, 1.25 * rl)
        if len(near) < 2:
            continue
        for a in near:
            da = float(np.hypot(*(pts[a] - Q)))
            if abs(da - rl) > 0.22 * rl:
                continue
            # 对侧目标点：从 a 穿过 Q，再走 rl
            tgt = Q + (Q - pts[a]) / da * rl
            _dt, b = tree.query(tgt)
            db = float(np.hypot(*(pts[b] - Q)))     # Q 到 b 的距离，不是到目标的距离
            if abs(db - rl) > 0.22 * rl:
                continue
            ua, ub = (pts[a] - Q) / da, (pts[b] - Q) / max(db, 1e-9)
            if float(ua @ ub) > -0.80:      # 必须几乎正对
                continue
            chord = float(np.hypot(*(pts[b] - pts[a])))
            err = abs(chord - 2 * rl) / (2 * rl)
            sym = abs(da - db) / rl
            score = err + 0.5 * sym
            if score > 0.20:
                continue
            d_ab, d_ba = arc_between(int(a), int(b))
            # 被删的必须是**短弧**：一段绕过钩尖，另一段绕整字一大圈。
            if d_ab <= d_ba:
                iS_poly, iE_poly, del_len = int(a), int(b), d_ab
            else:
                iS_poly, iE_poly, del_len = int(b), int(a), d_ba
            # 钩的弧长是 6–10 倍半宽；上限按轮廓 1/4 与 12r 取小。
            if del_len < 1.5 * rl or del_len > min(0.25 * per, 12.0 * rl):
                continue
            full = score - 0.12 * arc[i] / r
            if best is not None and full >= best[0]:
                continue
            # 原曲线上的精确切点：用这对点的连线方向求交，再取离两端最近的两个交点。
            d0 = _norm((pts[b][0] - pts[a][0], pts[b][1] - pts[a][1]))
            hits = cut_points(contour, (float(pts[a][0]), float(pts[a][1])), d0)
            if len(hits) < 2:
                continue
            h1 = min(hits, key=lambda h: _dist(h[3], (pts[a][0], pts[a][1])))
            h2 = min(hits, key=lambda h: _dist(h[3], (pts[b][0], pts[b][1])))
            if h1 is h2:
                continue
            pA, pB = h1[3], h2[3]
            exact = _dist(pA, pB)
            if abs(exact - 2 * rl) > 0.12 * 2 * rl:
                continue
            iA, iB = int(a), int(b)
            d_ab2, d_ba2 = arc_between(iA, iB)
            if d_ab2 <= d_ba2:
                hS, hE = h1, h2
            else:
                hS, hE = h2, h1
            C = ((pA[0] + pB[0]) / 2, (pA[1] + pB[1]) / 2)
            u = _norm((pB[0] - pA[0], pB[1] - pA[1]))
            best = (full, C, u, (hS[1], hS[2], hS[3]), (hE[1], hE[2], hE[3]),
                    exact, arc[i], exact / 2)
    return None if best is None else best[1:]

def _samples(contour, per=12):
    """把轮廓稠密采样成 [(seg, t, pt)]，段序即轮廓序。"""
    out = []
    for si, (kind, p0, ctrls, p1, _at) in enumerate(segments_of(contour)):
        c = ctrls[0] if ctrls else None
        for k in range(per):
            t = k / per
            pt = _quad_at(p0, c, p1, t) if kind == "quad" else (
                p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
            out.append((si, t, pt))
    return out


def _bisect_zero(contour, seg, t_in, t_out, P, d):
    """在 [t_in, t_out]（同为 seg 参数）上二分找 s = (p-P)·d 的零点。"""
    kind, p0, ctrls, p1, _at = segments_of(contour)[seg]
    c = ctrls[0] if ctrls else None
    def pt_at(t):
        return _quad_at(p0, c, p1, t) if kind == "quad" else (
            p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
    lo, hi = (t_in, t_out) if t_in < t_out else (t_out, t_in)
    flo = (lambda q: (q[0] - P[0]) * d[0] + (q[1] - P[1]) * d[1])(pt_at(lo)) > 0
    for _ in range(48):
        mid = (lo + hi) / 2
        if (((pt_at(mid)[0] - P[0]) * d[0] + (pt_at(mid)[1] - P[1]) * d[1]) > 0) == flo:
            lo = mid
        else:
            hi = mid
    t = (lo + hi) / 2
    return t, pt_at(t)


def _despike(pts, thresh=2.0, passes=2):
    """掐掉针状顶点与重合点。

    半圆端头落好以后，接缝处偶尔会留下一个离邻居 40 多个单位、夹角 180° 的
    针尖（`也` 端头右下一根发丝）。它离前后两点连线不到 2 个单位，删掉形状
    不变；不删放大就是瑕疵。
    """
    for _ in range(passes):
        if len(pts) <= 8:
            break
        out, removed = [], False
        n = len(pts)
        for i in range(n):
            x, y, on = pts[i]
            px, py = pts[i - 1][0], pts[i - 1][1]
            nx, ny = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
            if (math.hypot(x - px, y - py) < 0.5 and math.hypot(x - nx, y - ny) < 0.5):
                removed = True
                continue
            if on:
                ax, ay = x - px, y - py
                bx, by = nx - x, ny - y
                area2 = abs(ax * by - ay * bx)
                longest = max(math.hypot(ax, ay), math.hypot(bx, by),
                              math.hypot(nx - px, ny - py))
                if 1e-9 < longest < 60 and area2 / longest < thresh:
                    removed = True
                    continue
            out.append(pts[i])
        pts = out
        if not removed:
            break
    return pts


def build_round_cap(S, E, n, quads=4):
    """切口上直接扣一个标准半圆：直径就是切口，半径 = 弦的一半。

    不做任何外伸、不收窄、不加直段——钩切掉多少，端头就停在哪儿。
    半圆的两端正好落在切口两端，端头最宽处就是切口本身，所以它只可能等于
    笔宽、不可能比笔身胖；切口垂直于笔势时，半圆在端点处的切线也正好顺着
    笔身两侧走，接缝一阶连续。
    """
    r = _dist(S, E) / 2
    if r < 1e-6:
        return []
    C = ((S[0] + E[0]) / 2, (S[1] + E[1]) / 2)
    u = _norm((S[0] - C[0], S[1] - C[1]))
    coef = math.cos(math.pi / (2 * quads))
    out = []
    for q in range(quads):
        t0 = math.pi * q / quads
        t1 = math.pi * (q + 1) / quads
        tm = (t0 + t1) / 2
        out.append((C[0] + r / coef * (u[0] * math.cos(tm) + n[0] * math.sin(tm)),
                    C[1] + r / coef * (u[1] * math.cos(tm) + n[1] * math.sin(tm)), False))
        if q < quads - 1:
            out.append((C[0] + r * (u[0] * math.cos(t1) + n[0] * math.sin(t1)),
                        C[1] + r * (u[1] * math.cos(t1) + n[1] * math.sin(t1)), True))
    out.append((E[0], E[1], True))
    return out


def _dir_fwd(contour, segs, si, t):
    """轮廓在 (si,t) 处沿前进方向的单位切向。"""
    kind, p0, ctrls, p1, _at = segs[si]
    if kind == "quad" and ctrls:
        c = ctrls[0]
        u = 1 - t
        return _norm((2 * u * (c[0] - p0[0]) + 2 * t * (p1[0] - c[0]),
                      2 * u * (c[1] - p0[1]) + 2 * t * (p1[1] - c[1])))
    return _norm((p1[0] - p0[0], p1[1] - p0[1]))


def _dir_at(contour, idx):
    """轮廓在 idx 处的单位切向（用左右最近的 on-curve 点做中心差分）。"""
    n = len(contour)
    a = (idx - 1) % n
    for _ in range(n):
        if contour[a][2]:
            break
        a = (a - 1) % n
    b = (idx + 1) % n
    for _ in range(n):
        if contour[b][2]:
            break
        b = (b + 1) % n
    return _norm((contour[b][0] - contour[a][0], contour[b][1] - contour[a][1]))


def _nearest_param(contour, T):
    """轮廓上离 T 最近的参数 (seg_index, t)，用来定位钩尖所在的那一段弧。"""
    best = None
    for si, (kind, p0, ctrls, p1, _at) in enumerate(segments_of(contour)):
        c = ctrls[0] if ctrls else None
        for k in range(SAMPLE + 1):
            t = k / SAMPLE
            if kind == "quad":
                pt = _quad_at(p0, c, p1, t)
            else:
                pt = (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
            dd = _dist(pt, T)
            if best is None or dd < best[0]:
                best = (dd, si, t)
    return best[1], best[2]



def circle_hits(contour, C, r):
    """轮廓与圆 |p-C|=r 的交点列表 [(seg, t, pt)]。

    用圆而不是直线去切：笔身弯曲时，过切点的法线切出来的弦会**比笔宽长**
    （`九` 是 75.2 vs 69.6），按那条弦做半圆，端头就比笔身粗，看起来是个鼓包。
    圆弧的半径直接取半笔宽，交点又严格落在圆上，端头粗细才对得上。
    """
    hits = []
    for si, (kind, p0, ctrls, p1, _at) in enumerate(segments_of(contour)):
        c = ctrls[0] if ctrls else None
        prev = p0
        pg = _dist(prev, C) - r
        for k in range(1, SAMPLE + 1):
            t = k / SAMPLE
            pt = _quad_at(p0, c, p1, t) if kind == "quad" else (
                p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
            g = _dist(pt, C) - r
            if (pg > 0) != (g > 0):
                lo, hi, glo = (k - 1) / SAMPLE, t, pg
                for _ in range(48):
                    mid = (lo + hi) / 2
                    q = _quad_at(p0, c, p1, mid) if kind == "quad" else (
                        p0[0] + (p1[0] - p0[0]) * mid, p0[1] + (p1[1] - p0[1]) * mid)
                    if (_dist(q, C) - r > 0) == (glo > 0):
                        lo = mid
                    else:
                        hi = mid
                tt = (lo + hi) / 2
                q = _quad_at(p0, c, p1, tt) if kind == "quad" else (
                    p0[0] + (p1[0] - p0[0]) * tt, p0[1] + (p1[1] - p0[1]) * tt)
                hits.append((si, tt, q))
            prev, pg = pt, g
    return hits


def build_arc(S, E, C, r, d):
    """圆心 C、半径 r 的正圆弧，从 S 绕经 C+r*d 到 E，按 ≤90° 拆成二次贝塞尔。"""
    aS = math.atan2(S[1] - C[1], S[0] - C[0])
    aE = math.atan2(E[1] - C[1], E[0] - C[0])
    aD = math.atan2(d[1], d[0])
    ccw = (aE - aS) % (2 * math.pi)
    through = (aD - aS) % (2 * math.pi)
    if through > ccw:          # 正向不过 d，说明要走反向
        ccw -= 2 * math.pi
    n = max(1, int(math.ceil(abs(ccw) / (math.pi / 2))))
    step = ccw / n
    coef = math.cos(abs(step) / 2)
    out = []
    for q in range(n):
        t0 = aS + step * q
        t1 = t0 + step
        tm = (t0 + t1) / 2
        ctrl = (C[0] + r / coef * math.cos(tm), C[1] + r / coef * math.sin(tm))
        out.append((ctrl[0], ctrl[1], False))
        if q < n - 1:
            out.append((C[0] + r * math.cos(t1), C[1] + r * math.sin(t1), True))
    out.append((E[0], E[1], True))
    return out


def _body_path(start, banned, sk, reach):
    """从钩根出发，在骨架（去掉钩）上 BFS，返回（根→最远点）的有序路径。"""
    seen = {start}
    parent = {}
    frontier = [start]
    best, best_d = start, 0.0
    while frontier:
        nxt = []
        for p in frontier:
            for q in _adjacency(p, sk):
                if q in seen or q in banned:
                    continue
                seen.add(q)
                parent[q] = p
                nxt.append(q)
                dd = math.hypot(q[1] - start[1], q[0] - start[0])
                if dd <= reach and dd > best_d:
                    best, best_d = q, dd
        if not nxt:
            break
        frontier = nxt
    path = [best]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def choose_cut(root, banned, sk, r, upp, to_font, d_root):
    """沿骨架往回找**笔势最接近水平**的点作为切口，返回 (P, d) 或 None。

    为什么不在钩根切：`九` 的钩根处笔势已经是 50° 上扬，切在根上，半圆就朝
    右上鼓，读起来是"竖弯"而不是"横捺"。往回走到笔势变平的那一点（也就是
    弯钩真正起弯之前），切口的法线垂直于笔势、半圆轴线水平，收笔才是横捺，
    而且切口与笔身相切，接缝不出角——不需要任何附加变形。
    """
    reach = FLAT_BACK * r / upp
    path = _body_path(root, banned, sk, reach)
    if len(path) < 6:
        return None
    k = max(2, int(round(0.15 * r / upp)))
    target = 0.0 if d_root[0] >= 0 else 180.0
    ang_root = math.degrees(math.atan2(d_root[1], d_root[0]))
    best = None
    for i in range(k, len(path) - k):
        py, px = path[i]
        dist = math.hypot(px - root[1], py - root[0]) * upp
        if not (FLAT_MIN * r <= dist <= FLAT_BACK * r):
            continue
        a = path[i - k]
        b = path[i + k]
        dx = (b[1] - a[1])
        dy = -(b[0] - a[0])          # 栅格 y 朝下，字体 y 朝上
        if dx == 0 and dy == 0:
            continue
        # 路径是**从钩根往外**走的，笔势（笔往钩那边走的方向）正好相反。
        ang = math.degrees(math.atan2(-dy, -dx))
        dev = abs((ang - target + 180) % 360 - 180)
        if dev > FLAT_MAX:
            continue
        turn = abs((ang - ang_root + 180) % 360 - 180)
        if turn < FLAT_TURN:
            continue
        if best is None or dev < best[0]:
            best = (dev, py, px, dx, dy)
    if best is None:
        return None
    _, py, px, dx, dy = best
    P = to_font(py, px)
    d = _norm((-dx, -dy))
    return P, d


def _adjacency(p, sk):
    y, x = p
    out = []
    h, w = sk.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            yy, xx = y + dy, x + dx
            if 0 <= yy < h and 0 <= xx < w and sk[yy, xx]:
                out.append((yy, xx))
    return out


def _root_of(removed, sk, reach=400):
    """返回 `removed` 两端里真正连着笔身的那一端（钩根）。"""
    banned = {(int(p[0]), int(p[1])) for p in removed}
    ends = [(int(removed[0][0]), int(removed[0][1])), (int(removed[-1][0]), int(removed[-1][1]))]
    best, best_count = ends[0], -1
    for e in ends:
        seen = {e}
        queue = [e]
        count = 0
        while queue and count < reach:
            y, x = queue.pop()
            for q in _adjacency((y, x), sk):
                if q in seen or q in banned:
                    continue
                seen.add(q)
                queue.append(q)
                count += 1
        if count > best_count:
            best, best_count = e, count
    return best



def _walk_out(start, banned, sk, target_dist):
    """在骨架上从 start 向外走（不经过 banned），返回离 start 最接近 target_dist 的点。"""
    seen = {start}
    frontier = [start]
    best = None
    best_d = 0.0
    while frontier:
        nxt = []
        for p in frontier:
            for q in _adjacency(p, sk):
                if q in seen or q in banned:
                    continue
                seen.add(q)
                nxt.append(q)
                dd = math.hypot(q[1] - start[1], q[0] - start[0])
                if dd <= target_dist and dd > best_d:
                    best, best_d = q, dd
        if not nxt:
            break
        frontier = nxt
        if best_d >= target_dist * 0.92:
            break
    return best


def process(font, gname, px=2000, margin_frac=0.08, verbose=True):
    mask, tr = raster_mask(font, gname, px, margin_frac)
    xmin, ymin, scale, margin, upp, sign = tr
    dist = ndimage.distance_transform_edt(mask)
    sk = skeletonize(mask)
    hooks = raster_hooks(mask, sk, dist)
    if not hooks:
        return None

    glyf = font["glyf"]
    glyph = glyf[gname]
    coords, ends, flags = glyph.getCoordinates(glyf)
    contours = split_contours(coords, ends, flags)

    def area(c):
        return sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1]
                   for i in range(len(c))) / 2

    outer = max(range(len(contours)), key=lambda k: abs(area(contours[k])))

    def to_font_early(y, x):
        return (xmin + (x - margin) * upp, ymin + (px - margin - y) * upp)

    def contour_at(pt):
        """笔尖落在哪条轮廓上就切哪条。`包` 的横折钩在**次大**轮廓里（离最大轮廓
        30 单位以外），只切最大轮廓永远切不到它。"""
        best_k, best_d = None, None
        for k, c in enumerate(contours):
            d = min(_dist((q[0], q[1]), pt) for q in c)
            if best_d is None or d < best_d:
                best_k, best_d = k, d
        return best_k

    contour = list(contours[outer])
    # 局部半笔宽：钩根处的距离变换才反映那一笔的粗细。
    # 用全字中位数会让 `九`/`了` 差 6–20%，切口宽度对不上。
    _r0 = int(hooks[0][1][-1][0]), int(hooks[0][1][-1][1])
    r = float(dist[_r0]) * upp

    def to_font(y, x):
        return (xmin + (x - margin) * upp, ymin + (px - margin - y) * upp)

    report = []
    diag = []
    done_roots = []
    for _cut, removed, _w in hooks:
        # 同一个钩会被两条规则各报一次（`乙` 的钩根同时命中 A 和 B），切完第一刀
        # 轮廓已经变了，第二刀会落在笔身上——`了` 因此整条竖被挖空（IoU 0.19）。
        # 钩根离已切过的钩根不到 2r 就跳过。
        _root = to_font(int(removed[-1][0]), int(removed[-1][1]))
        if any(_dist(_root, q) < 2.0 * r for q in done_roots):
            report.append(("dup",))
            continue
        done_roots.append(_root)
        # `find_hooks` 的两条规则都把钩根放在 `removed[-1]`：
        # 规则 A 是 `reversed(edge[:trimmed])`，末位 = 分叉点；规则 B 是
        # `path[:trimmed]`，trimmed 从**笔尖**数起，末位 = 靠钩根那端。
        ry, rx = int(removed[-1][0]), int(removed[-1][1])
        P = to_font(ry, rx)
        banned = {(int(p[0]), int(p[1])) for p in removed}
        half = r / upp
        # 笔身方向：从钩根出发，在骨架（去掉钩）上往外走约 1.5 倍笔宽，
        # 取"根 → 走到那里"的方向。不能用邻近点平均——那会滑到钩的内侧去。
        target = 0.6 * half
        walked = _walk_out((ry, rx), banned, sk, target)
        if walked is None:
            report.append(("no-body", 0))
            continue
        B = to_font(walked[1], walked[0])
        d = _norm((P[0] - B[0], P[1] - B[1]))
        # 横捺：钩根处笔势已经上扬，就地收圆会读成"竖弯"。沿骨架往回找笔势
        # 变平的那一点重做切口，半圆轴线才是水平的，接缝也相切。
        n = (-d[1], d[0])
        # n 的朝向不固定（d 随钩的形状变号），会让 S/E 的左右关系随机翻转，
        # 进而把保留侧和丢弃侧搞反。统一成"指向钩尖那一侧"。
        # 笔尖端 = `removed` 两端里骨架度数为 1 的那端。规则 A 的 removed[0]
        # 是切除点，不翻过来会让「被删弧必须含笔尖」这条判据永远不成立。
        _e0 = (int(removed[0][0]), int(removed[0][1]))
        _e1 = (int(removed[-1][0]), int(removed[-1][1]))
        _d0 = len(_adjacency(_e0, sk))
        _d1 = len(_adjacency(_e1, sk))
        _tip_px = _e0 if (_d0 == 1 and _d1 != 1) else (_e1 if (_d1 == 1 and _d0 != 1) else _e1)
        tip = to_font(_tip_px[0], _tip_px[1])
        if (tip[0] - P[0]) * n[0] + (tip[1] - P[1]) * n[1] < 0:
            n = (-n[0], -n[1])


        # 笔身方向：从钩根出发，走「离钩尖最远」的那条分支。
        # `_body_path` 本身不认方向——钩根落在骨架交叉点（`乙` 的两处钩根都是
        # 度数 2/3 的交叉点）时，它会顺着钩往里走，窗口里量的全是钩的宽度，
        # 于是一个合格横截面都找不到，钩就切不掉。
        bp, bp_len = [], 0.0
        for _nb in _adjacency((ry, rx), sk):
            if _nb in banned:
                continue
            _seg = _body_path(_nb, banned, sk, 2.2 * r / upp)
            if not _seg:
                continue
            _len = sum(_dist(_seg[k], _seg[k + 1]) for k in range(len(_seg) - 1))
            _far = _dist(to_font(*_seg[-1]), to_font(*removed[0]))
            if _far > bp_len:
                bp, bp_len = [(ry, rx)] + list(_seg), _far
        if not bp:
            bp = _body_path((ry, rx), banned, sk, 2.2 * r / upp)
        hook_pts = [to_font(y, x) for y, x in removed]
        bw = [float(dist[y, x]) * upp for y, x in bp]
        # 先用**笔尖**切：半径取笔尖处的局部半笔宽，被切掉的弧长正好是钩的长度
        # （实测 3.1–3.7r）。从钩根往里切会带走笔身（旧版 9.8r，`乙` 因此看着
        # 还有钩）。笔尖取不到（`乙` 的 removed 两端都是交叉点）时才回退。
        fd = None
        _target = outer
        # 笔尖候选：骨架端点（度数 1）且离钩骨架 6 单位内。
        # 不能只从 `removed` 两端取——`了`/`子` 的真笔尖不在 removed 里（它是
        # 钩骨架往外 1 单位的端点），`乙` 的 removed 两端全是交叉点（度数 2/3）。
        _hookpx = {(int(p[0]), int(p[1])) for _c, _rm, _w in hooks for p in _rm}
        _tips = []
        for _y, _x in zip(*np.nonzero(sk)):
            if len(_adjacency((int(_y), int(_x)), sk)) != 1:
                continue
            _near = min((math.hypot(_y - p[0], _x - p[1]) for p in _hookpx), default=1e9)
            if _near <= 6.0:
                _tips.append(((int(_y), int(_x)), _near))
        _tips.sort(key=lambda t: t[1])
        for _tp, _ in _tips:
            if len(_adjacency(_tp, sk)) != 1:
                continue
            _tr = float(dist[_tp]) * upp
            if _tr < 20:
                continue
            _k = contour_at(to_font(_tp[0], _tp[1]))
            fd = best_cut_at_tip(contours[_k], to_font(_tp[0], _tp[1]), _tr)
            if fd is not None:
                _target = _k
                diag.append(("tip-cut", _k, round(_tr, 1), round(fd[5], 1)))
                break
        if fd is not None:
            contour = list(contours[_target])
            outer = _target
        if fd is None and len(bp) > 8:
            fd = best_cut(contour, [to_font(y, x) for y, x in bp], tip, r, None, bw)
            if fd is not None:
                diag.append(("root-cut", round(fd[6], 1), round(fd[5], 1)))
        if fd is None:
            # 没有合格切口就**原样保留**。以前这里走 hook_run 兜底，兜底量出的
            # 弦可以长达 3 倍笔宽（`子` 242.4 vs 71.9），收笔只能在拐角上糊一个
            # 球。退路本身就会毁字，删掉比修好更实在。
            report.append(("skip",))
            continue
        else:
            P, d, (siS, tS_, pS), (siE, tE_, pE), chord, arc_d, r = fd
            diag.append(("pick", round(arc_d, 1), "chord", round(chord, 1), "r", round(r, 1)))
        # 参数环是「切点 S 处轮廓自身的走向」：轮廓是有向的，S→E 在**轮廓方向**上
        # 恰好是保留侧。`best_cut` 给的 S 是无向的，所以这里按有向面积判一次：
        # 被删的那一段必须是短的那一侧。
        if siS == siE:
            report.append(("same-seg", siS))
            continue
        segs = segments_of(contour)

        def sub(seg, t0, t1):
            """取 seg 在 [t0,t1] 上的子曲线，返回除起点外的点（末位是 on-curve）。"""
            kind, p0, ctrls, p1, _at = seg
            if t1 - t0 < 1e-9:
                return []
            if kind == "line":
                return [(p0[0] + (p1[0] - p0[0]) * t1, p0[1] + (p1[1] - p0[1]) * t1, True)]
            left, _ = _split_quad(p0, ctrls[0], p1, t1)
            if t0 <= 1e-9:
                return [(left[1][0], left[1][1], False), (left[2][0], left[2][1], True)]
            _, right = _split_quad(left[0], left[1], left[2], t0 / t1)
            return [(right[1][0], right[1][1], False), (right[2][0], right[2][1], True)]

        # 收笔 = **直的等宽笔身 + 标准半圆**（就是"一条直"）。
        # 切口两侧的轮廓在弯笔身上是斜的，直接贴一个半圆，圆半径就跟着弦长跑，
        # 必然比笔宽大一圈（`九` 38.2 vs 34.8），放大就是脓包。
        # 所以从切口收窄到笔宽 2r，走一段直侧边，再接半径 = 半笔宽的真半圆。
        C_ = ((pS[0] + pE[0]) / 2, (pS[1] + pE[1]) / 2)
        nrm = (-(pE[1] - pS[1]), pE[0] - pS[0])
        nrm = _norm(nrm)
        # 鼓向：朝**被删掉的那段轮廓弧的重心**。这段就是钩本身，它必然在端头
        # 该鼓的一侧。笔身点 B 和钩尖都会在弯处判反（`必` 鼓进笔身自交成洞、
        # `也` 鼓错边切出缺口），只有被删弧的重心不会错。
        arc_sum = [0.0, 0.0]
        n_arc = 0
        idx2, first2 = siS, True
        while True:
            t0 = tS_ if first2 else 0.0
            t1 = tE_ if idx2 == siE else 1.0
            kind2, q0, ctrls2, q1, _at2 = segs[idx2]
            for kk in range(1, 5):
                tt = t0 + (t1 - t0) * kk / 4
                if kind2 == "quad" and ctrls2:
                    qq = _quad_at(q0, ctrls2[0], q1, tt)
                else:
                    qq = (q0[0] + (q1[0] - q0[0]) * tt, q0[1] + (q1[1] - q0[1]) * tt)
                arc_sum[0] += qq[0]
                arc_sum[1] += qq[1]
                n_arc += 1
            if idx2 == siE:
                break
            idx2 = (idx2 + 1) % len(segs)
            first2 = False
        if n_arc:
            gx, gy = arc_sum[0] / n_arc, arc_sum[1] / n_arc
            if (gx - C_[0]) * nrm[0] + (gy - C_[1]) * nrm[1] < 0:
                nrm = (-nrm[0], -nrm[1])
        def tangent(seg, t):
            kind3, q0, ctrls3, q1, _a3 = seg
            if kind3 == "quad" and ctrls3:
                c3 = ctrls3[0]
                return (2 * (1 - t) * (c3[0] - q0[0]) + 2 * t * (q1[0] - c3[0]),
                        2 * (1 - t) * (c3[1] - q0[1]) + 2 * t * (q1[1] - c3[1]))
            return (q1[0] - q0[0], q1[1] - q0[1])

        # 端头半径**绝不能超过半笔宽**。取弦的一半时，弦比笔宽大多少，端头就比
        # 笔身宽多少——放大就是一个蘑菇头（主人说的脓包）。弦更窄时宁可按弦收，
        # 也不反过来撑宽。
        cap = build_round_cap(pS, pE, nrm)
        diag.append(("capchord", round(_dist(pS, pE), 1), "2r", round(2 * r, 1)))

        # 保留段：从 E 顺着段序走回 S。按段重建，不再往扁平点表里插点
        # （插点会留下孤立控制点，轮廓自交，端头就出缺口）。
        kept = []
        idx, first = siE, True
        while True:
            t0 = tE_ if first else 0.0
            if idx == siS:
                kept += sub(segs[idx], t0, tS_)
                break
            kept += sub(segs[idx], t0, 1.0)
            idx = (idx + 1) % len(segs)
            first = False
        while kept and _dist((kept[-1][0], kept[-1][1]), pS) < 1e-6:
            kept.pop()
        new = _despike([(pS[0], pS[1], True)] + cap + kept)
        # 安全网：切完包围盒任何一边缩进超过 3.4r，说明切掉的是笔身而不是钩。
        # 切点挪到钩之外以后，去钩本身就会让包围盒合法收缩 1.5–2r（`九` 64.6），
        # 阈值仍按 1.5r 会把正常去钩全挡掉。
        # 正常去钩只让包围盒变化 10–31（钩长）；`了` 的假钩一度让 xmin 从 94
        # 跳到 266（+172），整条横撇被吃掉。宁可这次不切，也不能毁字。
        def _bbox(pts):
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            return min(xs), max(xs), min(ys), max(ys)
        _b0, _b1 = _bbox(contour), _bbox(new)
        _grow = max(abs(_b1[k] - _b0[k]) for k in range(4))
        if _grow > 3.4 * r:
            report.append(("revert-bbox", round(_grow, 1)))
            diag.append(("revert", round(_grow, 1), "limit", round(1.5 * r, 1)))
            continue
        diag.append(("cut", round(pS[0]), round(pS[1]), "E", round(pE[0]), round(pE[1]),
                     "chord", round(_dist(pS, pE), 1), "2r", round(2 * r, 1),
                     "kept", len(kept)))
        contour = new
        report.append(("ok", round(r, 1), len(kept)))
        if verbose:
            print("   diag:", diag)
        if verbose:
            print(f"  {gname}: {report[-1]}")
    if not any(x[0] == "ok" for x in report):
        if verbose:
            print("   report:", report, "diag:", diag)
        return None
    contours[outer] = contour
    flat, new_ends = [], []
    for c in contours:
        flat.extend(c)
        new_ends.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x, y, on in flat])
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf)
    # 侧边距必须跟着 xMin 走：原字 lsb == xMin，切掉钩后 xMin 会变，
    # 不同步的话 FreeType 会按旧 lsb 定位，整个字在格子里偏移（`了` 曾偏 172 单位）。
    if "hmtx" in font and gname in font["hmtx"].metrics:
        adv, lsb = font["hmtx"][gname]
        font["hmtx"][gname] = (adv, glyph.xMin)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    parser.add_argument("--chars", required=True)
    parser.add_argument("--px", type=int, default=2000)
    args = parser.parse_args()
    font = TTFont(args.infont)
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    ok = []
    for ch in dict.fromkeys(args.chars):
        if ord(ch) not in cmap:
            continue
        gname = cmap[ord(ch)]
        if glyf[gname].isComposite():
            continue
        res = process(font, gname, args.px)
        print(f"{ch}: {res}")
        if res:
            ok.append(gname)
    for gname in ok:
        advance = font["hmtx"][gname][0]
        font["hmtx"][gname] = (advance, glyf[gname].xMin)
    font.save(args.outfont)
    print(f"处理 {len(ok)} 字 -> {args.outfont}")


if __name__ == "__main__":
    main()


