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
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from scipy import ndimage
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_cut import split_contours  # noqa: E402
from hook_erase import find_hooks as raster_hooks  # noqa: E402
from stroke_width_normalize_prototype import raster_mask  # noqa: E402

SAMPLE = 32
TAPER = 2.1        # 收尖长度 / 半笔宽
SIDE_K = 0.46      # 侧边起手控制点系数（× 弦长）
AXIS_M = 0.34      # 收尖前轴向下压系数（× 弦长）
TIP_E = 0.20       # 尖端横向错开（× 半笔宽），保证是个楔形而不是对折
BEND_TARGET = None  # 弯折压平（实验开关）。捺的收笔就是等宽 + 半圆，不弯。
FLAT_MAX = 20.0    # 切口处允许的"水平"偏差（度）
FLAT_BACK = 2.6    # 沿骨架往回最多找多远（× 半笔宽）
FLAT_MIN = 0.30    # 最近也至少离开钩根这么远（× 半笔宽）
FLAT_TURN = 25.0   # 与钩根笔势至少差这么多度，才认为钩后确实转了弯（度）


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
            # 连续 off-curve：按 TT 隐含中点拆段，每段插入点 = 下一个 off 点的索引
            pts = [(p0, None)] + offs + [(p1, j)]
            for t in range(len(pts) - 2):
                a, ai = pts[t]
                c, ci = pts[t + 1]
                b, bi = pts[t + 2]
                if t + 2 < len(pts) - 1:
                    mid = ((c[0] + b[0]) / 2, (c[1] + b[1]) / 2)
                    segs.append(("quad", a, [c], mid, bi))
                else:
                    segs.append(("quad", a, [c], b, bi))
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


def bend_tail(pts, path, delta, L, r):
    """沿骨架中心线把笔尾**弯**过去：收笔方向从原笔势转到 delta 后的方向。

    为什么用弯而不是切：切在弯曲笔段上时，弦宽 ≠ 笔宽（`九` 是 107%），
    半圆就会鼓出来。沿中心线扭转是刚体旋转的逐点版本——
    每个轮廓点绕**自己最近的**中心线点转 θ(s)，横向偏移被等距旋转，
    所以笔宽严格不变、端头仍是正圆、中心线本身也保持光滑，接缝不出角。

    权重 = 沿轴向的 smoothstep(1 - s/L) × 横向衰减（1.6r 内全额、2.6r 外为零）。
    横向那项不能省：否则别的笔画只要"最近中心线点在根部"就会被整段甩走。
    """
    if len(path) < 4 or abs(delta) < 1e-3:
        return pts
    s_nodes = [0.0]
    for i in range(len(path) - 1):
        s_nodes.append(s_nodes[-1] + _dist(path[i], path[i + 1]))

    def theta(s_):
        if s_ >= L:
            return 0.0
        u = 1.0 - s_ / L
        return delta * (u * u * (3 - 2 * u))

    def radial(rho):
        if rho <= 1.6 * r:
            return 1.0
        if rho >= 2.6 * r:
            return 0.0
        u = (rho - 1.6 * r) / (1.0 * r)
        return 1 - u * u * (3 - 2 * u)

    # 新中心线：沿原切向逐段旋转累加
    new_cl = [path[0]]
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        ds = _dist(a, b)
        if ds < 1e-9:
            new_cl.append(new_cl[-1])
            continue
        th = theta(s_nodes[i] + ds / 2)
        e = _norm((b[0] - a[0], b[1] - a[1]))
        c, s_ = math.cos(th), math.sin(th)
        e2 = (e[0] * c - e[1] * s_, e[0] * s_ + e[1] * c)
        new_cl.append((new_cl[-1][0] + e2[0] * ds, new_cl[-1][1] + e2[1] * ds))

    out = []
    for x, y, on in pts:
        s_, rho, q, _e = _nearest_on_path(path, (x, y))
        w = radial(rho)
        th = theta(s_) * w
        if th == 0.0:
            out.append((x, y, on))
            continue
        j = 0
        while j + 2 < len(s_nodes) and s_nodes[j + 1] < s_:
            j += 1
        span = max(1e-9, s_nodes[j + 1] - s_nodes[j])
        u = max(0.0, min(1.0, (s_ - s_nodes[j]) / span))
        cq = (new_cl[j][0] + (new_cl[j + 1][0] - new_cl[j][0]) * u,
              new_cl[j][1] + (new_cl[j + 1][1] - new_cl[j][1]) * u)
        vx, vy = x - q[0], y - q[1]
        c, sn = math.cos(th), math.sin(th)
        out.append((cq[0] + vx * c - vy * sn, cq[1] + vx * sn + vy * c, on))
    return out



def best_cut(contour, path, tip, r, hook_pts=None, widths=None):
    """沿骨架找切口：在所有交点里取**短边**为钩，且弦长最接近局部笔宽。

    两个关键点（前几版都栽在这）：
      · 不能按"钩尖的参数夹在两个交点之间"来配对——参数是环形的，夹出来的
        往往是绕整条轮廓的那一边（`了` 因此被切掉整条竖）。
        正解：交点两两配对，取两侧中的**短边**，钩本来就是最小的一块轮廓。
      · 半笔宽要用**切点处**的局部值：钩根被钩的弯撑大（`了` 36.5 vs 实际 30），
        拿它当基准，弦永远"偏窄"，候选全被拒。
    """
    n_ = len(path)
    if n_ < 8:
        return None
    arc = [0.0]
    for i in range(n_ - 1):
        arc.append(arc[-1] + _dist(path[i], path[i + 1]))
    step_px = arc[-1] / max(1, n_ - 1)
    smp = _samples(contour)
    nsm = len(smp)
    per = 0.0
    for i in range(nsm):
        per += _dist(smp[i][2], smp[(i + 1) % nsm][2])
    step = per / nsm
    hook_pts = hook_pts or []

    def sidx(pt):
        return min(range(nsm), key=lambda i: _dist(smp[i][2], pt))

    best = None
    for i in range(2, n_ - 1, 3):
        if not (0.15 * r <= arc[i] <= 1.9 * r):
            continue
        # 切向必须按**弧长窗口**取中心差分，不能用相邻两点：
        # 骨架是 8 连通像素步进，相邻点差只有 (1,0)/(1,1)/(0,1) 几种，
        # 单步差分会把笔势量化成 45° 的倍数——切平面方向只有 8 种，
        # 斜切弯笔时弦宽就忽大忽小（`九` 76.4 vs 笔宽 69.6），端头永远对不齐。
        win = max(3, int(round(0.35 * r / step_px)))
        ia_, ib_ = max(0, i - win), min(n_ - 1, i + win)
        d = _norm((path[ia_][0] - path[ib_][0], path[ia_][1] - path[ib_][1]))
        P = path[i]
        nv = (-d[1], d[0])
        hits = cut_points(contour, P, nv)
        if len(hits) < 2:
            continue
        rl = widths[i] if widths else r
        for a in range(len(hits)):
            for b in range(a + 1, len(hits)):
                h1, h2 = hits[a], hits[b]
                i1, i2 = sidx(h1[3]), sidx(h2[3])
                fwd = (i2 - i1) % nsm
                if fwd <= nsm - fwd:
                    hS, hE, ln = h1, h2, fwd
                else:
                    hS, hE, ln = h2, h1, nsm - fwd
                chord = _dist(hS[3], hE[3])
                if not (0.62 * 2 * rl <= chord <= 1.55 * 2 * rl):
                    continue
                seg_len = ln * step
                if hook_pts:
                    # 被移除的那段得挨着钩的根线。上限放到 6r：钩的根线本来就只覆盖
                    # 钩尖那一小截，而轮廓上属于这块"端头"的部分会比根线长得多。
                    pts_arc = [smp[(i1 + k) % nsm][2] for k in range(ln + 1)] \
                        if hS is h1 else [smp[(i2 + k) % nsm][2] for k in range(ln + 1)]
                    far = max(min(_dist(q, h) for h in hook_pts) for q in pts_arc)
                    if far > 12.0 * r:
                        continue
                score = abs(chord - 2 * rl) / (2 * rl) + 0.45 * seg_len / (2 * rl)
                if best is None or score < best[0]:
                    best = (score, P, d, (hS[1], hS[2], hS[3]), (hE[1], hE[2], hE[3]),
                            chord, arc[i], rl)
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


def hook_run(contour, P, d, tip, reach):
    """返回被移除那一段的两个端点 (segS,tS,ptS),(segE,tE,ptE)；失败返回 None。

    做法：稠密采样 → 从离钩尖最近的采样点起，向两侧扩展
    「在切平面之外（s>0）且离切点不远（<reach）」的连续采样段。
    这样两端的边界就是唯一的一对，不必再猜"哪两个交点配对"。
    """
    smp = _samples(contour)
    n = len(smp)
    def s_of(pt):
        return (pt[0] - P[0]) * d[0] + (pt[1] - P[1]) * d[1]
    def near(pt):
        return _dist(pt, P) < reach
    inside = [s_of(p) > 0 and near(p) for _, _, p in smp]
    i0 = min(range(n), key=lambda i: _dist(smp[i][2], tip))
    if not inside[i0]:
        return None
    iF = i0
    while inside[(iF + 1) % n] and (iF + 1) % n != i0:
        iF = (iF + 1) % n
    iB = i0
    while inside[(iB - 1) % n] and (iB - 1) % n != i0:
        iB = (iB - 1) % n
    a0 = smp[(iB + 1) % n]          # 段起点在外，段终点在内 → 前向交点
    a1 = smp[iB % n]
    b0 = smp[(iF - 1) % n]
    b1 = smp[iF % n]
    if a0[0] != a1[0] or b0[0] != b1[0]:
        return None                  # 恰好跨段边界，放弃（极少）
    tS, pS = _bisect_zero(contour, a0[0], a0[1], a1[1], P, d)
    tE, pE = _bisect_zero(contour, b0[0], b0[1], b1[1], P, d)
    return (a0[0], tS, pS), (b1[0], tE, pE)




def build_ellipse_cap(S, E, C, d, b, quads=4):
    """半椭圆收笔：弦向半轴 = |S-E|/2，笔势向半轴 = b（取半笔宽）。

    为什么不能是半圆：切口的弦长由笔段弯曲程度决定（`九` 75.2），比真笔宽
    （69.6）宽；按弦长做半圆，端头两侧各多出 2.8 单位，交界处就是一道台阶
    （放大看是端头"顶个球"）。半椭圆把弦向半轴留在弦上、笔势向半轴压回半笔宽，
    端点仍精确落在轮廓上（无台阶），顶点高度也正好是笔宽的一半（不鼓）。
    """
    a = _dist(S, E) / 2
    n = _norm((S[0] - C[0], S[1] - C[1]))
    out = []
    for q in range(quads):
        t0 = math.pi * q / quads
        t1 = math.pi * (q + 1) / quads
        tm = (t0 + t1) / 2
        coef = math.cos((t1 - t0) / 2)
        out.append((C[0] + a / coef * math.cos(tm) * n[0] + b / coef * math.sin(tm) * d[0],
                    C[1] + a / coef * math.cos(tm) * n[1] + b / coef * math.sin(tm) * d[1],
                    False))
        if q < quads - 1:
            out.append((C[0] + a * math.cos(t1) * n[0] + b * math.sin(t1) * d[0],
                        C[1] + a * math.cos(t1) * n[1] + b * math.sin(t1) * d[1], True))
    out.append((E[0], E[1], True))
    return out




def build_flare_cap(S, E, tS, tE, C, d, r, quads=4):
    """捺端：半径 = 真半笔宽的半圆 + 两端各一段 G1 小喇叭。

    切口的弦由笔段弯曲程度决定，会比真笔宽宽一点（`九` 76.9 vs 69.6）。
    按弦长做半圆 → 端头比笔身胖一圈、交界留台阶；按真笔宽做 → 两端缩进 3.6 单位，
    直接接又是台阶。所以两端各插一段小喇叭：起点沿轮廓切向、终点沿圆的切向，
    全程 G1 连续——笔身顺势张开一点再收成半圆，正是捺的收笔。
    """
    u = _norm((E[0] - C[0], E[1] - C[1]))
    S2 = (C[0] - u[0] * r, C[1] - u[1] * r)
    E2 = (C[0] + u[0] * r, C[1] + u[1] * r)
    out = []
    k1 = max(1.9, 0.8 * _dist(S, S2))
    out.append((S[0] + tS[0] * k1, S[1] + tS[1] * k1, False))
    out.append((S2[0] - d[0] * k1, S2[1] - d[1] * k1, False))
    out.append((S2[0], S2[1], True))
    a0 = math.atan2(S2[1] - C[1], S2[0] - C[0])
    a1 = math.atan2(E2[1] - C[1], E2[0] - C[0])
    aD = math.atan2(d[1], d[0])
    sweep = (a1 - a0) % (2 * math.pi)
    through = (aD - a0) % (2 * math.pi)
    if through > sweep:                      # 正向不过 d，说明该走反向
        sweep -= 2 * math.pi
    step = sweep / quads
    coef = math.cos(abs(step) / 2)
    for q in range(quads):
        t0 = a0 + step * q
        t1 = t0 + step
        tm = (t0 + t1) / 2
        out.append((C[0] + r / coef * math.cos(tm), C[1] + r / coef * math.sin(tm), False))
        if q < quads - 1:
            out.append((C[0] + r * math.cos(t1), C[1] + r * math.sin(t1), True))
    out.append((E2[0], E2[1], True))
    k2 = max(1.9, 0.8 * _dist(E, E2))
    out.append((E2[0] + d[0] * k2, E2[1] + d[1] * k2, False))
    out.append((E[0] - tE[0] * k2, E[1] - tE[1] * k2, False))
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


def build_blunt(S, E, tS, tE, d, r, k=0.30):
    """平宽收笔（捺）：两段三次贝塞尔，两端与轮廓**切向一致**，顶点切线垂直于 d。

    为什么不用半圆：切口是直线，而笔身是弯的，弦宽 ≠ 笔宽（`九` 107%），
    按弦长做半圆，端头就比笔身粗；而且圆弧在 S 处的切向与轮廓切向不平行，
    于是留下一道角（缺口）。用两段三次贝塞尔，两端都从轮廓切向出发，
    顶点处切线水平，G1 连续——既没有鼓包也没有缺口，端头读起来就是"捺"。
    """
    C = ((S[0] + E[0]) / 2, (S[1] + E[1]) / 2)
    w = _dist(S, E)
    h = w / 2                                   # 顶点高度 = 弦长一半（与切口同宽）
    M = (C[0] + d[0] * h, C[1] + d[1] * h)
    v = (-d[1], d[0])
    out = []
    # 左段：S → M
    l1 = min(_dist(S, M) * k, 0.5 * w * k)
    out.append((S[0] + tS[0] * l1, S[1] + tS[1] * l1, False))
    l2 = h * 0.55
    out.append((M[0] - v[0] * l2, M[1] - v[1] * l2, False))
    out.append((M[0], M[1], True))
    # 右段：M → E
    out.append((M[0] + v[0] * l2, M[1] + v[1] * l2, False))
    l3 = min(_dist(M, E) * k, 0.5 * w * k)
    out.append((E[0] - tE[0] * l3, E[1] - tE[1] * l3, False))
    out.append((E[0], E[1], True))
    return out


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


def build_cap(S, E, P, d, r, quads=4, body=None):
    """真半圆端头：S、E 为直径两端，向背离笔身的一侧扫 180°。

    不再用角度增量推导（那段逻辑反复出错，切出来的弧会绕到笔身另一侧）。
    直接构造正交基：
      u = 从圆心指向 S 的单位向量
      k = u × (S→E 方向的旋转) …… 用"笔身在哪侧"确定 k 的符号
    半圆参数化为 C + rad*(u*cosθ + k*sinθ)，θ∈[0,π]，显式从 S 扫到 E。
    """
    C = ((S[0] + E[0]) / 2, (S[1] + E[1]) / 2)
    rad = _dist(S, E) / 2
    u = _norm((S[0] - C[0], S[1] - C[1]))
    k = (-u[1], u[0])
    # 让 k 指向背离笔身的一侧
    ref = body if body is not None else (P[0] + d[0] * rad, P[1] + d[1] * rad)
    if (ref[0] - C[0]) * k[0] + (ref[1] - C[1]) * k[1] > 0:
        k = (-k[0], -k[1])
    out = []
    coef = math.cos(math.pi / (2 * quads))
    for q in range(quads):
        t0 = math.pi * q / quads
        t1 = math.pi * (q + 1) / quads
        tm = (t0 + t1) / 2
        ctrl = (C[0] + rad / coef * (u[0] * math.cos(tm) + k[0] * math.sin(tm)),
                C[1] + rad / coef * (u[1] * math.cos(tm) + k[1] * math.sin(tm)))
        out.append((ctrl[0], ctrl[1], False))
        if q < quads - 1:
            out.append((C[0] + rad * (u[0] * math.cos(t1) + k[0] * math.sin(t1)),
                        C[1] + rad * (u[1] * math.cos(t1) + k[1] * math.sin(t1)), True))
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
    contour = list(contours[outer])
    # 局部半笔宽：钩根处的距离变换才反映那一笔的粗细。
    # 用全字中位数会让 `九`/`了` 差 6–20%，切口宽度对不上。
    _r0 = int(hooks[0][1][-1][0]), int(hooks[0][1][-1][1])
    r = float(dist[_r0]) * upp

    def to_font(y, x):
        return (xmin + (x - margin) * upp, ymin + (px - margin - y) * upp)

    report = []
    diag = []
    for _cut, removed, _w in hooks:
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
        tip = to_font(int(removed[0][0]), int(removed[0][1]))
        if (tip[0] - P[0]) * n[0] + (tip[1] - P[1]) * n[1] < 0:
            n = (-n[0], -n[1])


        bp = _body_path((ry, rx), banned, sk, 2.2 * r / upp)
        hook_pts = [to_font(y, x) for y, x in removed]
        bw = [float(dist[y, x]) * upp for y, x in bp]
        fd = (best_cut(contour, [to_font(y, x) for y, x in bp], tip, r, hook_pts, bw)
              if len(bp) > 8 else None)
        if fd is None:
            run = hook_run(contour, P, d, tip, reach=6.0 * r)
            if run is None:
                report.append(("no-run",))
                continue
            (siS, tS_, pS), (siE, tE_, pE) = run
        else:
            P, d, (siS, tS_, pS), (siE, tE_, pE), chord, arc_d, r = fd
            diag.append(("pick", round(arc_d, 1), "chord", round(chord, 1), "r", round(r, 1)))
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

        # 收笔：捺端（半圆半径 = 真半笔宽 + 两端 G1 小喇叭）。
        # 切口的弦由笔段弯曲程度决定，比真笔宽宽一点（`九` 76.9 vs 69.6）：
        # 按弦长做半圆端头就胖一圈；按真笔宽做，两端差 3.6 单位直接接会成台阶。
        # 所以两端各插一段小喇叭——起点沿轮廓切向、终点沿圆的切向，全程 G1。
        # best_cut 已经保证弦长 ≈ 2×局部半笔宽，所以这里就是标准半圆：
        # 半径 = 半笔宽、两端与笔身切向一致，既不会胖，也不会留台阶。
        # 端头用半椭圆（见 build_ellipse_cap）：弦向半轴 = 半弦长、笔势向 = 半笔宽。
        # 端头朝**背离笔身**（B 在笔身上）的一侧鼓。
        C_ = ((pS[0] + pE[0]) / 2, (pS[1] + pE[1]) / 2)
        nrm = (-(pE[1] - pS[1]), pE[0] - pS[0])
        nrm = _norm(nrm)
        if (C_[0] - B[0]) * nrm[0] + (C_[1] - B[1]) * nrm[1] < 0:
            nrm = (-nrm[0], -nrm[1])
        # 端头要顺着笔势**延伸**出去，不能平贴在切口上：不延伸就是被截断的笔。
        # 延伸长度按被去掉的钩在笔势方向上的投影给，至少 0.5r。
        ext = 0.0
        if hook_pts:
            ext = sum((q[0] - C_[0]) * nrm[0] + (q[1] - C_[1]) * nrm[1] for q in hook_pts) / len(hook_pts)
            ext = max(0.5 * r, min(1.6 * r, ext - 0.6 * r))
        cap = build_ellipse_cap(pS, pE, C_, nrm, r + ext)

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
        new = [(pS[0], pS[1], True)] + cap + kept
        diag.append(("cut", round(pS[0]), round(pS[1]), "E", round(pE[0]), round(pE[1]),
                     "chord", round(_dist(pS, pE), 1), "2r", round(2 * r, 1),
                     "kept", len(kept)))
        if BEND_TARGET is not None:
            # 弯的是**整条轮廓**（含刚落好的半圆端头）：端头必须跟着笔身一起转，
            # 只转 cap 会让它绕钩根甩出去，变成"棍子上顶个球"。
            bp = _body_path((ry, rx), banned, sk, 4.0 * r / upp)
            if len(bp) > 5:
                path_f = [to_font(y, x) for y, x in bp]
                delta = math.radians(BEND_TARGET - math.degrees(math.atan2(d[1], d[0])))
                new = bend_tail(new, path_f, delta, 3.2 * r, r)
                diag.append(("bend", round(math.degrees(delta), 1)))
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


def build_ellipse_cap(S, E, C, nrm, b, quads=4):
    """半椭圆收笔：弦向半轴 = 半弦长，笔势向半轴 = b（半笔宽）。

    为什么不能用半圆：切口的弦长由笔段弯曲决定，通常比真笔宽宽一点
    （`九` 73–86 vs 69.6）。按弦做半圆 → 半径 38 > 34.8，端头比笔身胖一圈，
    放大就是个鼓包。半椭圆把弦向半轴留在弦上（端点精确落在轮廓上，无台阶），
    笔势向压回半笔宽（端头厚度与笔身一致），且两端切向恰为 ±法线，天然 G1。
    """
    a = _dist(S, E) / 2
    u = _norm((S[0] - C[0], S[1] - C[1]))
    out = []
    for q in range(quads):
        t0 = math.pi * q / quads
        t1 = math.pi * (q + 1) / quads
        tm = (t0 + t1) / 2
        coef = math.cos((t1 - t0) / 2)
        out.append((C[0] + a / coef * math.cos(tm) * u[0] + b / coef * math.sin(tm) * nrm[0],
                    C[1] + a / coef * math.cos(tm) * u[1] + b / coef * math.sin(tm) * nrm[1],
                    False))
        if q < quads - 1:
            out.append((C[0] + a * math.cos(t1) * u[0] + b * math.sin(t1) * nrm[0],
                        C[1] + a * math.cos(t1) * u[1] + b * math.sin(t1) * nrm[1], True))
    out.append((E[0], E[1], True))
    return out
