"""按骨架重画笔端：钩整条去掉，端头落成半径 = 半笔宽的标准半圆。

背景（为什么推倒重来）
----------------------
`hook_taper` 那一套是「在轮廓上找两个点 S/E，删掉它们之间那段弧」。这条路走了五版，
每一版都栽在同一处：S/E 的定位、方向、短弧选择、跨轮廓、配对闸……二十个阈值互相
牵制，改一处坏两处。`process` 报 `ok`、IoU 微涨，而**钩一个都没去掉**——
差分图里八个字的钩全在原处，刀子只在端头削掉一千来个像素。

根因不是参数没调好，是方法选错了：轮廓点序是这件事最脆弱的表示。

本版的做法
----------
对**填充区域**做布尔运算，不碰任何点序：

1. 钩骨架 `removed`（`hook_erase` 给）转字体坐标；`removed[0]` 是钩尖、`[-1]` 是钩根。
2. 从钩根沿**最长**的骨架分支往外取笔身方向 u（不能用最近点：钩根常落在交叉点，
   最近点可能属于另一条笔画，切平面会横穿整字）。
3. 切除区 =（过钩根、垂直 u 的半平面）∩ 球(Q, 3.6r) ∪ 钩走廊。
4. 字 = 字 − 切除区；再 ∪ 圆盘(Q, r_cap)。

第 4 步的圆盘是**设计规则**不是补丁：Maruko 的自由端头就是半圆，半径 = 该笔半宽
（`docs/design-principles.md`：398 个端头 d_min/r 中位 1.01，55% 整半圆）。
切平面是直切，圆盘内切于切口，两边相切——不会长出脓包，也不留接缝。

速度：一个字形一轮栅格化（0.7 s）+ 每钩 3 次布尔运算（~0.1 s）。

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

WINDOW = 3.6     # 切除区半径，单位 r（钩长实测 3.1–3.7r）
MIN_AREA = 0.25  # 面积小于 MIN_AREA·r² 的碎片丢掉
RESID_MAX = 0.15  # 钩走廊内、新端头之外的墨迹占比上限
BLISTER_MAX = 1.25  # 端头处最大内切半径 / 设计半径 的上限（超过就是脓包）


# ---------------------------------------------------------------- 几何工具
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
    """Ramer–Douglas–Peucker。骨架是逐像素的，156 个点 stroke 出来上千段曲线，
    容差 0.1r 降到十几个点，形状差 < 0.1r。"""
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


def _outer_sign(path):
    best = None
    for contour in path.contours:
        pts = [(float(x), float(y)) for x, y in contour.points]
        if len(pts) < 3:
            continue
        a = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts))) / 2
        if best is None or abs(a) > abs(best):
            best = a
    return 0 if best is None else (1 if best > 0 else -1)


def _drop_slivers(path, min_area):
    out = pathops.Path()
    for contour in path.contours:
        pts = [(float(x), float(y)) for x, y in contour.points]
        if len(pts) < 3:
            continue
        a = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                    - pts[(i + 1) % len(pts)][0] * pts[i][1]
                    for i in range(len(pts)))) / 2
        if a >= min_area:
            out.addPath(contour)
    return out


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
    node = far
    while prev.get(node) is not None and dists[node] > min_len:
        node = prev[node]
    path = [node]
    while path[-1] != root:
        path.append(prev[path[-1]])
    return list(reversed(path))


# ---------------------------------------------------------------- 栅格上下文
def analyse(font, gname, px=2000, margin_frac=0.08):
    mask, tr = raster_mask(font, gname, px, margin_frac)
    dist = ndimage.distance_transform_edt(mask)
    sk = skeletonize(mask)
    return dict(mask=mask, sk=sk, dist=dist, tr=tr, px=px,
                hooks=raster_hooks(mask, sk, dist))


def to_font(ctx, y, x):
    xmin, ymin, _scale, margin, upp, _sign = ctx["tr"]
    px = ctx["px"]
    return (xmin + (x - margin) * upp, ymin + (px - margin - y) * upp)


# ---------------------------------------------------------------- 单个钩
def cut_one(path, hook, ctx, scale=1.0):
    """从一个字形路径上切掉一处钩。返回 (新路径, 记录)。"""
    _cut, removed, _w = hook
    pts_px = [(int(p[0]), int(p[1])) for p in removed]
    if len(pts_px) < 4:
        return path, dict(kind="too-short")
    # `hook_erase` 两条规则都保证 removed[0] = 钩尖、removed[-1] = 钩根。
    # 不要按骨架度数猜方向：`了`/`子` 的 removed[0] 在骨架外一格（度数 0），
    # 一猜就会把方向和根部圆盘装反，走廊捅进笔身。
    root_px, tip_px = pts_px[-1], pts_px[0]
    banned = set(pts_px)
    dist, sk = ctx["dist"], ctx["sk"]
    upp = ctx["tr"][4]
    Q = to_font(ctx, *root_px)
    r_hook = float(np.median([dist[p] for p in pts_px])) * upp * scale
    if r_hook < 3:
        return path, dict(kind="skip-thin", r_hook=r_hook)

    branch = _longest_branch(root_px, banned, sk, 4.0 * r_hook / upp)
    if not branch:
        return path, dict(kind="no-body")
    # 笔身半宽不能用钩根处的距离变换：钩根落在交叉点上时，内切圆的半径是两条笔
    # 画并集的半径，比任何一条都粗（`九` 因此套上一个比笔身还大的球）。改用笔身
    # 分支上的**中位数**，交叉点只占少数几个像素。
    rt = [float(dist[p]) for p in branch] or [dist[root_px]]
    r_cap = float(np.median(rt)) * upp * scale
    if r_cap < 3:
        r_cap = r_hook
    B_px = branch[min(len(branch) - 1, max(1, int(1.5 * r_cap / upp)))]
    B = to_font(ctx, *B_px)

    ux, uy = Q[0] - B[0], Q[1] - B[1]
    n = math.hypot(ux, uy) or 1.0
    ux, uy = ux / n, uy / n
    px_, py_ = -uy, ux
    R = WINDOW * r_cap
    half = pathops.Path()
    half.moveTo(Q[0] - px_ * R, Q[1] - py_ * R)
    half.lineTo(Q[0] + ux * R - px_ * R, Q[1] + uy * R - py_ * R)
    half.lineTo(Q[0] + ux * R + px_ * R, Q[1] + uy * R + py_ * R)
    half.lineTo(Q[0] + px_ * R, Q[1] + py_ * R)
    half.close()
    half = pathops.op(half, _ball(Q[0], Q[1], R), pathops.PathOp.INTERSECTION)

    line = _rdp([Q] + [to_font(ctx, *p) for p in reversed(pts_px[:-1])],
                0.10 * r_hook)
    corridor = _polyline_path(line)
    corridor.stroke(2 * min(r_hook, r_cap), pathops.LineCap.ROUND_CAP,
                    pathops.LineJoin.ROUND_JOIN, 4)
    corridor.convertConicsToQuads()
    removal = pathops.op(half, corridor, pathops.PathOp.UNION)

    before = path.area
    out = pathops.op(path, removal, pathops.PathOp.DIFFERENCE)
    # 端头：以钩根为圆心、半径 = 笔身半宽的圆盘。切平面是直切，圆盘内切于切口。
    # 只并回**原字形本来就有的墨**（disk ∩ path）：钩根落在交叉点时 r_cap 会偏大，
    # 无条件并集会凸出一个球（`乙` 墨量 +2.6%、`電` +3.8%）。这条约束保证结果
    # 永远是原字形的子集，绝不会无中生有。
    cap = pathops.op(_ball(Q[0], Q[1], r_cap), path, pathops.PathOp.INTERSECTION)
    out = pathops.op(out, cap, pathops.PathOp.UNION)
    out = _drop_slivers(out, MIN_AREA * r_cap * r_cap)
    return out, dict(kind="cut", root=(float(Q[0]), float(Q[1])),
                     r_cap=float(r_cap), r_hook=float(r_hook),
                     removed=int(before - out.area), before=float(before))


def process(font, gname, px=2000, margin_frac=0.08, scale=1.0, hooks=None, ctx=None):
    """切掉一个字的全部钩。返回 (改了没有, 每处钩的记录)。"""
    ctx = ctx or analyse(font, gname, px, margin_frac)
    hooks = ctx["hooks"] if hooks is None else hooks
    if not hooks:
        return False, []
    path = _glyph_path(font, gname)
    # 布尔运算会把所有轮廓的绕向整体翻过来。TrueType 约定外轮廓顺时针（y 向上时
    # 有向面积为负），翻过来的字在部分光栅器上内白会被填实——必须转回去。
    want_sign = _outer_sign(path)
    log = []
    for hook in hooks:
        path, rec = cut_one(path, hook, ctx, scale=scale)
        log.append(rec)
    if not any(r["kind"] == "cut" for r in log):
        return False, log
    if _outer_sign(path) != want_sign and want_sign != 0:
        path.reverse()
    glyf = font["glyf"]
    pen = TTGlyphPen(None)
    path.draw(pen)
    glyf[gname] = pen.glyph()
    glyf[gname].recalcBounds(glyf)
    if "hmtx" in font:  # lsb 必须跟 xMin 走，否则整字会平移
        font["hmtx"][gname] = (font["hmtx"][gname][0], int(glyf[gname].xMin))
    return True, log


# ---------------------------------------------------------------- 自检
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
                nxt = end if i == len(ctrl) - 1 else ((ctrl[i + 1][0] + c[0]) / 2,
                                                       (ctrl[i + 1][1] + c[1]) / 2)
                for t in range(1, 9):
                    t /= 8
                    cur.append(((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * c[0] + t * t * nxt[0],
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
        a = sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1]
                for i in range(len(c))) / 2
        poly = [((p[0] - fx) * sc + margin, px - ((p[1] - fy) * sc + margin)) for p in c]
        polys.append((abs(a), a, poly))
    polys.sort(key=lambda t: -t[0])
    outer_sign = 1 if polys[0][1] > 0 else -1
    # 内白必须挖掉：TrueType 用相反绕向表示洞，一律填实会把 `包`/`電` 的封闭内白糊成实心
    for _, a, poly in polys:
        dr.polygon(poly, fill=255 if (1 if a > 0 else -1) == outer_sign else 0)
    return np.asarray(img) > 127, sc


def residual(mask, frame, px, hook, geo):
    """钩走廊内、新端头圆盘之外的墨迹占比。

    不用「旧钩尖的球必须空」：`乙` 的钩半宽只有 14，笔身半宽 32，半径 32 的端头
    圆盘必然盖住旧钩尖，那个球永远不可能空。要问的是「钩还剩多少」——沿原钩骨架、
    半径 = 钩半宽的走廊，扣掉端头圆盘，剩下的墨就是残留。
    """
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    Q = geo["root"]
    line = [(x, y) for _, x, y in
            [(0, *to_font_pt(p, frame, px)) for p in hook[1]]]
    xs = [(p[0] - fx) * sc + margin for p in line]
    ys = [px - ((p[1] - fy) * sc + margin) for p in line]
    pad = int(3.0 * geo["r_hook"] * sc) + 4
    x0, x1 = max(0, int(min(xs)) - pad), min(mask.shape[1], int(max(xs)) + pad)
    y0, y1 = max(0, int(min(ys)) - pad), min(mask.shape[0], int(max(ys)) + pad)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    fxx = (xx - margin) / sc + fx
    fyy = (px - margin - yy) / sc + fy
    dq = np.hypot(fxx - Q[0], fyy - Q[1])
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


def terminal_check(mask, frame, px, geo):
    """端头是否凸出：新的端头是以钩根为圆心、半径 r_cap 的圆，若该处最大内切
    半径明显大于 r_cap，说明圆盘比笔画粗——就是「贴了个球」。

    这个量必须进自检：`residual` 只问「钩还在不在」，不问「端头好不好看」。
    前几版正是只盯着钩，才把脓包当成成功。
    """
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    Q = geo["root"]
    qx = (Q[0] - fx) * sc + margin
    qy = px - ((Q[1] - fy) * sc + margin)
    r_px = geo["r_cap"] * sc
    rad = int(1.6 * r_px) + 2
    x0, x1 = max(0, int(qx) - rad), min(mask.shape[1], int(qx) + rad)
    y0, y1 = max(0, int(qy) - rad), min(mask.shape[0], int(qy) + rad)
    if x1 <= x0 or y1 <= y0:
        return 1.0
    sub = mask[y0:y1, x0:x1]
    d = ndimage.distance_transform_edt(sub)
    return float(d.max() / max(r_px, 1e-6))


def to_font_pt(p, frame, px):
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    return ((p[1] - margin) / sc + fx, (px - margin - p[0]) / sc + fy)


def evolve(font, gname, px=2000, rounds=3):
    """切 → 自检 → 不过就加大参数**重切那一处**。闭环，不是人调阈值。

    重切必须沿用**原来**那处钩的骨架：字被切过之后 `find_hooks` 已经检不到它，
    重新检测等于什么都没做（第一版就这样，三轮读数一模一样）。
    """
    ctx = analyse(font, gname, px)
    if not ctx["hooks"]:
        return [], "无钩"
    frame = _frame_of(font, gname)
    state = [dict(hook=h, scale=1.0, done=False, geo=None) for h in ctx["hooks"]]
    history = []
    for k in range(rounds):
        for st in state:
            if st["done"]:
                continue
            ok, log = process(font, gname, px, scale=st["scale"],
                              hooks=[st["hook"]], ctx=ctx)
            st["geo"] = next((r for r in log if r["kind"] == "cut"), st["geo"])
        mask, sc = render_frame(font, gname, frame, px)
        for st in state:
            if st["geo"] is None:
                st["done"] = True
                st["res"] = 1.0
                continue
            st["res"] = residual(mask, frame, px, st["hook"], st["geo"])
            st["blister"] = terminal_check(mask, frame, px, st["geo"])
            st["done"] = (st["res"] <= RESID_MAX
                          and st["blister"] <= BLISTER_MAX)
        bad = [s for s in state if not s["done"]]
        history.append(dict(round=k + 1, bad=len(bad),
                            res=[round(s.get("res", 1.0), 2) for s in state],
                            blister=[round(s.get("blister", 1.0), 2) for s in state]))
        if not bad:
            break
        for s in bad:
            s["scale"] *= 0.88  # 端头凸出就收半径；钩还在就靠下一轮重切
    return history, ("通过" if not bad else f"仍有 {len(bad)} 处")


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
        print(f"{ch}  {verdict}  " +
              " ".join(f"r{h['round']}:{h['bad']}处{h['res']}" for h in hist))
    font.save(args.dst)
    print(f"→ {args.dst}")


if __name__ == "__main__":
    main()
