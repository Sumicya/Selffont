"""把描边得到的折线环拟合回真曲线（三次贝塞尔链 → 二次曲线链）。

为什么必须有这一步：`design_cjk.stroke_contours` 算出来的是**点**，`cjk_vf` 以前
`pen.lineTo` 把它们直连，于是每个字形都是一圈折线。折线在 1000 px 下看不出，放大到
6000 px/em（看端头圆不圆时用的倍率）就是一圈棱——设计原则 2026-10-24 已经写过
「全是直线的输出无论 IoU 多高都是多边形字体」，本轮主人看到的「凹凸」就是它。

做法（Schneider 1990 那套，改成三档共享分割）：

1. 三档的密点列是同索引一一对应的（`outline_points` 保证）。
2. 先在 400 档上跑 Douglas–Peucker，三档取并集 → **锚点**。锚点是「曲线段的分界」，
   也是真拐角所在，所以三档必然一致。
3. 相邻锚点之间拟合一条三次贝塞尔：端点固定，端点切向由密点邻域定，控制柄长度用
   最小二乘解 2×2 正规方程。**三档各解一次**（各档自己的形状），误差取三档最大。
4. 误差超容差就在「误差最大的那一档的最大误差点」处切开，三档同时切（索引相同），
   所以段数、点数、on/off 标志三档完全一致——gvar 要的就是这个。
5. 每段三次贝塞尔再拆成 n 条二次曲线。n 由三档分别试算后取最大，三档共用 n，
   于是二次曲线的点序也一致。拆法：把三次按参数等分成 n 段，每段取
   `q = (3(c1+c2) - c0 - c3) / 4`（在段中点与原三次曲线严格重合，端点重合）。

输出的 on/off 标志序列三档相同；坐标各档不同。
"""

from __future__ import annotations

import math

FIT_TOL = 0.80        # 三次贝塞尔拟合容差（字体单位）。0.4 会把每个 90° 圆角切成两段
                      # （R≈200 的弧单段三次误差 1.0），段数翻倍；0.8 与母版自身的
                      # 曲线误差（圆角两段二次、2.1 单位）同量级
QUAD_TOL = 1.5        # 三次 → 二次的弦高容差（字体单位）：母版 90° 圆角就是两段二次（误差 2.1 单位），
                      # 段越碎接点越多，接点上曲率不连续，放大看就是一圈棱
LINE_TOL = 0.80       # 段内点到弦线的最大距离不超过它 → 当直线，一个点都不多给。
                      # 0.3 会把剖面上 0.2 单位的正常起伏判成弯，直边被拆成两三条曲线
MAX_QUAD = 5          # 单段三次最多拆成几条二次
MAX_DEPTH = 12        # 递归切分深度上限


# ---------------------------------------------------------------- 小几何

def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 1e-12 else (1.0, 0.0)


def _bez(p0, p1, p2, p3, t):
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
            a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def _tangent_at(pts, i, step, toward):
    """i 处的切向：用邻域三点定圆，圆的切线对粗采样也准。

    为什么不用弦方向：弦 u(p0,pk) 与真实切向差半个步角。圆角处的采样步长是 3–15°，
    半个步角就是 1.5–7.5°——起点方向一错，最小二乘解出来的控制柄整段偏，一个本来
    0.05 单位就能拟合的 90° 弧会被量出几单位误差，然后切成一串小段。fix7 点数暴涨、
    边上看得出棱，主因就是这里。
    """
    n = len(pts)
    idx = [(i + step * k) % n for k in (0, 1, 2)]
    (ax, ay), (bx, by), (cx, cy) = (pts[j] for j in idx)
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) > 1e-7:
        ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
              + (cx * cx + cy * cy) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
              + (cx * cx + cy * cy) * (bx - ax)) / d
        tx, ty = -(ay - uy), (ax - ux)          # 半径转 90°
    else:
        tx, ty = bx - ax, by - ay               # 三点共线：退回弦方向
    if tx * toward[0] + ty * toward[1] < 0:     # 朝向行进方向
        tx, ty = -tx, -ty
    nn = math.hypot(tx, ty)
    if nn < 1e-12:
        return _unit(pts[i], pts[idx[1]])
    return (tx / nn, ty / nn)


def _local_dir(points, i, forward=True):
    """i 处的切向：往前（或往后）取 3 个点做差分，抗单点抖动。"""
    n = len(points)
    k = min(3, n - 1)
    if k <= 0:
        return (1.0, 0.0)
    j = (i + k) % n if forward else (i - k) % n
    return _unit(points[i], points[j])


# ---------------------------------------------------------------- 单段拟合

def _fit_one(pts, u):
    """一段点列（首末是锚点）拟合成三次贝塞尔；返回 (c1, c2, max_err, at)。

    向量化：一段动辄两三百个点，逐点 Python 循环会把全库构建拖到一个小时以上。
    """
    import numpy as np

    P = np.asarray(pts, float)
    T = np.asarray(u, float)
    p0, p3 = P[0], P[-1]
    if len(pts) >= 6:
        # 端点切向：正向取前三点、反向取末三点各做一次三点圆（端点附近曲率最可靠）
        t0 = _tangent_at(pts, 0, +1, (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
        t3 = _tangent_at(pts, len(pts) - 1, -1,
                         (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]))
    else:
        t0 = _unit(pts[0], pts[-1])
        t3 = t0
    t0 = np.asarray(t0, float)
    t3 = np.asarray(t3, float)
    U = 1.0 - T
    W1 = 3.0 * U * U * T
    W2 = 3.0 * U * T * T
    R = P - np.outer((1 - T) ** 3 + W1, p0) - np.outer(3 * U * T * T + T ** 3, p3)
    a11 = float(W1 @ W1)
    a22 = float(W2 @ W2)
    a12 = -float(W1 @ W2) * float(t0 @ t3)
    b1 = float(W1 @ (R @ t0))
    b2 = -float(W2 @ (R @ t3))
    det = a11 * a22 - a12 * a12
    alpha = None
    if abs(det) > 1e-9:
        a1 = (b1 * a22 - b2 * a12) / det
        a2 = (a11 * b2 - a12 * b1) / det
        if a1 > 1e-6 and a2 > 1e-6:
            alpha = (a1, a2)
    if alpha is None:                       # 退化：用三分之一点（Schneider 的兜底）
        d = _dist(p0, p3) / 3.0
        alpha = (d, d)
    c1 = p0 + t0 * alpha[0]
    c2 = p3 - t3 * alpha[1]
    B = np.outer(U ** 3, p0) + np.outer(W1, c1) + np.outer(W2, c2) + np.outer(T ** 3, p3)
    e = np.hypot(*(P - B).T)
    at = int(e.argmax())
    return (float(c1[0]), float(c1[1])), (float(c2[0]), float(c2[1])), float(e[at]), at


def _params(pts):
    """按弦长把点列参数化到 [0,1]。"""
    import numpy as np
    P = np.asarray(pts, float)
    d = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
    total = float(d[-1]) or 1.0
    return d / total


# ---------------------------------------------------------------- 环分割

def _max_off_line(pts):
    """点列到首末连线的最大距离。"""
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return max(_dist(p, a) for p in pts)
    return max(abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / L for p in pts)


def _sub(points, a, b):
    """闭合环上 a..b（含两端，b 可回绕）的点列。"""
    n = len(points)
    out = [points[a % n]]
    i = a
    while True:
        i += 1
        out.append(points[i % n])
        if i % n == b % n:
            break
    return out


def _segment(points_by_weight, a, b, depth, ref=None):
    """a、b 是锚点索引；返回该段的切分列表 [(a,b), ...]（递归）。

    **切分只在参考档（400）上判**：三档形状差一个笔宽，误差量级相同，逐档算三遍
    等于把构建时间乘三。三档最终仍在同一套段上各自最小二乘，点数与 on/off 不变。
    """
    out = []
    ref = ref if ref is not None else next(iter(points_by_weight.values()))
    pts = _sub(ref, a, b)
    worst_err, worst_at, worst_w = -1.0, 1, None
    if len(pts) >= 2:
        _c1, _c2, worst_err, worst_at = _fit_one(pts, _params(pts))
        worst_w = next(iter(points_by_weight))
    span = (b - a) % len(next(iter(points_by_weight.values())))
    # 直线：参考档（400）离弦不超过 LINE_TOL，就一个点都不多给
    if _max_off_line(pts) <= LINE_TOL:
        return [(a, b, "line")]
    if worst_err <= FIT_TOL:
        return [(a, b, "curve")]
    if span <= 2 or depth >= MAX_DEPTH:
        # 切到只剩三点还拟合不准：这里是真拐角（圆角与直边的切点就是这种）。三段点原样
        # 留下，宁可贵两个点，也不许把角削圆——削掉的正是母版最锋利的地方。
        return [(a, b, "poly")]
    n = len(next(iter(points_by_weight.values())))
    mid = (a + worst_at) % n
    if mid == a % n or mid == b % n:
        # 最大误差落在端点：端点误差是被固定住的，切在那里等于不切。退到段中点。
        mid = (a + max(1, span // 2)) % n
        if mid == a % n or mid == b % n:
            return [(a, b, "curve")]
    # ref 必须一路传下去：切分判据只能看参考档（400）。丢了这个参数，递归里的子段会
    # 退回 points_by_weight 的第一档（300），拿 300 档的几何去判「是不是直线」，
    # 400 档上弯 4 单位的弧会被当成直线放过去——实测最大偏差 4.1 单位，肉眼就是棱。
    out.extend(_segment(points_by_weight, a, mid, depth + 1, ref))
    out.extend(_segment(points_by_weight, mid, b, depth + 1, ref))
    return out


# ---------------------------------------------------------------- 三次 → 二次

def _quad_of_cubic(c0, c1, c2, c3):
    """一段三次的最优单条二次近似（段中点与原曲线严格重合）。"""
    return ((3 * (c1[0] + c2[0]) - c0[0] - c3[0]) * 0.25,
            (3 * (c1[1] + c2[1]) - c0[1] - c3[1]) * 0.25)


def _split_cubic(c0, c1, c2, c3, t):
    p01 = (c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t)
    p12 = (c1[0] + (c2[0] - c1[0]) * t, c1[1] + (c2[1] - c1[1]) * t)
    p23 = (c2[0] + (c3[0] - c2[0]) * t, c2[1] + (c3[1] - c2[1]) * t)
    p012 = (p01[0] + (p12[0] - p01[0]) * t, p01[1] + (p12[1] - p01[1]) * t)
    p123 = (p12[0] + (p23[0] - p12[0]) * t, p12[1] + (p23[1] - p12[1]) * t)
    m = (p012[0] + (p123[0] - p012[0]) * t, p012[1] + (p123[1] - p012[1]) * t)
    return [(c0, p01, p012, m), (m, p123, p23, c3)]


def _cubic_slice(c0, c1, c2, c3, a, b):
    """取三次贝塞尔在参数区间 [a, b] 上的那一段（de Casteljau 两次切分）。"""
    if a > 0.0:
        _left, (c0, c1, c2, c3) = _split_cubic(c0, c1, c2, c3, a)
        b = 1.0 if b >= 1.0 else (b - a) / (1.0 - a)
    if b < 1.0:
        (c0, c1, c2, c3), _right = _split_cubic(c0, c1, c2, c3, b)
    return (c0, c1, c2, c3)


def _sub_cubics(c0, c1, c2, c3, n):
    """按参数等分成 n 段三次。"""
    n = max(1, int(n))
    if n == 1:
        return [(c0, c1, c2, c3)]
    return [_cubic_slice(c0, c1, c2, c3, i / n, (i + 1) / n) for i in range(n)]


def _cubic_quad_err(c0, c1, c2, c3):
    """单条二次近似这条三次的最大误差。

    三次与「中点匹配的单条二次」之差是 t(1-t)(2t-1) 的量级，极值在 t=(3±√3)/6 ≈
    0.211/0.789 附近；取这两点就够选 n 用，不必撒 7 个采样点（每段要算五遍，差 3 倍）。
    """
    qx, qy = _quad_of_cubic(c0, c1, c2, c3)
    worst = 0.0
    for t in (0.21132486540518713, 0.7886751345948129):
        u = 1 - t
        a = _bez(c0, c1, c2, c3, t)
        bx = u * u * c0[0] + 2 * u * t * qx + t * t * c3[0]
        by = u * u * c0[1] + 2 * u * t * qy + t * t * c3[1]
        e = math.hypot(a[0] - bx, a[1] - by)
        if e > worst:
            worst = e
    return worst


def _n_quad(cubic, tol=QUAD_TOL):
    """这段三次要拆成几条二次才够准。"""
    for n in range(1, MAX_QUAD + 1):
        ok = True
        for seg in _sub_cubics(*cubic, n):
            if _cubic_quad_err(*seg) > tol:
                ok = False
                break
        if ok:
            return n
    return MAX_QUAD


# ---------------------------------------------------------------- 对外

def fit_rings(dense, anchors):
    """dense: {档: [环点列]}（三档同索引）；anchors: [环号][锚点索引]。

    返回 ({档: [环点列]}, {档: [环 flags]})，flags 里 1 = on-curve、0 = off-curve。
    三档的环点数与 flags 逐一相同。
    """
    weights = list(dense)
    out_pts = {w: [] for w in weights}
    out_flags = {w: [] for w in weights}
    for ri, ring in enumerate(dense[weights[0]]):
        n = len(ring)
        if n < 4:
            for w in weights:
                out_pts[w].append(list(dense[w][ri]))
                out_flags[w].append([1] * n)
            continue
        # **不拿 DP 的保留点当锚点**：闭合环上 DP 的初始弦穿过环心，远端点的「离弦」
        # 是半径量级，于是它会在一条光滑的大弧上每隔几十单位硬插一个点——锚点一密，
        # 每段只剩两三个点，拟合退化成连直线，点数反而更多。
        # 只用两个起始点（首点 + 离它最远的点），其余交给拟合自己按误差切。
        idx = sorted(anchors[ri]) if anchors[ri] else []
        if len(idx) < 2:
            # 只用两个起始点（首点 + 离它最远的点），其余交给递归按误差切。
            # 按弧长每 110 单位预分割会在光滑弧上硬插分界，每插一处就多一个 on 点，
            # 实测那一条让点数多 7%。
            far = max(range(n), key=lambda i: _dist(ring[i], ring[0]))
            idx = sorted({0, far})
        if len(idx) < 2:                    # 退化环：退回密点，宁可多几个点也不许走形
            for w in weights:
                out_pts[w].append(list(dense[w][ri]))
                out_flags[w].append([1] * n)
            continue
        per_w = {w: dense[w][ri] for w in weights}
        # 参考档固定 400：切分与二次拆分数都按它判，它是最贴合母版的那一档。
        ref_w = 400 if 400 in per_w else weights[0]
        ref = per_w[ref_w]
        # 闭合环：段 = idx[k] → idx[k+1]（末段回绕到 idx[0]）
        segs = []
        for k in range(len(idx)):
            segs.extend(_segment(per_w, idx[k], idx[(k + 1) % len(idx)], 0, ref))
        # 直线段一个点都不多给；曲线段拟合三次、再拆二次（n 取三档最大）
        cubics = {w: [] for w in weights}
        for (a, b, kind) in segs:
            for w in weights:
                pts = _sub(per_w[w], a, b)
                c1, c2, _err, _at = _fit_one(pts, _params(pts))
                cubics[w].append((pts[0], c1, c2, pts[-1]))
        quads = {w: [] for w in weights}
        for si, (_a, _b, kind) in enumerate(segs):
            if kind == "line":
                for w in weights:
                    quads[w].append(None)
                continue
            if kind == "poly":
                for w in weights:
                    quads[w].append("poly")
                continue
            # 二次拆分数只按参考档（400）算：三档形状差一个笔宽，需要的段数在这个精度下相同
            k = _n_quad(cubics[ref_w][si])
            for w in weights:
                quads[w].append([(_quad_of_cubic(*s), s[3])
                                 for s in _sub_cubics(*cubics[w][si], k)])
        for w in weights:
            pts, flags = [], []
            pts.append(cubics[w][0][0])
            flags.append(1)
            for si, chain in enumerate(quads[w]):
                if chain is None:                     # 直线：只加终点
                    pts.append(cubics[w][si][3])
                    flags.append(1)
                    continue
                if chain == "poly":                   # 拐角：段内密点全部留下
                    a_, b_, _k = segs[si]
                    for p in _sub(per_w[w], a_, b_)[1:]:
                        pts.append(p)
                        flags.append(1)
                    continue
                for q, end in chain:
                    pts.append(q)
                    flags.append(0)
                    pts.append(end)
                    flags.append(1)
            # 末点 == 起点（闭合），去掉
            if len(pts) > 2 and _dist(pts[-1], pts[0]) < 1e-9:
                pts.pop()
                flags.pop()
            out_pts[w].append(pts)
            out_flags[w].append(flags)
    return out_pts, out_flags
