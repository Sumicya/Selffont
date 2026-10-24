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
from hook_erase import find_hooks as raster_hooks  # noqa: E402
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

    # 候选切面：① 沿笔身在钩根附近（粗定位）；② 沿**钩骨架**靠近钩根处，
    # 切平面垂直于钩的走向（正定位）。只靠 ① 时，切面是垂直于笔身而不是垂直于
    # 钩，钩是斜着长出来的，弦就斜，半圆的轴跟着歪（`必` 的弦一度歪到 2.1 长）。
    sites = []
    for i in range(2, n_ - 1, 3):
        # 只能贴着钩根找：跑远了就是切笔身，`也` 因此在弧长 31 处切出 65% 笔宽的弦。
        if not (0.0 <= arc[i] <= 1.05 * r):
            continue
        # 切向必须按**弧长窗口**取中心差分，不能用相邻两点：
        # 骨架是 8 连通像素步进，相邻点差只有 (1,0)/(1,1)/(0,1) 几种，
        # 单步差分会把笔势量化成 45° 的倍数——切平面方向只有 8 种，
        # 斜切弯笔时弦宽就忽大忽小（`九` 76.4 vs 笔宽 69.6），端头永远对不齐。
        win = max(3, int(round(0.35 * r / step_px)))
        ia_, ib_ = max(0, i - win), min(n_ - 1, i + win)
        d = _norm((path[ia_][0] - path[ib_][0], path[ia_][1] - path[ib_][1]))
        sites.append((path[i], d, widths[i] if widths else r, arc[i]))
    if hook_pts and len(hook_pts) >= 8:
        m = len(hook_pts)
        for k in range(1, min(10, m - 3)):
            a2 = hook_pts[m - 1 - min(k + 4, m - 1)]
            b2 = hook_pts[m - 1 - max(0, k - 4)]
            if _dist(a2, b2) < 1e-9:
                continue
            d2 = _norm((a2[0] - b2[0], a2[1] - b2[1]))
            sites.append((hook_pts[m - 1 - k], d2, r, 0.0))

    best = None
    for P, d, rl, arc_d in sites:
        nv = (-d[1], d[0])
        hits = cut_points(contour, P, nv)
        if len(hits) < 2:
            continue
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
                if not (0.92 * 2 * rl <= chord <= 1.10 * 2 * rl):
                    if _DEBUG:
                        print("   reject chord", round(chord, 1), "2rl", round(2 * rl, 1),
                              "arc", round(arc_d, 1), "seg", round(ln * step, 1))
                    continue
                # 删掉的那段弧必须**贴着钩骨架**：钩的骨架点集是已知的，
                # 真正该删的那一小块轮廓离它不超过一个笔宽。只看弦长和弧长
                # 会配到笔身上的另一瓣（`子` 把整条竖钩当短边删掉，只剩横撇）。
                if hook_pts:
                    # 采样必须从**被删那段的起点**出发。配对交换过以后起点是 i2，
                    # 还从 i1 走就会绕到另外半圈上，量出来的距离是整字的对角
                    # （`了` 因此被判 10r 开外、真钩被跳过）。
                    iS_ = sidx(hS[3])
                    ds = [min(_dist(smp[(iS_ + ln * k // 6) % nsm][2], h) for h in hook_pts)
                          for k in range(1, 6)]
                    if max(ds) > 1.5 * r or sum(ds) / len(ds) > 1.2 * r:
                        if _DEBUG:
                            print("   reject far", round(max(ds), 1), "mean", round(sum(ds) / 5, 1),
                                  "arc", round(arc_d, 1), "chord", round(chord, 1),
                                  "seg", round(ln * step, 1))
                        continue
                seg_len = ln * step
                score = abs(chord - 2 * rl) / (2 * rl) + 0.45 * seg_len / (2 * rl)
                if best is None or score < best[0]:
                    best = (score, P, d, (hS[1], hS[2], hS[3]), (hE[1], hE[2], hE[3]),
                            chord, arc_d, rl)
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
            # 没有合格切口就**原样保留**。以前这里走 hook_run 兜底，兜底量出的
            # 弦可以长达 3 倍笔宽（`子` 242.4 vs 71.9），收笔只能在拐角上糊一个
            # 球。退路本身就会毁字，删掉比修好更实在。
            report.append(("skip",))
            continue
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


