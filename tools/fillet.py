"""凹角补圆：生成补丁环，并在生成时用三条判据把关（2026-11-01 主人定）。

补丁 = 一段圆弧围成的多边形环（顶点 C → 切点 T1 → 弧 → 切点 T2）。应用时由
`cjk_vf.build_vf` 追加到该字的环列表末尾，`design_cjk` 的笔画环一条都不改——所以笔宽、
端头、字面高度一个数都不动。

**三条判据（半径只作记录，不作门槛）**

1. **相切角 ≤1°**：弧与相邻直边相切。量法是「圆心到直边的垂距 = 半径」，差多少除以半径
   就是夹角：`asin(|dist-R|/R)`。
2. **切线长 ≤ 直段 80%**：切线长 `t = R / tan(θ/2)`，直段按 **10° 容差**量。容差不能取
   1.5°：笔画本身带一点弧度，容差一紧就在弧起处碎成短段（2026-11-01 实测同一条撇
   1.5° 量出 31.1、10° 量出 69.7，差 2.2 倍），结论会从「做得到」翻成「做不到」。
3. **角外 60 单位位移 0**：补丁只许动角，动到直边就是填错了地方。用量法验：
   改前改后各栅格一次，异或出来的像素全部落在角点 60 单位以内。

三条都是可跑的数，不是形容词。生成时判据 2 不过直接拒绝出补丁；判据 1、3 在
`--verify` 里对**出件后的字体**再量一遍（不是拿生成时的几何自证）。

三条构造约束（踩出来的，不是审美）：

1. **绕向必须与笔画环一致（−1）**。nonzero 填充下同向重叠处 −1 + −1 = −2 仍是墨；反向
   （+1）在重叠处抵消成 0，渲染出一道发丝白缝，看起来比原来更尖。
2. **弧必须鼓向空气侧**。反了就是弧穿进墨里，出来一个逗号。
3. **圆心取平分线上「空气那一侧」**那个候选，**顶点内移 4 单位**（`C_in = C − w·4`）：
   栅格边界比真边缘略靠外，顶点留原位会留一道发丝缝。

用法：

    # 生成补丁（角点从 corner_probe.py 量，改前字体上量一次）；--radius auto 按判据 2 取
    .venv/bin/python tools/fillet.py --font build/metrics/before1/preview.ttf \\
        --char 篱 --at 346,710 --at 738,703 --radius auto --json tools/fillet_patches.json

    # 出件后验收：半径/残差、相切角、直段、切线长占比、角外位移
    .venv/bin/python tools/fillet.py --verify build/metrics/after1/preview.ttf \\
        --base build/metrics/before1/preview.ttf --char 篱 --at 346,710 --at 738,703
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import corner_scan as cs

# ---- 三条判据的门槛（改这里等于改验收线，CHANGELOG 里要写） ----
TOL_DEG = 10.0        # 量直段的容差；不要改成 1.5°，理由见文件头
TANGENT_MAX = 0.80    # 切线长占直段的上限
ANGLE_MAX = 1.0       # 相切角上限（度）
FAR = 60.0            # 角外 60 单位内允许动，之外位移必须为 0
LINE_TOL = 0.75       # 栅格边界噪声（1024 px/em 下 0.5 px = 0.49 单位）
RADIUS_CAP = 40.0     # --radius auto 的上限：再大就不像「补圆」而像「挖圆」


# ---------------------------------------------------------------- 几何

def kasa(P: np.ndarray):
    """Kasa 圆拟合：返回圆心、半径、最大残差。"""
    A = np.column_stack([2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))])
    sol, *_ = np.linalg.lstsq(A, (P ** 2).sum(1), rcond=None)
    cx, cy, c = sol
    R = math.sqrt(c + cx * cx + cy * cy)
    res = np.abs(np.linalg.norm(P - [cx, cy], axis=1) - R)
    return np.array([cx, cy]), float(R), float(res.max())


def edge_line(Q: np.ndarray, C: np.ndarray, ref: np.ndarray, dmax: float = 220.0):
    """沿 ref 取轮廓点，迭代内点拟合直边；返回 (点均值, 单位方向, 残差)。"""
    R = Q - C
    s = R @ ref
    d = np.abs(R @ np.array([-ref[1], ref[0]]))
    P = Q[(s > 12) & (s < dmax) & (d < 3)]
    if len(P) < 10:
        raise SystemExit("直边上取不到点，角点或窗口给错了")
    dirv = ref
    for _ in range(6):
        c = P.mean(0)
        _u, _sv, vt = np.linalg.svd(P - c)
        dirv = vt[0] if vt[0] @ ref > 0 else -vt[0]
        keep = np.abs((P - c) @ np.array([-dirv[1], dirv[0]])) < LINE_TOL
        if keep.sum() < 10:
            break
        P = P[keep]
    c = P.mean(0)
    _u, _sv, vt = np.linalg.svd(P - c)
    dirv = vt[0] if vt[0] @ ref > 0 else -vt[0]
    resid = np.abs((P - c) @ np.array([-dirv[1], dirv[0]]))
    return c, dirv, float(resid.max())


def straight_run(Q: np.ndarray, C: np.ndarray, c: np.ndarray, dirv: np.ndarray,
                 tol_deg: float = TOL_DEG, dmax: float = 300.0, s0: float = 20.0) -> float:
    """从角点量到头那条直边有多长。

    做法：沿轮廓把每个点的「沿边投影 s」与「到直边垂距 d」都算出来，从 s0（=20 单位，
    已经越过原有圆角，r≈15 时 20 单位外一定回到直边）往外看，找出**最远**的 s，使
    「从第一个合格点到这里」整段都满足 `d ≤ max(LINE_TOL, s·sin(tol))`。

    为什么从 s0 起：角点附近本来就是一小段弧，弧上的点离开直边延线 1–3 单位，那不属于
    「直段弯了」。把这一段算进去，1.5° 容差会在 s=9 就判停，量出来 8.2 单位——比 1.5°
    更松的 10° 反倒量得更短的怪数就是这么来的。
    """
    n = len(Q)
    i = int(np.argmin(np.linalg.norm(Q - C, axis=1)))
    normal = np.array([-dirv[1], dirv[0]])
    lim = math.sin(math.radians(tol_deg))
    best = 0.0
    for step in (-1, 1):
        ok_started = False
        j = i
        while True:
            j = (j + step) % n
            R = Q[j] - C
            s = float(R @ dirv)
            d = abs(float(R @ normal))
            if s <= 0 or s > dmax:
                break
            good = d <= max(LINE_TOL, s * lim)
            if s >= s0 and good:
                ok_started = True
                best = max(best, s)
            elif ok_started and not good:
                break
            j0 = (j - i) % n
            if j0 == 0:
                break
    return best


def tangent_angle(O: np.ndarray, R: float, c: np.ndarray, dirv: np.ndarray) -> tuple[float, float]:
    """圆心到直边的垂距与半径差多少 → 夹角（度）。切得好就是 0。"""
    dist = abs(float((O - c) @ np.array([-dirv[1], dirv[0]])))
    diff = abs(dist - R)
    return math.degrees(math.asin(min(1.0, diff / R))), dist


# ---------------------------------------------------------------- 生成

def _side_points(Q, seed, step, d0, d1):
    i = int(np.argmin(np.linalg.norm(Q - np.asarray(seed, float), axis=1)))
    n = len(Q)
    pts, acc, j = [], 0.0, i
    while acc < d1:
        j2 = (j + step) % n
        acc += float(np.linalg.norm(Q[j2] - Q[j]))
        j = j2
        if acc >= d0:
            pts.append(Q[j])
    return np.array(pts)


def _fit_line(P):
    c = P.mean(0)
    _u, _s, vt = np.linalg.svd(P - c)
    return c, vt[0]


def patch_for(font_path: Path, ch: str, seed, radius, px_per_em: int = 1024):
    rings, mask, (ox, oy), to_u = cs.boundary(Path(font_path), ch, px_per_em)
    best = None
    for P in rings:
        Q = cs.resample(np.vstack([P, P[:1]]), 1.0)
        if len(Q) < 30:
            continue
        d = float(np.min(np.linalg.norm(Q - np.asarray(seed, float), axis=1)))
        if best is None or d < best[0]:
            best = (d, Q)
    _d, Q = best

    A = _side_points(Q, seed, -1, 16.0, 44.0)
    B = _side_points(Q, seed, +1, 16.0, 44.0)
    ca, da = _fit_line(A)
    cb, db = _fit_line(B)
    C0 = ca + da * np.linalg.solve(np.array([[da[0], -db[0]], [da[1], -db[1]]]), cb - ca)[0]
    u0 = da / np.linalg.norm(da)
    v0 = db / np.linalg.norm(db)
    if u0 @ (A.mean(0) - C0) < 0:
        u0 = -u0
    if v0 @ (B.mean(0) - C0) < 0:
        v0 = -v0

    # 两条边用**内点迭代**拟合（与 --verify 里量相切角用的是同一套），否则切的是 A 线、
    # 量的是 B 线，相切角会凭空多出 1° 以上
    cu, du, _ru = edge_line(Q, C0, u0)
    cv, dv, _rv = edge_line(Q, C0, v0)
    C = cu + du * np.linalg.solve(np.array([[du[0], -dv[0]], [du[1], -dv[1]]]), cv - cu)[0]
    u, v = du, dv
    if u @ (cu - C) < 0:
        u = -u
    if v @ (cv - C) < 0:
        v = -v
    theta = math.acos(max(-1.0, min(1.0, float(u @ v))))
    Lu = straight_run(Q, C, cu, du)
    Lv = straight_run(Q, C, cv, dv)
    Lmin = min(Lu, Lv)
    if radius in (None, "auto"):
        radius = math.floor(Lmin * TANGENT_MAX * math.tan(theta / 2.0) * 10) / 10
        radius = min(radius, RADIUS_CAP)
        auto = True
    else:
        radius = float(radius)
        auto = False
    if Lmin <= 0:
        raise SystemExit(
            f"不可补：角点 {C[0]:.1f},{C[1]:.1f} 有一边量不到直段"
            f"（Lu={Lu:.1f} Lv={Lv:.1f}）——那是弧上的拐点，不是折角。")
    t = radius / math.tan(theta / 2.0)
    ratio = t / Lmin
    if ratio > TANGENT_MAX:
        raise SystemExit(
            f"判据 2 不过：切线长 {t:.1f} 超过直段 {Lmin:.1f} 的 {TANGENT_MAX:.0%}"
            f"（{ratio:.0%}）。半径要 ≤ {Lmin * TANGENT_MAX * math.tan(theta / 2.0):.1f}，"
            f"或用 --radius auto 让判据自己定。")

    def ink(p):
        px = int(round(ox + p[0] / to_u))
        py = int(round(oy - p[1] / to_u))
        return bool(mask[py, px]) if (0 <= py < mask.shape[0] and 0 <= px < mask.shape[1]) else False

    w = u + v
    w /= np.linalg.norm(w)

    def first_ink(direction):
        for step in np.arange(0.5, 80.0, 0.5):
            if ink(C + direction * step):
                return float(step)
        return None

    d1, d2 = first_ink(w), first_ink(-w)
    if d2 is not None and (d1 is None or d2 > d1):
        w = -w

    T1 = C + u * t
    T2 = C + v * t
    O = C + w * (radius / math.sin(theta / 2.0))
    a1 = math.atan2(*(T1 - O)[::-1])
    a2 = math.atan2(*(T2 - O)[::-1])
    da2 = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    mid = (T1 + T2) / 2

    def side(p):
        return (p[0] - mid[0]) * (T2[1] - T1[1]) - (p[1] - mid[1]) * (T2[0] - T1[0])

    arc_mid = np.array([O[0] + radius * math.cos(a1 + da2 / 2), O[1] + radius * math.sin(a1 + da2 / 2)])
    if side(arc_mid) * side(C) < 0:
        da2 -= 2 * math.pi * np.sign(da2)

    seg = 16
    arc = [(float(O[0] + radius * math.cos(a1 + da2 * k / seg)),
            float(O[1] + radius * math.sin(a1 + da2 * k / seg))) for k in range(seg + 1)]
    C_in = C - w * 4.0
    pts = [tuple(C_in), tuple(T1)] + arc[1:-1] + [tuple(T2)]
    area = sum(pts[k][0] * pts[(k + 1) % len(pts)][1] - pts[(k + 1) % len(pts)][0] * pts[k][1]
               for k in range(len(pts)))
    if area > 0:
        pts.reverse()
    return {
        "角点": [round(float(C[0]), 2), round(float(C[1]), 2)],
        "夹角": round(math.degrees(theta), 1),
        "圆心": [round(float(O[0]), 2), round(float(O[1]), 2)],
        "半径": radius,
        "半径来源": "auto（判据 2 反推）" if auto else "指定",
        "直段u": round(Lu, 1),
        "直段v": round(Lv, 1),
        "切线长": round(t, 1),
        "切线长占直段": round(ratio, 3),
        "多边形": [[round(x, 3), round(y, 3)] for x, y in pts],
    }


# ---------------------------------------------------------------- 验收

def render_mask(font_path: Path, ch: str, px_per_em: int):
    """同一原点、同一字号栅格一次；两个字体用同一组 (ox, oy)，异或才有意义。"""
    from PIL import ImageFont
    font = ImageFont.truetype(str(font_path), px_per_em)
    side = int(px_per_em * 1.8)
    ox, oy = int(px_per_em * 0.5), int(px_per_em * 1.4)
    canvas = Image.new("L", (side, side), 255)
    ImageDraw.Draw(canvas).text((ox, oy), ch, font=font, fill=0, anchor="ls")
    return np.asarray(canvas) < 128, ox, oy


def vector_rings(font_path: Path, ch: str) -> list[np.ndarray]:
    """直接从字体文件取轮廓（矢量，不经过栅格）。补丁环是纯 lineTo 的多边形。"""
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont
    font = TTFont(str(font_path))
    glyph = font.getGlyphSet()[font.getBestCmap()[ord(ch)]]
    pen = RecordingPen()
    glyph.draw(pen)
    out, cur = [], None
    for op, args in pen.value:
        if op == "moveTo":
            cur = [args[0]]
        elif op == "lineTo":
            cur.append(args[0])
        elif op == "qCurveTo":
            for a in args[:-1]:
                if a is not None:
                    cur.append(a)
            cur.append(args[-1])
        elif op in ("closePath", "endPath"):
            if cur:
                out.append(np.array(cur, float))
                cur = None
    return out


def _ring_key(c: np.ndarray):
    return (round(float(c[:, 0].mean()), 1), round(float(c[:, 1].mean()), 1), len(c))


def patch_rings(font_after: Path, font_before: Path, ch: str) -> list[np.ndarray]:
    """改后有、改前没有的环 = 补丁环。"""
    after = vector_rings(font_after, ch)
    keys = {_ring_key(c) for c in vector_rings(font_before, ch)}
    return [c for c in after if _ring_key(c) not in keys]


def _raster_contour(font_path: Path, ch: str, seed, px_per_em: int = 4096):
    rings, _mask, _org, _tu = cs.boundary(Path(font_path), ch, px_per_em)
    best = None
    for P in rings:
        Q = cs.resample(np.vstack([P, P[:1]]), 1000.0 / px_per_em)
        if len(Q) < 40:
            continue
        d = float(np.min(np.linalg.norm(Q - np.asarray(seed, float), axis=1)))
        if best is None or d < best[0]:
            best = (d, Q)
    return best[1]


def _corner_refs(Q, seed):
    """从**改前**轮廓取角点与两条边的方向（改后轮廓在角上已经是弧，取不出直边）。"""
    A = _side_points(Q, seed, -1, 16.0, 44.0)
    B = _side_points(Q, seed, +1, 16.0, 44.0)
    ca, da = _fit_line(A)
    cb, db = _fit_line(B)
    C = ca + da * np.linalg.solve(np.array([[da[0], -db[0]], [da[1], -db[1]]]), cb - ca)[0]
    u = da / np.linalg.norm(da)
    v = db / np.linalg.norm(db)
    if u @ (A.mean(0) - C) < 0:
        u = -u
    if v @ (B.mean(0) - C) < 0:
        v = -v
    theta = math.acos(max(-1.0, min(1.0, float(u @ v))))
    return C, u, v, theta


def verify(font_path: Path, base: Path, ch: str, seeds, px_per_em: int = 2048):
    """对**出件后**的字体量三条判据。三个数的来源互不依赖：

    - 半径与相切角：**矢量**轮廓（补丁环整环拟合圆），不经过栅格；
    - 直段与切线长：直边在**改前**栅格轮廓（4096 px/em）上拟合，按 1.5° 与 10° 各量一次；
    - 角外位移：改前改后各栅格一次（2048 px/em），2 像素容差后异或，按 60 单位筛。
    """
    mask_after, ox, oy = render_mask(Path(font_path), ch, px_per_em)
    mask_base, ox2, oy2 = render_mask(Path(base), ch, px_per_em)
    assert (ox, oy) == (ox2, oy2), "两次栅格的原点不一致，异或没有意义"
    # 2 像素容差：反走样阈值抖动会让个别像素翻面，那不是「位移」
    from scipy import ndimage as ndi
    tol_px = 2
    a_d = ndi.binary_dilation(mask_after, iterations=tol_px)
    b_d = ndi.binary_dilation(mask_base, iterations=tol_px)
    added_mask = mask_after & ~b_d
    removed_mask = mask_base & ~a_d
    added, removed = int(added_mask.sum()), int(removed_mask.sum())
    to_u = 1000.0 / px_per_em
    ys, xs = np.nonzero(added_mask | removed_mask)
    far_pts = 0
    if len(xs):
        P = np.column_stack([(xs - ox) * to_u, (oy - ys) * to_u])
        near = np.min(np.linalg.norm(P[:, None, :] - np.asarray(seeds, float)[None, :, :], axis=2), axis=1)
        far_pts = int((near > FAR).sum())
        max_dist = float(near.max())
    else:
        max_dist = 0.0

    rings = patch_rings(Path(font_path), Path(base), ch)
    rows = []
    for seed in seeds:
        ring = min(rings, key=lambda c: np.min(np.linalg.norm(c - np.asarray(seed, float), axis=1)))
        arc = ring[2:-1] if len(ring) > 6 else ring          # [顶点, 切点, 弧…, 切点]
        O, R, kasa_res = kasa(arc)

        Qb = _raster_contour(base, ch, seed)
        C, u, v, theta = _corner_refs(Qb, seed)
        edges = [edge_line(Qb, C, ref) for ref in (u, v)]
        angs, offs = [], []
        for c, d, _r in edges:
            ang, dist = tangent_angle(O, R, c, d)
            angs.append(ang)
            offs.append(abs(dist - R))
        t = R / math.tan(theta / 2.0)
        L15 = min(straight_run(Qb, C, *e[:2], tol_deg=1.5) for e in edges)
        L10 = min(straight_run(Qb, C, *e[:2], tol_deg=10.0) for e in edges)
        rows.append({
            "角点": [float(seed[0]), float(seed[1])],
            "夹角": round(math.degrees(theta), 1),
            "半径": round(R, 2),
            "圆拟合残差": round(kasa_res, 2),
            "相切u": round(angs[0], 2),
            "相切v": round(angs[1], 2),
            "偏心u": round(offs[0], 2),
            "偏心v": round(offs[1], 2),
            "直段1.5": round(L15, 1),
            "直段10": round(L10, 1),
            "切线长": round(t, 1),
            "占比": round(t / L10, 3),
        })
    return rows, far_pts, max_dist, added, removed


def main() -> None:
    ap = argparse.ArgumentParser(description="生成/验收凹角补丁（三条判据把关）")
    ap.add_argument("--font", type=Path, help="生成用：改前字体")
    ap.add_argument("--verify", type=Path, help="验收用：出件后的字体")
    ap.add_argument("--base", type=Path, help="验收用：改前字体（算角外位移与直段）")
    ap.add_argument("--char", required=True)
    ap.add_argument("--at", action="append", required=True, help="角点坐标 x,y")
    ap.add_argument("--radius", default="auto", help="数字或 auto（按判据 2 反推）")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    seeds = [tuple(float(x) for x in s.split(",")) for s in args.at]

    if args.verify:
        if not args.base:
            raise SystemExit("--verify 要给 --base（改前字体）")
        rows, far_pts, max_dist, added, removed = verify(args.verify, args.base, args.char, seeds)
        print(f"{'角点':>15} {'夹角':>5} {'半径':>6} {'残差':>5} {'相切u':>6} {'相切v':>6} "
              f"{'直段1.5':>7} {'直段10':>7} {'切线长':>6} {'占比':>5}")
        for r in rows:
            print(f"{str(r['角点']):>15} {r['夹角']:>5} {r['半径']:>6} {r['圆拟合残差']:>5} "
                  f"{r['相切u']:>6} {r['相切v']:>6} {r['直段1.5']:>7} {r['直段10']:>7} "
                  f"{r['切线长']:>6} {r['占比']:>5.0%}")
        print(f"新增墨 {added} px / 删去 {removed} px（{args.verify and 2048} em，2 px 容差）；"
              f"角外 {FAR:.0f} 单位新增 {far_pts} px，最远改动离角 {max_dist:.1f} 单位")
        fails = []
        for r in rows:
            if max(r["相切u"], r["相切v"]) > ANGLE_MAX and max(r["偏心u"], r["偏心v"]) > 1.0:
                fails.append(f"{r['角点']} 相切角 {max(r['相切u'], r['相切v'])}°")
            if r["占比"] > TANGENT_MAX:
                fails.append(f"{r['角点']} 切线长占直段 {r['占比']:.0%}")
        if far_pts:
            fails.append(f"角外位移 {far_pts} px")
        print("== 判据 ==" + ("三条全过" if not fails else "不过：" + "；".join(fails)))
        raise SystemExit(0 if not fails else 1)

    if not args.font or not args.json:
        raise SystemExit("生成要给 --font 与 --json")
    made = [patch_for(args.font, args.char, s, args.radius) for s in seeds]

    data = json.loads(args.json.read_text(encoding="utf-8")) if args.json.exists() else {}
    data[str(ord(args.char))] = [m["多边形"] for m in made]
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for m in made:
        print(f"  角点 {m['角点']} 夹角 {m['夹角']}° 半径 {m['半径']}（{m['半径来源']}）"
              f" 直段 u={m['直段u']} v={m['直段v']} 切线长 {m['切线长']}"
              f" 占 {m['切线长占直段']:.0%}")
    print(f"{args.char}：{len(made)} 块补丁 → {args.json}")


if __name__ == "__main__":
    main()
