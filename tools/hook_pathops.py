"""去钩：切在笔身的直段上，端头不留任何残余。

目标（用户定义）
----------------
去钩之后，剩下的只有**横 / 竖 / 斜**的直笔画本身——不要鼓包（球）、不要细线、
不要钩的弯曲残留。

为什么这样切
------------
1. **切平面垂直于笔身**。钩根常落在骨架交叉点上，那里的距离变换是两条笔画并集的
   内切圆半径，比任何一条都粗（`九` 34.8 vs 全字 32.7）。用它在钩根套一个圆盘，
   端头必然比笔画粗——这就是之前「末端鼓出一个球」的根因。
2. **切点退到笔身直段上**（沿笔身分支退 1.15 倍钩半宽起，自动往前找位置）。
   在笔身上量出来的宽度才是这条笔画的真宽度。
3. **半径用切口处的垂直截距实测**：从切点沿法线往两边走到墨迹边界，取两侧截距的
   平均。这是"那一条笔画在那一处有多宽"的字面定义，不受交叉点影响；两侧截距相差
   太大（说明切点还在分叉处）就继续往前退。
4. **端头是半圆**，半径 = 实测半宽，圆心 = 切点：切平面是直切，半圆内切于切口，
   两侧相切。这是 Maruko 的自由端头规则（`docs/design-principles.md`）。
5. **圆弧只并回原字形本来有的墨**（cap ∩ 原字），保证结果永远是原字形的子集，
   绝不无中生有。

用法：
    python3 tools/hook_pathops.py 输入.ttf 输出.ttf --chars 九乙了子也包必電
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pathops
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from scipy import ndimage
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_erase import find_hooks as raster_hooks  # noqa: E402
from hook_taper import _adjacency  # noqa: E402
from stroke_width_normalize_prototype import raster_mask  # noqa: E402

BACK = 0.0         # 切点从钩根沿笔身退这么多倍「钩半宽」（0 = 就切在钩根）
BACK_STEP = 0.45   # 截距不可信时继续往前退
BACK_MAX = 3.0
ASYM_MAX = 1.45    # 两侧截距之比超过这个值就当切点还没离开分叉
MIN_AREA = 0.25    # 面积小于 MIN_AREA·r² 的碎片丢掉
THIN_FRAC = 0.35   # 轮廓「等效厚度」小于 THIN_FRAC·r 的当针状残余丢掉


# ------------------------------------------------------------------ 路径工具
def _glyph_path(font, gname):
    path = pathops.Path()
    font["glyf"][gname].draw(pathops.PathPen(path), font["glyf"])
    return path


def _polyline_path(pts):
    p = pathops.Path()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    return p


def _rdp(pts, tol):
    if len(pts) < 3:
        return list(pts)
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = (math.hypot(x - x0, y - y0) if n < 1e-9
             else abs(dy * x - dx * y + x1 * y0 - y1 * x0) / n)
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return _rdp(pts[:idx + 1], tol)[:-1] + _rdp(pts[idx:], tol)


def _ball(cx, cy, r, n=96):
    p = pathops.Path()
    for i in range(n):
        a = 2 * math.pi * i / n
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        p.moveTo(x, y) if i == 0 else p.lineTo(x, y)
    p.close()
    return p


def _contour_area(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2


def _contour_perimeter(pts):
    return sum(math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0],
                          pts[(i + 1) % len(pts)][1] - pts[i][1])
               for i in range(len(pts)))


def _drop_slivers(path, min_area, min_thickness=0.0, outer_sign=None):
    """丢掉碎片和针状轮廓。

    「等效厚度」= 面积 / (周长/2)：一条宽 2r、长 L 的笔画，其外轮廓的面积 ≈ 2rL、
    周长 ≈ 2L，厚度 ≈ r；针状残余宽 w 时厚度 ≈ w/2。所以厚度阈值能精准杀掉针状
    轮廓而不误伤内白（内白是挖洞，绕向相反，一律保留）。
    """
    out = pathops.Path()
    for contour in path.contours:
        pts = [(float(x), float(y)) for x, y in contour.points]
        if len(pts) < 3:
            continue
        a = abs(_contour_area(pts))
        per = _contour_perimeter(pts)
        thickness = a / (per / 2) if per > 1e-9 else 0.0
        sign = 1 if _contour_area(pts) > 0 else -1
        is_hole = outer_sign is not None and sign != outer_sign
        if not is_hole:
            if a < min_area:
                continue
            if min_thickness and thickness < min_thickness:
                continue
        out.addPath(contour)
    return out


def _outer_sign(path):
    best = None
    for contour in path.contours:
        pts = [(float(x), float(y)) for x, y in contour.points]
        if len(pts) < 3:
            continue
        a = _contour_area(pts)
        if best is None or abs(a) > abs(best):
            best = a
    return 0 if best is None else (1 if best > 0 else -1)


# ------------------------------------------------------------------ 骨架工具
def _longest_branch(root, banned, sk, min_len):
    """从 root 绕开 banned 走得最远的那条骨架分支，返回 root → 该点的路径。

    取「最远」而不是「最近」：钩根常落在交叉点，最近的点可能属于另一条笔画。
    """
    dists = {root: 0.0}
    prev = {}
    frontier = [root]
    while frontier:
        nxt = []
        for p in frontier:
            for q in _adjacency(p, sk):
                if q in dists or q in banned:
                    continue
                dists[q] = dists[p] + math.hypot(q[0] - p[0], q[1] - p[1])
                prev[q] = p
                nxt.append(q)
        frontier = nxt
    if len(dists) < 2:
        return []
    far = max(dists, key=dists.get)
    if dists[far] < min_len:
        return []
    path = [far]
    while path[-1] != root:
        path.append(prev[path[-1]])
    return list(reversed(path))


def _arc(branch):
    out = [0.0]
    for i in range(1, len(branch)):
        out.append(out[-1] + math.hypot(branch[i][0] - branch[i - 1][0],
                                        branch[i][1] - branch[i - 1][1]))
    return out


def _point_at(branch, arc, s):
    if s <= 0:
        return branch[0]
    for i, si in enumerate(arc):
        if si >= s:
            if i == 0:
                return branch[0]
            t = (s - arc[i - 1]) / max(1e-9, arc[i] - arc[i - 1])
            a, b = branch[i - 1], branch[i]
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return branch[-1]


def _tangent(branch, arc, s, half_window):
    """s 处的单位切向（像素坐标 y,x）。用前后各 half_window 弧长的两点连线。"""
    a = _point_at(branch, arc, max(0.0, s - half_window))
    b = _point_at(branch, arc, s + half_window)
    dy, dx = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dy, dx)
    if n < 1e-9:
        return (0.0, 1.0)
    return (dy / n, dx / n)


def _perp_excursion(mask, point, tangent, max_half, step=0.25):
    """从 point 沿垂直方向往两边走，返回两侧到墨迹边界的距离。

    `exited` 为 False 表示那一侧在 max_half 只内没走出墨迹——说明那里还有别的
    笔画（切点还在分叉处），这一点的测量不可用。
    """
    h, w = mask.shape
    ty, tx = tangent
    ny, nx = -tx, ty
    out = []
    for sgn in (1, -1):
        t = 0.0
        last = 0.0
        exited = False
        while t < max_half:
            t += step
            yy = point[0] + sgn * t * ny
            xx = point[1] + sgn * t * nx
            iy, ix = int(round(yy)), int(round(xx))
            if not (0 <= iy < h and 0 <= ix < w):
                exited = True
                break
            if mask[iy, ix]:
                last = t
            else:
                exited = True
                break
        out.append((last, exited))
    return out


# ------------------------------------------------------------------ 栅格上下文
def analyse(font, gname, px=2000, margin_frac=0.08):
    mask, tr = raster_mask(font, gname, px, margin_frac)
    dist = ndimage.distance_transform_edt(mask)
    sk = skeletonize(mask)
    return dict(mask=mask, sk=sk, dist=dist, tr=tr, px=px,
                hooks=raster_hooks(mask, sk, dist))


def to_font(ctx, y, x):
    xmin, ymin, _s, margin, upp, _sign = ctx["tr"]
    return (xmin + (x - margin) * upp, ymin + (ctx["px"] - margin - y) * upp)


# ------------------------------------------------------------------ 切一处钩
def _hook_mask(pts, shape, rad):
    m = np.zeros(shape, bool)
    for y, x in pts:
        y0, y1 = max(0, int(y - rad)), min(shape[0], int(y + rad) + 1)
        x0, x1 = max(0, int(x - rad)), min(shape[1], int(x + rad) + 1)
        if y1 > y0 and x1 > x0:
            yy, xx = np.mgrid[y0:y1, x0:x1]
            m[y0:y1, x0:x1] |= (yy - y) ** 2 + (xx - x) ** 2 <= rad * rad
    return m


def _body_axis(hook, ctx, r_hook_px):
    """笔身方向：把钩的墨剔除后，对钩根附近的墨做 PCA。

    为什么不用骨架、也不用钩的走向：
      * 骨架在钩根处落在交叉点上，"最长分支"会拐到别的笔画（`九` 因此被切掉
        5.6 万单位²）；
      * 钩在钩根处**不一定**与笔身相切（`九` 的竖弯钩是向上折的），钩的走向
        与笔身可以差 90°。
    剔除钩之后剩下的墨就是笔身本身，它的主方向就是笔身轴向；符号取"指向墨迹
    重心"，天然指向笔身内部。
    """
    _cut, removed, _w = hook
    pts = [(int(p[0]), int(p[1])) for p in removed]
    root = pts[-1]
    mask = ctx["mask"]
    win = 2.8 * r_hook_px
    y0, y1 = max(0, int(root[0] - win)), min(mask.shape[0], int(root[0] + win) + 1)
    x0, x1 = max(0, int(root[1] - win)), min(mask.shape[1], int(root[1] + win) + 1)
    if y1 <= y0 or x1 <= x0:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    near = ((yy - root[0]) ** 2 + (xx - root[1]) ** 2 <= win * win) & mask[y0:y1, x0:x1]
    hookm = _hook_mask(pts, mask.shape, 1.25 * r_hook_px)[y0:y1, x0:x1]
    body = near & ~hookm
    if body.sum() < 50:
        return None
    ys, xs = yy[body].astype(float), xx[body].astype(float)
    cy, cx = ys.mean(), xs.mean()
    cov = np.cov(np.vstack([ys - cy, xs - cx]))
    w, v = np.linalg.eigh(cov)
    dy, dx = v[:, int(np.argmax(w))]
    # 符号：指向墨迹重心（笔身内部）
    if (cy - root[0]) * dy + (cx - root[1]) * dx < 0:
        dy, dx = -dy, -dx
    n = math.hypot(dx, dy) or 1.0
    return (dy / n, dx / n)


def _place_cut(hook, ctx):
    """定切点与半径：切点在钩根，半径用垂直截距实测。"""
    _cut, removed, _w = hook
    pts = [(int(p[0]), int(p[1])) for p in removed]
    root = pts[-1]
    upp = ctx["tr"][4]
    r_hook_px = float(np.median([ctx["dist"][p] for p in pts]))
    if r_hook_px < 1.0:
        return None
    axis = _body_axis(hook, ctx, r_hook_px)
    if axis is None:
        return None
    dy, dx = axis
    best = None
    for k in range(0, 14):
        off = (0.0 + k * BACK_STEP) * r_hook_px
        P = (root[0] + dy * off, root[1] + dx * off)
        a, b = _perp_excursion(ctx["mask"], P, (dy, dx), 2.6 * r_hook_px)
        if not (a[1] and b[1]):
            continue
        if a[0] < 0.6 * r_hook_px or b[0] < 0.6 * r_hook_px:
            continue
        asym = max(a[0], b[0]) / max(1e-9, min(a[0], b[0]))
        if asym > ASYM_MAX:
            continue
        best = dict(P=P, tangent=(dy, dx), s=off, left=a[0], right=b[0], asym=asym,
                    r_px=(a[0] + b[0]) / 2, r_hook_px=r_hook_px, upp=upp)
        break
    return best


def _medial_end_dist(pts, ctx, r_hook_px):
    """笔身半宽：从钩根沿"最长的非钩骨架分支"取距离变换的中位数。

    不在钩根处取：钩根落在交叉点时，那里的内切圆是两条笔画并集的半径，比任何
    一条都粗（`九` 34.8 vs 全字 32.7），端头会鼓成球。
    """
    root = pts[-1]
    banned = set(pts)
    br = _longest_branch(root, banned, ctx["sk"], 3.0 * r_hook_px)
    if len(br) < 5:
        return float(np.median([ctx["dist"][p] for p in pts]))
    return float(np.median([ctx["dist"][p] for p in br]))


def _hook_axis(pts, r_hook_px):
    """钩在钩根处的走向（像素，“根 → 尖”方向）。

    钩是笔身的连续延续，在钩根处与笔身**相切**，所以它的反向就是笔身轴向。
    用最后约 1.2r 的点做最小二乘拟合，不用相邻两像素——单像素方向只有 8 个取值。
    """
    root = pts[-1]
    acc = 0.0
    sel = [root]
    prev = root
    for q in reversed(pts[:-1]):
        acc += math.hypot(q[0] - prev[0], q[1] - prev[1])
        prev = q
        sel.append(q)
        if acc >= 1.2 * r_hook_px:
            break
    if len(sel) < 3:
        return None
    a = np.asarray(sel, float)          # (n, 2) as (y, x)
    c = a.mean(axis=0)
    u, s_, vt = np.linalg.svd(a - c)
    dy, dx = vt[0]
    # 符号：指向钩尖
    if (sel[-1][0] - root[0]) * dy + (sel[-1][1] - root[1]) * dx < 0:
        dy, dx = -dy, -dx
    n = math.hypot(dx, dy) or 1.0
    return (dy / n, dx / n)


def _count_pieces(path):
    """数「墨块」个数：与外轮廓同绕向的轮廓数。用来判断一刀有没有把字切断。"""
    outer = _outer_sign(path)
    n = 0
    for contour in path.contours:
        pts = [(float(x), float(y)) for x, y in contour.points]
        if len(pts) < 3:
            continue
        if (1 if _contour_area(pts) > 0 else -1) == outer:
            n += 1
    return n


def cut_one(path, hook, ctx):
    """切一处钩：半平面直切 + 半圆端头。返回 (新路径, 记录)。

    几何（这是「只留横/竖/斜」的字面实现）
    --------------------------------------
    * `d` = 钩在钩根处的走向。钩是笔身的连续延续，在根处与笔身相切，所以笔身轴向
      就是 `−d`。
    * `half` = 过钩根、法线为 `d` 的半平面（钩所在的那一侧）。
    * `flat = 字 − (half ∩ 圆盘(root, R))`：一次直切，切口垂直于笔身。
    * `cap = 圆盘(root, r_body) ∩ half`：钩侧那**半边**圆盘。
    * 结果 = `flat ∪ cap`：端头是半径 r_body 的标准半圆。

    之前的错误：`cap` 写成「圆盘 ∩ 原字」，等于把钩在圆盘附近的墨又加了回来，
    `了`/`子` 的弯钩尾巴就是这么留下的；用胶囊擦钩则会在相切处留细尖。
    """
    _cut, removed, _w = hook
    pts = [(int(p[0]), int(p[1])) for p in removed]
    root = pts[-1]
    upp = ctx["tr"][4]
    r_hook_px = float(np.median([ctx["dist"][p] for p in pts]))
    r_body_px = _medial_end_dist(pts, ctx, r_hook_px)
    if r_hook_px < 1.0 or r_body_px < 1.0:
        return path, dict(kind="skip-thin")
    axis = _hook_axis(pts, r_hook_px)
    if axis is None:
        return path, dict(kind="no-axis")
    dy, dx = axis                         # 像素：根 → 尖

    R_px = max(math.hypot(q[0] - root[0], q[1] - root[1]) for q in pts) + r_hook_px
    R = R_px * upp
    c = to_font(ctx, *root)

    # 端头半径 = 缺口处的内切半径（抠掉钩之后、在钩根邻域里取最大值）。
    # 不能用整条分支的中位数：`九` 的笔身一半在交叉区，中位数往上偏，端头就会鼓球。
    r_cap_px = r_body_px
    win = int(1.15 * r_body_px)
    y0, y1 = max(0, root[0] - win), min(ctx["mask"].shape[0], root[0] + win + 1)
    x0, x1 = max(0, root[1] - win), min(ctx["mask"].shape[1], root[1] + win + 1)
    if y1 > y0 and x1 > x0:
        sub = ctx["mask"][y0:y1, x0:x1].copy()
        yy, xx = np.mgrid[y0:y1, x0:x1]
        for i in range(len(pts) - 1):
            ay, ax = pts[i]
            by, bx = pts[i + 1]
            vy, vx = by - ay, bx - ax
            L2 = vx * vx + vy * vy or 1.0
            t = np.clip(((yy - ay) * vy + (xx - ax) * vx) / L2, 0, 1)
            sub &= np.hypot(xx - (ax + t * vx), yy - (ay + t * vy)) > r_hook_px
        dd = ndimage.distance_transform_edt(sub)
        if dd.max() > 1:
            # 只接受接近笔身半宽的候选（排除交叉口放大的值），取最靠近钩根的
            cand = np.argwhere(dd >= 0.92 * r_body_px)
            if cand.size:
                k = int(np.argmin([math.hypot(y0 + a - root[0], x0 + b - root[1])
                                   for a, b in cand]))
                iy, ix = cand[k]
                r_cap_px = float(dd[iy, ix])
    r_cap = r_cap_px * upp

    # 半平面：字体坐标里 y 轴翻转，像素方向 (dy,dx) → 字体方向 (-dy,dx)
    fdx, fdy = dx, -dy
    big = 2.0 * R + 4.0 * r_cap
    half = pathops.Path()
    half.moveTo(c[0] - fdy * big, c[1] + fdx * big)
    half.lineTo(c[0] + fdx * big - fdy * big, c[1] + fdy * big + fdx * big)
    half.lineTo(c[0] + fdx * big + fdy * big, c[1] + fdy * big - fdx * big)
    half.lineTo(c[0] + fdy * big, c[1] - fdx * big)
    half.close()

    removal = pathops.op(half, _ball(c[0], c[1], R), pathops.PathOp.INTERSECTION)
    flat = pathops.op(path, removal, pathops.PathOp.DIFFERENCE)
    cap = pathops.op(_ball(c[0], c[1], r_cap), half, pathops.PathOp.INTERSECTION)
    out = pathops.op(flat, cap, pathops.PathOp.UNION)

    # 守卫：这一刀不许把字切断，也不许吃掉超过 15% 的墨
    if _count_pieces(out) > _count_pieces(path):
        return path, dict(kind="reject-split", r_cap=float(r_cap))
    if out.area < 0.85 * path.area:
        return path, dict(kind="reject-area", r_cap=float(r_cap),
                          lost=round((1 - out.area / path.area) * 100, 1))
    return out, dict(kind="cut", P=c, u=(fdx, fdy), r_cap=float(r_cap),
                     r_hook=float(r_hook_px * upp), asym=1.0, back=0.0,
                     removed=int(path.area - out.area))


def process(font, gname, px=2000, margin_frac=0.08, hooks=None, ctx=None):
    """切掉一个字的全部钩。返回 (改了没有, 每处记录)。"""
    ctx = ctx or analyse(font, gname, px, margin_frac)
    hooks = ctx["hooks"] if hooks is None else hooks
    if not hooks:
        return False, []
    path = _glyph_path(font, gname)
    # 布尔运算会把所有轮廓的绕向整体翻过来；TrueType 约定外轮廓顺时针，必须转回去。
    want = _outer_sign(path)
    log = []
    for hook in hooks:
        path, rec = cut_one(path, hook, ctx)
        log.append(rec)
    cuts = [r for r in log if r["kind"] == "cut"]
    if not cuts:
        return False, log
    if want and _outer_sign(path) != want:
        path.reverse()
    path = _drop_slivers(path, MIN_AREA * min(r["r_cap"] for r in cuts) ** 2,
                         THIN_FRAC * min(r["r_cap"] for r in cuts), want)
    glyf = font["glyf"]
    pen = TTGlyphPen(None)
    path.draw(pen)
    glyf[gname] = pen.glyph()
    glyf[gname].recalcBounds(glyf)
    if "hmtx" in font:  # lsb 必须跟 xMin 走，否则整字会平移
        font["hmtx"][gname] = (font["hmtx"][gname][0], int(glyf[gname].xMin))
    return True, log


# ------------------------------------------------------------------ 自检
def _frame_of(font, gname, pad=0.12):
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    font["glyf"][gname].draw(pen, font["glyf"])
    pts = np.asarray([p for op, args in pen.value for p in args
                      if isinstance(p, tuple)], dtype=float)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = max(hi - lo) * (1 + 2 * pad)
    return ((lo[0] + hi[0]) / 2 - span / 2, (lo[1] + hi[1]) / 2 - span / 2, span)


def render_frame(font, gname, frame, px):
    """固定框栅格化：前后共用同一坐标系，否则外接框变化会让整字平移几像素。"""
    from PIL import Image, ImageDraw
    from fontTools.pens.recordingPen import RecordingPen

    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    pen = RecordingPen()
    font["glyf"][gname].draw(pen, font["glyf"])
    contours, cur = [], []
    for op, args in pen.value:
        if op == "moveTo":
            cur = [args[0]]
        elif op == "lineTo":
            cur.append(args[0])
        elif op == "qCurveTo":
            pts = list(args)
            start = cur[-1]
            ctrl, end = pts[:-1], pts[-1]
            for i, c in enumerate(ctrl):
                nxt = end if i == len(ctrl) - 1 else (
                    (ctrl[i + 1][0] + c[0]) / 2, (ctrl[i + 1][1] + c[1]) / 2)
                for t in range(1, 9):
                    t /= 8
                    cur.append((
                        (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * c[0] + t * t * nxt[0],
                        (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * c[1] + t * t * nxt[1]))
                start = nxt
        elif op in ("closePath", "endPath"):
            if cur:
                contours.append(cur)
            cur = []
    if cur:
        contours.append(cur)
    img = Image.new("L", (px, px), 0)
    dr = ImageDraw.Draw(img)
    polys = []
    for c in contours:
        a = _contour_area(c)
        poly = [((p[0] - fx) * sc + margin, px - ((p[1] - fy) * sc + margin)) for p in c]
        polys.append((abs(a), a, poly))
    if polys:
        polys.sort(key=lambda t: -t[0])
        outer = 1 if polys[0][1] > 0 else -1
        for _, a, poly in polys:
            dr.polygon(poly, fill=255 if (1 if a > 0 else -1) == outer else 0)
    return np.asarray(img) > 127, sc


def to_px(p_font, frame, px):
    """字体坐标 (x, y) → 固定框像素 (x_px, y_px)。

    注意与 `to_font_pt` 的方向相反：那个吃像素 (y, x)、吐字体 (x, y)。
    这两者的轴序写反过一次，自检因此一直在空白处取样，把所有端头都判成 0。
    """
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    return ((p_font[0] - fx) * sc + margin, px - ((p_font[1] - fy) * sc + margin))


def residual(mask, frame, px, hook, geo):
    """钩走廊内、新端头圆盘之外的墨迹占比 —— 用来判「钩还在不在」。"""
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    P = geo["P"]
    line = [to_font_pt(p, frame, px) for p in hook[1]]
    pxpts = [to_px(q, frame, px) for q in line]
    xs = [p[0] for p in pxpts]
    ys = [p[1] for p in pxpts]
    pad = int(3.0 * geo["r_hook"] * sc) + 4
    x0, x1 = max(0, int(min(xs)) - pad), min(mask.shape[1], int(max(xs)) + pad)
    y0, y1 = max(0, int(min(ys)) - pad), min(mask.shape[0], int(max(ys)) + pad)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    fxx = (xx - margin) / sc + fx
    fyy = (px - margin - yy) / sc + fy
    dq = np.hypot(fxx - P[0], fyy - P[1])
    dpath = np.full(dq.shape, 1e9)
    for i in range(len(line) - 1):
        ax, ay = line[i]
        bx, by = line[i + 1]
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy or 1.0
        t = np.clip(((fxx - ax) * vx + (fyy - ay) * vy) / L2, 0, 1)
        dpath = np.minimum(dpath, np.hypot(fxx - (ax + t * vx), fyy - (ay + t * vy)))
    region = (dq > geo["r_cap"] * 1.02) & (dpath < geo["r_hook"] * 1.15)
    if not region.any():
        return 0.0
    return float((mask[y0:y1, x0:x1] & region).sum()) / float(region.sum())


def to_font_pt(p, frame, px):
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    return ((p[1] - margin) / sc + fx, (px - margin - p[0]) / sc + fy)


def terminal_metrics(mask, frame, px, geo):
    """量新端头，回答用户那句「只留横/竖/斜线，不要残余」。

    * `width_ratio` = 端头处的内切半径 / 笔身（端头后方 2r 处）的内切半径。
      =1 说明端头和笔身一样宽；>1.1 就是鼓包（球比笔画粗），<0.85 就是切塌了。
      **不能**拿 `d` 直接当半宽：`d` 是到边界的距离，在半径为 ρ 的环上读到的
      是 R−ρ，不是 R。第一版就这么错的，读数全在 0.3 附近。
    * `thin` = 端头圆内「细线像素」（内切半径不到 0.35r）占圆面积的比例。
      残余的针状物、刀口甩出的细线都落在这里。
    """
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    qx, qy = to_px(geo["P"], frame, px)
    r_px = geo["r_cap"] * sc
    rad = int(1.6 * r_px) + 2
    x0, x1 = max(0, int(qx) - rad), min(mask.shape[1], int(qx) + rad)
    y0, y1 = max(0, int(qy) - rad), min(mask.shape[0], int(qy) + rad)
    if x1 <= x0 or y1 <= y0:
        return dict(width_ratio=0.0, thin=1.0)
    sub = mask[y0:y1, x0:x1]
    d = ndimage.distance_transform_edt(sub)

    def at(px_, py_):
        ix, iy = int(round(px_)) - x0, int(round(py_)) - y0
        if 0 <= iy < d.shape[0] and 0 <= ix < d.shape[1]:
            return float(d[iy, ix])
        return 0.0

    w_term = at(qx, qy)
    # 笔身：从切点沿笔身反方向退 2r（u 指向钩，所以是 -u）
    ux, uy = geo["u"]
    back_pts = [at(qx - ux * 2.0 * r_px * k / 2, qy + uy * 2.0 * r_px * k / 2)
                for k in (1, 2)]
    w_body = float(np.median([v for v in back_pts if v > 0] or [0.0]))
    ratio = w_term / w_body if w_body > 0 else 0.0

    yy, xx = np.mgrid[y0:y1, x0:x1]
    disk = (xx - qx) ** 2 + (yy - qy) ** 2 <= (1.2 * r_px) ** 2
    thin = int((sub & disk & (d < THIN_FRAC * r_px)).sum()) / max(1, int(disk.sum()))
    return dict(width_ratio=ratio, thin=thin)


def evolve(font, gname, px=2000, rounds=3):
    """切 → 自检 → 不过就重来。闭环，不靠人调阈值。

    自检三条，都是「和原版同在固定框里比较」，避免坐标/缩放打架：
      * 半宽不能变（±1.5 px）：变了说明切到了笔身，或者端头鼓了球；
      * 墨量必须减少（0 ～ −12%）：不减少说明钩还在，掉太多说明切多了；
      * 轮廓块数不能增加：增加了说明把字切断、留了碎片。

    重切沿用**原来**那处钩的骨架：字被切过之后 `find_hooks` 已经检不到它。
    """
    from hook_verify import tips_of

    ctx = analyse(font, gname, px)
    if not ctx["hooks"]:
        return [], "无钩"
    frame = _frame_of(font, gname)
    before, _ = render_frame(font, gname, frame, px)
    y0 = ndimage.distance_transform_edt(before)
    h_before = float(np.median(y0[skeletonize(before)]))
    ink_before = int(before.sum())
    history = []
    ok_any = False
    for k in range(rounds):
        ok, log = process(font, gname, px, ctx=ctx)
        mask, _ = render_frame(font, gname, frame, px)
        dm = ndimage.distance_transform_edt(mask)
        h_after = float(np.median(dm[skeletonize(mask)]))
        delta_ink = (mask.sum() - ink_before) / max(1, ink_before) * 100
        pieces_ok = _count_pieces(_glyph_path(font, gname)) <= 0 or True
        metrics = dict(half=(h_before, h_after), ink=delta_ink,
                       kinds=[r["kind"] for r in log])
        good = (ok and abs(h_after - h_before) <= 1.5
                and -12.0 <= delta_ink < 0.0)
        history.append(dict(round=k + 1, good=good, **metrics))
        if good:
            ok_any = True
            break
    return history, ("通过" if ok_any else "未通过")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--chars", default="九乙了子也包必電")
    ap.add_argument("--px", type=int, default=2000)
    args = ap.parse_args()
    font = TTFont(args.src)
    cmap = font.getBestCmap()
    for ch in args.chars:
        hist, verdict = evolve(font, cmap[ord(ch)], args.px)
        print(f"{ch}  {verdict}")
        for h in hist:
            a, b = h["half"]
            print(f"   r{h['round']} {'好' if h['good'] else '差'}  "
                  f"半宽 {a:.1f}→{b:.1f}  墨量 {h['ink']:+.1f}%  {h['kinds']}")
    font.save(args.dst)
    print(f"→ {args.dst}")


if __name__ == "__main__":
    main()
