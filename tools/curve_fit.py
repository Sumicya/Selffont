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
import os

FIT_TOL = float(os.environ.get("SELFFONT_FIT_TOL", 0.80))
                      # 三次贝塞尔拟合容差（字体单位）。0.4 会把每个 90° 圆角切成两段
                      # （R≈200 的弧单段三次误差 1.0），段数翻倍；0.8 与母版自身的
                      # 曲线误差（圆角两段二次、2.1 单位）同量级
QUAD_TOL = float(os.environ.get("SELFFONT_QUAD_TOL", 1.5))
                      # 三次 → 二次的弦高容差（字体单位）：母版 90° 圆角就是两段二次（误差 2.1 单位），
                      # 段越碎接点越多，接点上曲率不连续，放大看就是一圈棱
LINE_TOL = float(os.environ.get("SELFFONT_LINE_TOL", 0.12))
                      # 段内点到弦线的最大距离不超过它 → 当直线，一个点都不多给。
                      # 0.3 会把剖面上 0.2 单位的正常起伏判成弯，直边被拆成两三条曲线。
                      # 0.80 的反面：半径 31 的圆头，弦长 10.8 时矢高只有 0.47 ≤ 0.80，
                      # 于是整圈被判成直线 —— 屏幕上就是一个多边形（2026-11-01 主人指出的「多边形」）。
                      # 0.12 的由来（2026-11-01）：0.80 下半径 31 的圆头整圈被判成 12 段直线，
                      # 端头在 6× 下是多边形；0.12 让弦长 5.4 以上的弧全部走曲线，真直边（母版 81 单位
                      # 那种）不受影响。环境变量 SELFFONT_LINE_TOL 只为改前改后用同一份代码复算。
FIT_MODE = os.environ.get("SELFFONT_FIT_MODE", "proj")
# 隐式中点（2026-11-02）：独立于 FIT_MODE，任何拟合方式都能开。
IMPLICIT_MID = os.environ.get("SELFFONT_IMPLICIT_MID", "0") not in ("0", "", "no", "false")
# 强制隐式中点（2026-11-02）：把折角小于该阈值的接点改造成隐式中点，折角归零。0 = 关。
IMPLICIT_MERGE = float(os.environ.get("SELFFONT_IMPLICIT_MERGE", "8"))
MERGE_TOL = float(os.environ.get("SELFFONT_MERGE_TOL", "8"))   # 合并时控制点允许的最大位移（字体单位）
                      # 二次控制点怎么定（2026-11-02）：
                      #   "c0"     = 中点匹配（旧默认）
                      #   "proj"   = c0 打底再朝切向投影（_quad_proj），默认，形状安全
                      #   "g1"     = 切向交点，接点天然 G1
                      #   "bisect" = 保长度角平分线投影
                      # 2026-11-02 实测（100 字，相对 Maruko JP 原版）：
                      #   c0 / proj 折角中位 3.67°，整字 IoU 0.925 —— 安全
                      #   g1        折角中位 2.62°，IoU 0.861、最差 0.341 —— **伤形状，不采用**
                      #   bisect    折角中位 5.11°（更差），λ=1 时 76% 字形被拒 —— **不采用**
                      # 结论：TrueType 二次链在固定段数下，中点匹配的折角下限约 3.5°；
                      # 要更低必须换曲线类型（三次/CFF2）或换拓扑来源（直接搬母版，但那样
                      # 三档拓扑只有 1.0% 一致，做不出可变轴）。两条都超出本轮范围。
                      # 三者的段数判据都是 c0，所以点数只由几何决定、不受本开关影响。
QUAD_PROJ = float(os.environ.get("SELFFONT_QUAD_PROJ", "0.5"))
                      # 接点切向阻尼投影的强度 λ（2026-11-02）：0 = 老行为（只做中点匹配），
                      # 1 = 接点处严格 G1。只移动已有的二次控制点，**不改段数、不改点数**，
                      # 所以它是唯一一个「压折角不涨点数」的旋钮。取值见 docs/metrics.md。
MAX_QUAD = int(os.environ.get("SELFFONT_MAX_QUAD", 5))   # 单段三次最多拆成几条二次
MAX_DEPTH = 12        # 递归切分深度上限
BISECT_MAX_DEG = float(os.environ.get("SELFFONT_BISECT_MAX", "25.0"))
                      # 角平分线投影允许的最大转角（度）。超过不动：转了会鼓出去。
SMOOTH_JOINT_MAX = float(os.environ.get("SELFFONT_SMOOTH_JOINT", "30.0"))
                      # 接点投影的守卫：相邻两条三次自身切向差超过它，就当真折角，不投影

# 端点切向的来源。这是 2026-10-31 那一轮唯一动的变量，留开关是为了「改前 / 改后」
# 能用同一份代码复算，而不是靠 git 回滚去比。
#   "segment"（默认，旧） = 段内切向：段内点 ≥6 时用段内三点定圆，否则退回**弦方向**
#   "ring"              = 真切线：在**整条密点环**上取端点两侧邻点定圆，与这一段被切成多长无关
# 假设是「短段退回弦方向就是接点硬折的来源，换成真切线就能把跳变压下去」。3,500 字实测：
# ④ 中位 9.554° → 8.127°（−1.427），P90 10.854° → 9.410°，跳变确实降了；但 ① P90
# 44.202 → 46.275（+2.07）、③ lsb 合格率 99.57% → 99.40%（−0.17pp）两条守卫判据没过。
# 按事先定好的合取判据，这个改动**不采用**，默认留 "segment"；读数见 docs/metrics.md。
ENDPOINT_TANGENT = os.environ.get("SELFFONT_ENDPOINT_TANGENT", "segment")

# 诊断用：设 SELFFONT_JOINT_DEBUG=1 时，把每个接点的台账记到这里
# （环号, i 段类型, j 段类型, 三次切向差, 二次折角改前, 改后）。只为量「折角长在哪」，
# 不参与出件；默认关闭，不写文件。
JOINT_LOG: list[tuple] = []
_DEBUG_JOINTS = os.environ.get("SELFFONT_JOINT_DEBUG") == "1"


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


def _true_tangent(ring, i, toward):
    """整条密点环上 i 处的真切线：用两侧邻点定圆，共线就逐级加宽基线。

    与 `_tangent_at` 的差别只有一个：基线取的是**环上的邻点**，不是「这一段里的点」。
    段被切得再短，端点处的切向也还是整条曲线的切向——这正是接点不再出现硬折的原因。
    """
    n = len(ring)
    for span in (1, 2, 3, 5, 8):
        if 2 * span >= n:
            break
        a, b, c = ring[(i - span) % n], ring[i % n], ring[(i + span) % n]
        d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) > 1e-7:
            ux = ((a[0] ** 2 + a[1] ** 2) * (b[1] - c[1]) + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1])
                  + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])) / d
            uy = ((a[0] ** 2 + a[1] ** 2) * (c[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0])
                  + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])) / d
            tx, ty = -(a[1] - uy), (a[0] - ux)
            if tx * toward[0] + ty * toward[1] < 0:
                tx, ty = -tx, -ty
            nn = math.hypot(tx, ty)
            if nn > 1e-12:
                return (tx / nn, ty / nn)
    nxt = ring[(i + 1) % n]
    prv = ring[(i - 1) % n]
    return _unit(prv, nxt)



# ---------------------------------------------------------------- 单段拟合

def _fit_one(pts, u, t0=None, t3=None):
    """一段点列（首末是锚点）拟合成三次贝塞尔；返回 (c1, c2, max_err, at)。

    向量化：一段动辄两三百个点，逐点 Python 循环会把全库构建拖到一个小时以上。
    """
    import numpy as np

    P = np.asarray(pts, float)
    T = np.asarray(u, float)
    p0, p3 = P[0], P[-1]
    if t0 is None or t3 is None:            # 没给外部切向：按旧规则自己算（段内）
        if len(pts) >= 6:
            # 端点切向：正向取前三点、反向取末三点各做一次三点圆（端点附近曲率最可靠）
            t0 = _tangent_at(pts, 0, +1, (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
            t3 = _tangent_at(pts, len(pts) - 1, -1,
                             (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]))
        else:
            t0 = _unit(pts[0], pts[-1])      # 弦方向：这一行就是被替换掉的旧行为
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


def _quad_g1(c0, c1, c2, c3):
    """一段三次的**切向交点**二次近似：两端切向都与原曲线一致，接点天然 G1。

    二次的起始切向是「控制点−起点」，终止切向是「终点−控制点」。要两端切向都落在原
    曲线的切向线上，控制点只能取两条切线的交点——一条二次只有一个控制点，两个约束正
    好定死它。径向误差随每段张角四次方下降：90° 时 6.07%，45° 时 0.31%，22.5° 时
    0.019%，所以宁可多拆一段，也不要在接点上留缝。

    两条切向近乎平行（真直边）或交点跑到段外（反弯）时无解，退回中点匹配版。
    """
    da = (c1[0] - c0[0], c1[1] - c0[1])
    db = (c3[0] - c2[0], c3[1] - c2[1])
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < 1e-12:
        return _quad_of_cubic(c0, c1, c2, c3)
    ex, ey = c3[0] - c0[0], c3[1] - c0[1]
    chord = math.hypot(ex, ey)
    if chord < 1e-9:
        return _quad_of_cubic(c0, c1, c2, c3)
    # 交点写成 c0 + s·da = c3 + t·db。da 向前、db 也向前（c3−c2），控制点要落在 c0 的
    # 前方（s>0）与 c3 的后方（t<0）；符号反了说明这段在反弯，交点法不适用。
    s_ = (ex * db[1] - ey * db[0]) / den
    t_ = (ex * da[1] - ey * da[0]) / den
    if s_ <= 0 or t_ >= 0:
        return _quad_of_cubic(c0, c1, c2, c3)
    # 距离上界 3 倍弦长（半张角约 80°）：近乎直线的段两条切线几乎平行，交点会跑到几十倍
    # 弦长之外，控制点越出字身框，整字会被丢掉。
    if s_ * math.hypot(*da) > 3 * chord or -t_ * math.hypot(*db) > 3 * chord:
        return _quad_of_cubic(c0, c1, c2, c3)
    return (c0[0] + s_ * da[0], c0[1] + s_ * da[1])


def _nrm(v):
    n = (v[0] ** 2 + v[1] ** 2) ** 0.5
    return (v[0] / n, v[1] / n) if n > 1e-12 else (0.0, 0.0)


def _quad_proj(cubics, lam=0.5):
    """把一条二次链的**接点**朝 G1 投影，只挪控制点——段数与点数一个都不变。

    一条二次曲线 (P0, Q, P1) 的两端切向是 `Q−P0` 与 `P1−Q`。相邻两条要在接点 P 处
    切向连续，`P−Q_前` 与 `Q_后−P` 就得同向。中点匹配（`_quad_of_cubic`）只保证曲线
    经过段中点，接点切向不管，于是每拆一次段就在接点上留一个几度的折角——这正是
    「点数比母版多、边却比母版糙」的地方。

    做法：接点 P、该处切向 d（取后一段三次的起始切向），把两侧控制点各自朝
    「过 P、沿 d 的直线」正投影，只走 λ 倍距离。λ=1 是严格 G1；λ=1 的副作用是控制点
    可能被拉出去很远（近直段上投影距离很大），所以默认 0.5。

    为什么不是 g1 模式：那个换的是**控制点算法**，为了压误差会多拆段（点数 +29%、
    体积 +30%）。这里不动拆段，只在既有段上改接点，所以点数恒定。

    输入 `cubics` 是一条**首尾相接**的三次曲线链（闭合环就是整环）；返回同样长度的
    [(起点, 控制点, 终点)]。
    """
    quads = [[s[0], _quad_of_cubic(*s), s[3]] for s in cubics]
    if lam <= 0 or len(quads) < 2:
        return [tuple(q) for q in quads]
    tang = [_nrm((s[1][0] - s[0][0], s[1][1] - s[0][1])) for s in cubics]
    tend = [_nrm((s[3][0] - s[2][0], s[3][1] - s[2][1])) for s in cubics]
    n = len(quads)

    def _angle(a, b):
        c = a[0] * b[0] + a[1] * b[1]
        return math.degrees(math.acos(max(-1.0, min(1.0, c))))

    def _joint(i, j):
        """这一对二次在接点上形成的折角（度）与折反（180° 附近）都要能看见。"""
        P = quads[i][2]
        a = _nrm((P[0] - quads[i][1][0], P[1] - quads[i][1][1]))
        b = _nrm((quads[j][1][0] - P[0], quads[j][1][1] - P[1]))
        return _angle(a, b)

    for i in range(n):
        j = (i + 1) % n
        # 守卫一：真折角不动。相邻两条三次自己的切向就差很多，那不是「同一段弧被切碎」
        # 而是设计上的拐；投影上去会把角磨平、把形状改坏（实测 P90 18.96°→68.34°）。
        if _angle(tend[i], tang[j]) > SMOOTH_JOINT_MAX:
            if _DEBUG_JOINTS:
                JOINT_LOG.append(("corner", _angle(tend[i], tang[j]), _joint(i, j), _joint(i, j)))
            continue
        P = quads[i][2]
        d = tang[j]
        qa, qb = quads[i][1], quads[j][1]
        sa = (qa[0] - P[0]) * d[0] + (qa[1] - P[1]) * d[1]
        sb = (qb[0] - P[0]) * d[0] + (qb[1] - P[1]) * d[1]
        na = (qa[0] + lam * (P[0] + sa * d[0] - qa[0]),
              qa[1] + lam * (P[1] + sa * d[1] - qa[1]))
        nb = (qb[0] + lam * (P[0] + sb * d[0] - qb[0]),
              qb[1] + lam * (P[1] + sb * d[1] - qb[1]))
        # 守卫二：只接受折角变小，不接受折反。
        before = _joint(i, j)
        qa0, qb0 = quads[i][1], quads[j][1]
        quads[i][1], quads[j][1] = na, nb
        after = _joint(i, j)
        if after > before:
            quads[i][1], quads[j][1] = qa0, qb0
            after = before
        if _DEBUG_JOINTS:
            JOINT_LOG.append(("joint", _angle(tend[i], tang[j]), before, after))
    return [tuple(q) for q in quads]


def _angle_deg(a, b):
    c = a[0] * b[0] + a[1] * b[1]
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _proj_toward(q, P, d, lam):
    """把 q 朝「过 P、沿 d 的直线」移动 lam 倍，返回新点。"""
    t = (q[0] - P[0]) * d[0] + (q[1] - P[1]) * d[1]
    return (q[0] + lam * (P[0] + t * d[0] - q[0]),
            q[1] + lam * (P[1] + t * d[1] - q[1]))


def _quad_bisect(cubics, lam=1.0):
    """保长度的角平分线投影：把接点两侧控制点放到同一条角平分线上，**各自长度不变**。

    为什么不是 g1（切向交点）：那个为了两端都贴原切向，会把控制点甩很远，大张角下
    径向误差 6%，实测整字 IoU 掉到 0.861、最差 0.341。
    为什么不是投影到后段切向：投影会改变控制点到接点的距离，近距离时方向误差放大，
    而且容易翻到接点另一侧（被守卫拒绝后原地不动，折角还在）。

    这里：方向取两段三次自身切向的角平分线 d，两侧控制点分别放在 `P−|q−P|·d` 与
    `P+|q−P|·d`。于是末切向 = P−qa = |qa−P|·d、首切向 = qb−P = |qb−P|·d，**严格共线**，
    折角恒为 0；长度一个数都没动，所以形状只是绕接点转了一下。
    """
    quads = [[s[0], _quad_of_cubic(*s), s[3]] for s in cubics]
    if lam <= 0 or len(quads) < 2:
        return [tuple(q) for q in quads]
    tang = [_nrm((s[1][0] - s[0][0], s[1][1] - s[0][1])) for s in cubics]
    tend = [_nrm((s[3][0] - s[2][0], s[3][1] - s[2][1])) for s in cubics]
    n = len(quads)
    for i in range(n):
        j = (i + 1) % n
        P = quads[i][2]
        d = _nrm((tend[i][0] + tang[j][0], tend[i][1] + tang[j][1]))
        if d == (0.0, 0.0):
            continue
        for slot, sign in ((i, -1.0), (j, 1.0)):
            q = quads[slot][1]
            vx, vy = q[0] - P[0], q[1] - P[1]
            L = (vx * vx + vy * vy) ** 0.5
            if L < 1e-6:
                continue
            tx, ty = P[0] + sign * L * d[0], P[1] + sign * L * d[1]
            # 限制单次转角：保长度但转到角平分线，若原方向与 d 差得多，曲线会鼓出去。
            # BISECT_MAX_DEG 之外的不动（那些多半是真折笔或端头附近，转了会变形）。
            ux, uy = -sign * vx / L, -sign * vy / L          # 原方向（指向接点）
            if _angle_deg((ux, uy), (sign * d[0], sign * d[1])) > BISECT_MAX_DEG:
                continue
            quads[slot][1] = (q[0] + lam * (tx - q[0]), q[1] + lam * (ty - q[1]))
    return [tuple(q) for q in quads]


def _implicit_mid_points(out_pts, out_flags, ri, weights, tol=0.05):
    """把「恰在前后两个 off 点中点」的显式 on 点标成可删，按倒序删三档。

    返回删掉的个数。三档同时判断（同一索引三档都满足才删）。
    """
    w0 = weights[0]
    pts0, flags0 = out_pts[w0][ri], out_flags[w0][ri]
    n = len(pts0)
    if n < 4:
        return 0
    victims = []
    for i in range(n):
        if flags0[i] != 1:
            continue
        a, b = (i - 1) % n, (i + 1) % n
        if flags0[a] != 0 or flags0[b] != 0:
            continue
        ok = True
        for w in weights:
            pw = out_pts[w][ri]
            if _dist(pw[i], ((pw[a][0] + pw[b][0]) * 0.5, (pw[a][1] + pw[b][1]) * 0.5)) > tol:
                ok = False
                break
        if ok:
            victims.append(i)
    if not victims:
        return 0
    # 相邻两个 victim 不能同时删（删完会变成三个 off 点连排，中点规则仍然成立，但
    # 第二个中点就不是原来那个 on 点了）。隔一个删。
    keep = []
    last = -99
    for i in victims:
        if i - last > 1 and not (last == 0 and i == n - 1):
            keep.append(i)
            last = i
    if not keep:
        return 0
    for i in sorted(keep, reverse=True):
        for w in weights:
            out_pts[w][ri].pop(i)
            out_flags[w][ri].pop(i)
    return len(keep)


def _implicit_merge(out_pts, out_flags, ri, weights, max_deg):
    """把「本来就在缓折」的显式 on 点改造成隐式中点，折角归零且不占点。

    母版接点 0° 不是因为拟合得好，而是因为它**根本不存 on 点**：相邻两个 off 点的中点
    由渲染器补出，那个中点天生 G1。我们全显式，每个接点都得自己挣 G1——这就是「重画
    一遍糙一档」真正花钱的地方。

    这里反向利用同一机制：挑接点 P，把两侧控制点 C、D 摆成关于 P 对称（方向取 C→D
    割线，长度取原两侧的平均），P 就精确等于 (C+D)/2，再删掉 P。曲线在 P 处的切向变成
    C→D 方向，折角恒 0。只动缓折接点：硬掰张角大的接点会把笔锋压平，那是设计的拐，
    不是误差。三档同时判定——gvar 的点序必须对齐，删不删只能有一个答案。
    """
    w0 = weights[0]
    pts0, flags0 = out_pts[w0][ri], out_flags[w0][ri]
    n = len(pts0)
    if n < 6:
        return 0
    victims = []
    for i in range(n):
        if flags0[i] != 1:
            continue
        a, b = (i - 1) % n, (i + 1) % n
        if flags0[a] != 0 or flags0[b] != 0:
            continue
        ok = True
        for w in weights:
            pw = out_pts[w][ri]
            P, C, D = pw[i], pw[a], pw[b]
            u = (P[0] - C[0], P[1] - C[1])
            v = (D[0] - P[0], D[1] - P[1])
            lu = (u[0] * u[0] + u[1] * u[1]) ** 0.5
            lv = (v[0] * v[0] + v[1] * v[1]) ** 0.5
            if lu < 1e-6 or lv < 1e-6:
                ok = False
                break
            if _angle_deg(u, v) > max_deg:
                ok = False
                break
        if ok:
            victims.append(i)
    if not victims:
        return 0
    keep = []
    last = -99
    for i in victims:
        if i - last > 1 and not (last == 0 and i == n - 1):
            keep.append(i)
            last = i
    if not keep:
        return 0
    for i in sorted(keep, reverse=True):
        # 先在**每一档**上算出对称摆法，全部合格才落刀：三档只允许一个答案，否则点数分叉。
        plans = {}
        ok = True
        for w in weights:
            pw = out_pts[w][ri]
            a, b = (i - 1) % len(pw), (i + 1) % len(pw)
            P, C, D = pw[i], pw[a], pw[b]
            # 约束是 (C'+D')/2 = P：两侧臂必须等长且共线，只有一个自由度 w。
            # 对 |C'−C|² + |D'−D|² 求极小，解就是 w = (D−C)/2——把 P 与中点的
            # 偏差**平分**给两个控制点。控制点因此只落在原 C–D 连线上，不会外飞
            # （曾用「两侧臂长取平均」，一长一短时把控制点甩出字身框，97/100 字被拒）。
            wx, wy = (D[0] - C[0]) * 0.5, (D[1] - C[1]) * 0.5
            # 位移守卫：控制点挪得太远说明这个接点并不是「缓折」，宁可不合。
            if (max(abs(wx - (P[0] - C[0])), abs(wy - (P[1] - C[1])),
                    abs(wx - (D[0] - P[0])), abs(wy - (D[1] - P[1]))) > MERGE_TOL):
                ok = False
                break
            plans[w] = (a, b, P, wx, wy)
        if not ok:
            continue
        for w in weights:
            a, b, P, wx, wy = plans[w]
            out_pts[w][ri][a] = (P[0] - wx, P[1] - wy)
            out_pts[w][ri][b] = (P[0] + wx, P[1] + wy)
            out_pts[w][ri].pop(i)
            out_flags[w][ri].pop(i)
    return len(keep)


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
    # 判据固定用中点匹配：g1 在大张角下径向误差更大（90° 时 6%），拿它判段数会
    # 一路把段拆碎（实测点数 +29%）。段数按 c0 判，控制点可以另选——见 FIT_MODE。
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
                if ENDPOINT_TANGENT == "ring" and kind != "poly":
                    # 真切线：端点处取整条环上的邻点定圆，与这一段被切多短无关。
                    ring_w = per_w[w]
                    t0 = _true_tangent(ring_w, a, _unit(ring_w[(a - 1) % n], ring_w[(a + 1) % n]))
                    t3 = _true_tangent(ring_w, b, _unit(ring_w[(b - 1) % n], ring_w[(b + 1) % n]))
                else:
                    t0 = t3 = None
                c1, c2, _err, _at = _fit_one(pts, _params(pts), t0, t3)
                cubics[w].append((pts[0], c1, c2, pts[-1]))
        # 先把每段的三次拆成 k 条二次的下料单攒起来，再按「连续的曲线段」连成链做接点投影。
        # 直线段与拐角段（poly）没有二次控制点，是链的断点：跨过它们的接点不在这一版的处理
        # 范围内（那边的另一侧根本不是二次曲线）。
        subs = {w: [] for w in weights}
        quads = {w: [] for w in weights}
        for si, (_a, _b, kind) in enumerate(segs):
            if kind in ("line", "poly"):
                for w in weights:
                    subs[w].append(None)
                    quads[w].append(None if kind == "line" else "poly")
                continue
            # 二次拆分数只按参考档（400）算：三档形状差一个笔宽，需要的段数在这个精度下相同
            k = _n_quad(cubics[ref_w][si])
            for w in weights:
                subs[w].append(_sub_cubics(*cubics[w][si], k))
                quads[w].append([])          # 占位，长度与 segs 对齐；下面按链回填

        for w in weights:
            run: list[int] = []
            todo: list[tuple[list[int], list[tuple]]] = []
            for si in range(len(segs)):
                if subs[w][si] is None:
                    if run:
                        todo.append((run, [x for si2 in run for x in subs[w][si2]]))
                        run = []
                else:
                    run.append(si)
            if run:
                todo.append((run, [x for si2 in run for x in subs[w][si2]]))
            for idxs, chain in todo:
                if FIT_MODE == "g1":
                    moved = [(_quad_g1(*c), c[3]) for c in chain]
                elif FIT_MODE == "c0":
                    moved = [(_quad_of_cubic(*c), c[3]) for c in chain]
                elif FIT_MODE == "bisect":
                    moved = [(q[1], q[2]) for q in _quad_bisect(chain, QUAD_PROJ)]
                else:
                    moved = [(q[1], q[2]) for q in _quad_proj(chain, QUAD_PROJ)]
                at = 0
                for si in idxs:
                    n_sub = len(subs[w][si])
                    quads[w][si] = moved[at:at + n_sub]
                    at += n_sub

        # 第二遍：曲线与**直线**相接的接点。这一侧只有一根控制柄，投影到直线方向上就够，
        # 不需要成对。跑之前这些接点完全没被处理过（直线段是链的断点），而横竖笔画的
        # 直边与端头/转折相接处正是它们——不补这一遍，中位数压不下去。
        if FIT_MODE in ("proj", "bisect") and QUAD_PROJ > 0:
            for w in weights:
                n_seg = len(segs)
                for si in range(n_seg):
                    j = (si + 1) % n_seg
                    a_lin = subs[w][si] is None and segs[si][2] == "line"
                    b_lin = subs[w][j] is None and segs[j][2] == "line"
                    if a_lin == b_lin:
                        continue                      # 两侧同类型（都曲线或都直线/拐角）：不处理
                    P = cubics[w][si][3]
                    if b_lin:                         # 曲线 i → 直线 j：末控制点朝直线方向投影
                        d = _nrm((cubics[w][j][3][0] - cubics[w][j][0][0],
                                  cubics[w][j][3][1] - cubics[w][j][0][1]))
                        t_side = _nrm((cubics[w][si][3][0] - cubics[w][si][2][0],
                                       cubics[w][si][3][1] - cubics[w][si][2][1]))
                        chain, slot, tail = quads[w][si], -1, True
                    else:                             # 直线 i → 曲线 j：首控制点朝直线方向投影
                        d = _nrm((cubics[w][si][3][0] - cubics[w][si][0][0],
                                  cubics[w][si][3][1] - cubics[w][si][0][1]))
                        t_side = _nrm((cubics[w][j][1][0] - cubics[w][j][0][0],
                                       cubics[w][j][1][1] - cubics[w][j][0][1]))
                        chain, slot, tail = quads[w][j], 0, False
                    # 真折角不动：曲线在接点处的切向与直线差得远，说明这是设计的拐，不是误差
                    if _angle_deg(t_side, d) > SMOOTH_JOINT_MAX:
                        continue
                    if not isinstance(chain, list) or not chain:
                        continue
                    q = chain[slot][0]
                    before = _angle_deg(_nrm((P[0] - q[0], P[1] - q[1]) if tail else
                                             (q[0] - P[0], q[1] - P[1])), d)
                    moved = _proj_toward(q, P, d, QUAD_PROJ)
                    after = _angle_deg(_nrm((P[0] - moved[0], P[1] - moved[1]) if tail else
                                            (moved[0] - P[0], moved[1] - P[1])), d)
                    if after <= before:               # 只接受折角变小，不接受折反
                        chain[slot] = (moved, chain[slot][1])

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
    if IMPLICIT_MID or FIT_MODE == "c0_none":
        # 隐式接点（2026-11-02）：TrueType 允许两个 off-curve 点相邻，中点由渲染器补出，
        # 而那个中点**天然 G1**——它是两个 off 点的均值，入切向 (M−A) 与出切向 (B−M)
        # 本来共线。母版正是这么排的（「一」14 点里 6 on / 8 off，最长连续 off = 2），
        # 所以它的接点折角是 0.00°。我们此前全是显式 on 点，每个接点都要自己挣 G1。
        # 这里把「正好落在前后两个 off 点中点」的显式 on 点删掉：曲线一个像素都不动，
        # 点数反而更少。三档必须同时满足才删，否则 gvar 的点序会错位。
        for ri in range(len(out_pts[weights[0]])):
            for _round in range(3):
                lens = {w: len(out_pts[w][ri]) for w in weights}
                if len(set(lens.values())) != 1:
                    break
                drop = _implicit_mid_points(out_pts, out_flags, ri, weights)
                if not drop:
                    break
    # 强制隐式中点：独立于上面的开关，任何拟合方式都能跑（见 _implicit_merge）。
    if IMPLICIT_MERGE > 0:
        for ri in range(len(out_pts[weights[0]])):
            # 只跑一轮：多轮会级联（这轮合掉 i，下轮 i+2 又满足条件），实测四轮把全库
            # on 点从 16,313 啃到 7,916——角被一起啃平了。一轮的每一次合并都受守卫约束。
            for _round in range(1):
                lens = {w: len(out_pts[w][ri]) for w in weights}
                if len(set(lens.values())) != 1:
                    break
                if not _implicit_merge(out_pts, out_flags, ri, weights, IMPLICIT_MERGE):
                    break
    return out_pts, out_flags
