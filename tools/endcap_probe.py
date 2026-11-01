"""端头圆：量「补出来的半圆半径」与「该处局部半笔宽」的比。

判据（2026-11-01 主人定）：**|r_end / r_half − 1| ≤ 0.05**，逐字、逐笔、逐自由端头。

两个量各自独立取：

- **r_end**：端头外廓拟合圆的半径。取该端头前方半圆上的轮廓点做 Kasa 最小二乘。
- **r_half**：该端点处的局部半笔宽。沿笔轴从端头往里退 s 单位，在 s 处做法向射线，
  与边界相交得两侧距离 d+ / d−，半笔宽 = (d+ + d−) / 2。**s 要退到半圆之外**
  （s ≥ 1.2·r_end），否则量到的是半圆本身，量出来永远等于 r_end——这是这道题唯一的坑。

为什么要拆成三个数：端头做小了可能是三处之一，混在一起看不出来。

| 量 | 取在哪 | 说明 |
| --- | --- | --- |
| `R_poly` | 描边密点环（未拟合曲线的折线半圆） | 数据给的半径 = 剖面末值 |
| `R_font` | 字体文件里的矢量轮廓 | 再经 DP 简化 + 二次拟合 + 整数化之后 |
| `H_body` | 字体轮廓，退 1.5·R 处 | 屏幕上看到的笔宽 |

`R_poly / H_body` 小 = **数据**的端部剖面塌了；`R_font / R_poly` 小 = **出件**把圆头啃掉了。

用法：

    .venv/bin/python tools/endcap_probe.py --font build/metrics/endcap/preview.ttf \\
        --chars 一二三十丁八人入大天夫上下川王主立文 --json build/metrics/endcap.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design_cjk  # noqa: E402

TARGET = 0.05          # |r_end / r_half − 1| 的门槛
WEIGHT = 400


# ---------------------------------------------------------------- 轮廓

def vector_rings(font_path: Path, ch: str):
    """字体里的轮廓点与 on/off 标志（矢量，不栅格）。"""
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.ttLib import TTFont
    font = TTFont(str(font_path))
    glyph = font.getGlyphSet()[font.getBestCmap()[ord(ch)]]
    pen = RecordingPen()
    glyph.draw(pen)
    rings, flags, cur, curf = [], [], [], []
    for op, args in pen.value:
        if op == "moveTo":
            cur, curf = [args[0]], [1]
        elif op == "lineTo":
            cur.append(args[0])
            curf.append(1)
        elif op == "qCurveTo":
            pts = [a for a in args if a is not None]
            for a in pts[:-1]:
                cur.append(a)
                curf.append(0)
            cur.append(pts[-1])
            curf.append(1)
        elif op in ("closePath", "endPath"):
            if cur:
                rings.append(cur)
                flags.append(curf)
                cur, curf = [], []
    return rings, flags


def flatten(points, flags, steps: int = 8) -> np.ndarray:
    """按 TrueType 规则把二次曲线展平成折线。

    必须展平再量：二次曲线的控制点在曲线**外面**（90° 圆弧的控制点在 45° 方向 1.41R 处），
    拿控制点当折线量，射线会打在控制多边形上——半径虚高、圆度虚大，全是假的。
    """
    P = [(float(x), float(y)) for x, y in points]
    F = list(flags)
    n = len(P)
    if n == 0:
        return np.zeros((0, 2))
    # 起点若为 off，按 TrueType 规则从「前一个 on 与后一个 on 的中点」起
    start = 0
    if not F[0]:
        on_idx = [i for i in range(n) if F[i]]
        if not on_idx:
            return np.array(P)
        start = on_idx[0]
        P = P[start:] + P[:start]
        F = F[start:] + F[:start]
        P.insert(0, ((P[-1][0] + P[1][0]) / 2, (P[-1][1] + P[1][1]) / 2))
        F.insert(0, 1)
    out = [P[0]]
    cur = P[0]
    ctrl = None
    for i in range(1, len(P) + 1):
        j = i % len(P)
        if F[j]:
            end = P[j]
            if ctrl is None:
                out.append(end)
            else:
                for k in range(1, steps + 1):
                    u = k / steps
                    v = 1 - u
                    out.append((v * v * cur[0] + 2 * u * v * ctrl[0] + u * u * end[0],
                                v * v * cur[1] + 2 * u * v * ctrl[1] + u * u * end[1]))
                ctrl = None
            cur = end
        else:
            ctrl = P[j]
    return np.array(out)


def kasa(P: np.ndarray):
    A = np.column_stack([2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))])
    sol, *_ = np.linalg.lstsq(A, (P ** 2).sum(1), rcond=None)
    cx, cy, c = sol
    R = math.sqrt(c + cx * cx + cy * cy)
    res = np.abs(np.linalg.norm(P - [cx, cy], axis=1) - R)
    return np.array([cx, cy]), float(R), float(res.max())


def ray_cross(ring: np.ndarray, origin, direction) -> float | None:
    """从 origin 沿 direction 打一条射线，返回最近的交点距离（>0）。"""
    best = None
    n = len(ring)
    ox, oy = origin
    dx, dy = direction
    for i in range(n):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((ax - ox) * ey - (ay - oy) * ex) / den        # 沿射线
        u = ((ax - ox) * dy - (ay - oy) * dx) / den        # 沿线段
        if t > 1e-9 and -1e-9 <= u <= 1 + 1e-9:
            if best is None or t < best:
                best = t
    return best


def half_width_at(ring: np.ndarray, P: np.ndarray, normal, back, R: float):
    """退 back 单位处量半笔宽：两侧都要有边界，缺一侧就返回 None。"""
    origin = P + back
    d_plus = ray_cross(ring, origin, tuple(normal))
    d_minus = ray_cross(ring, origin, tuple(-normal))
    if d_plus is None or d_minus is None:
        return None, d_plus, d_minus
    return (d_plus + d_minus) / 2.0, d_plus, d_minus


# ---------------------------------------------------------------- 逐端头

def ends_of(glyph: dict):
    """按 `stroke_contours` 的环顺序，列出每个自由端头：环号、端点、外法向、内退方向。"""
    out = []
    ring_idx = 0
    for si, stroke in enumerate(glyph.get("strokes") or []):
        segs = stroke.get("segs") or []
        if not segs:
            continue
        if design_cjk._zero_length(stroke):
            continue                                  # 字点也走 stroke_contours，但它是整圆
        if stroke.get("closed"):
            ring_idx += 2                             # 闭合笔：外环 + 内环
            continue
        axis, ts, tans = design_cjk._dense_axis(stroke)
        for which in ("start", "end"):
            k = 0 if which == "start" else -1
            T = np.array(tans[k], float)
            if which == "start":
                T = -T                                # 外法向朝笔画外侧
            nrm = np.array([-T[1], T[0]])
            out.append({"stroke": si, "ring": ring_idx, "which": which,
                        "P": np.array(axis[k], float), "T": T, "n": nrm})
        ring_idx += 1
    return out


def cap_rays(ring, P, T, R_hint: float, n_ray: int = 25):
    """从端点沿前方 ±86.4° 打 n_ray 条射线，返回各方向的边界距离。"""
    base = math.atan2(T[1], T[0])
    dists = []
    for k in range(n_ray):
        a = base + math.radians(-86.4 + 172.8 * k / (n_ray - 1))
        d = ray_cross(ring, tuple(P), (math.cos(a), math.sin(a)))
        if d is not None and 0.2 * R_hint < d < 2.2 * R_hint:
            dists.append(d)
    if len(dists) < n_ray // 2:
        return None
    return np.array(dists, float)


def radial_at(ring, P, T, deg: float):
    """指定角度（相对笔轴前方）上的边界距离。"""
    a = math.atan2(T[1], T[0]) + math.radians(deg)
    return ray_cross(ring, tuple(P), (math.cos(a), math.sin(a)))


def r_end_of(dists: np.ndarray):
    R = float(np.median(dists))
    roundness = float((dists.max() - dists.min()) / (2 * R))     # 0 = 正圆
    return R, roundness


def probe_font(font: Path, chars: str, weight: int = WEIGHT):
    data = design_cjk.load()
    rows = []
    for ch in chars:
        cp = ord(ch)
        glyph = data.get(cp)
        if glyph is None:
            rows.append({"字": ch, "错": "数据里没有"})
            continue
        polys = design_cjk.outline_points(glyph, weight)     # 折线（未拟合）
        rings_src = design_cjk.stroke_contours
        # 环顺序与 outline_points 一致：逐笔调一遍只为拿轴
        try:
            fonts_p, fonts_f = vector_rings(font, ch)
        except KeyError:
            rows.append({"字": ch, "错": "字体里没有"})
            continue
        FLAT = [flatten(p, f) for p, f in zip(fonts_p, fonts_f)]   # 二次曲线展平后才能打射线
        ends = ends_of(glyph)
        # 先粗估 R：用剖面末值的一半宽（有 prof 就取末值）
        half0 = design_cjk.stroke_half(glyph["strokes"][0], glyph, weight) if ends else 10.0
        for e in ends:
            stroke = glyph["strokes"][e["stroke"]]
            half = design_cjk.stroke_half(stroke, glyph, weight)
            P, T, nrm = e["P"], e["T"], e["n"]
            if e["ring"] >= len(polys) or e["ring"] >= len(FLAT):
                continue
            poly = np.asarray(polys[e["ring"]], float)
            font_ring = FLAT[e["ring"]]
            dpoly = cap_rays(poly, P, T, half * 1.3)
            dfont = cap_rays(font_ring, P, T, half * 1.3)
            if dpoly is None or dfont is None:
                continue
            R_poly, round_poly = r_end_of(dpoly)
            R_font, round_font = r_end_of(dfont)
            d0f = radial_at(font_ring, P, T, 0.0)
            d45f = [v for v in (radial_at(font_ring, P, T, 45.0), radial_at(font_ring, P, T, -45.0))
                    if v is not None]
            bulge = (float(np.mean(d45f)) / d0f) if (d45f and d0f) else float("nan")
            # 局部半笔宽：退到半圆**外面 4 单位**，法向两侧各打一条射线。
            # 不能退 1.5R：撇、捺的剖面在端部是收细的，退太远量到的是笔身最粗处，
            # 会把「端头按局部半笔宽画对了」判成「大了」——10 个不过的全是撇捺钩。
            back = -T * (R_font + 4.0)
            hw_font, dpl, dmi = half_width_at(font_ring, P, nrm, back, R_font)
            hw_poly, _, _ = half_width_at(poly, P, nrm, back, R_poly)
            if not hw_font or not hw_poly:
                continue
            rows.append({
                "字": ch, "笔": e["stroke"], "端": e["which"],
                "顶点": [round(float(P[0]), 1), round(float(P[1]), 1)],
                "R_poly": round(R_poly, 2), "R_font": round(R_font, 2),
                "圆度_poly": round(round_poly, 3), "圆度_font": round(round_font, 3),
                "H_body": round(hw_font, 2), "H_poly": round(hw_poly, 2),
                "两侧": [round(dpl, 2), round(dmi, 2)],
                "d0": round(d0f, 2) if d0f else None,
                "凸度": round(bulge, 3),
                "比_apex": round(d0f / hw_font, 3) if d0f else None,
                "比_font": round(R_font / hw_font, 3),
                "比_出件": round(R_font / R_poly, 3),
                "比_数据": round(R_poly / hw_poly, 3),
            })
    return rows


def summarize(rows):
    ok = [r for r in rows if "比_font" in r]
    print(f"{'字':>2} {'笔':>2} {'端':>5} {'R_poly':>6} {'R_font':>6} {'圆度':>5} {'圆度':>5} "
          f"{'H_body':>6} {'r/h':>6} {'出件':>5} {'数据':>5}")
    print(f"{'':>2} {'':>2} {'':>5} {'折线':>6} {'出件':>6} {'折线':>5} {'出件':>5}")
    for r in ok:
        flag = "" if abs(r["比_font"] - 1) <= TARGET else "  ✗"
        print(f"{r['字']:>2} {r['笔']:>2} {r['端']:>5} {r['R_poly']:>6} {r['R_font']:>6} "
              f"{r['圆度_poly']:>5} {r['圆度_font']:>5} {r['H_body']:>6} {r['比_font']:>6} "
              f"{r['比_出件']:>5} {r['比_数据']:>5}{flag}")
    if not ok:
        print("没有量到端头")
        return
    ratios = np.array([r["比_font"] for r in ok])
    out = np.array([r["比_出件"] for r in ok])
    dat = np.array([r["比_数据"] for r in ok])
    rnd_p = np.array([r["圆度_poly"] for r in ok])
    rnd_f = np.array([r["圆度_font"] for r in ok])
    bad = int((np.abs(ratios - 1) > TARGET).sum())
    print(f"\n端头 {len(ok)} 个；r_end/r_half 中位 {np.median(ratios):.3f}、"
          f"最小 {ratios.min():.3f}、最大 {ratios.max():.3f}；"
          f"|比−1| > {TARGET:.0%} 的 {bad} 个（{bad / len(ok):.0%}）")
    print(f"  拆因：出件/折线 {np.median(out):.3f}、数据端部剖面 {np.median(dat):.3f}（中位）")
    print(f"  圆度（0=正圆）：折线 中位 {np.median(rnd_p):.3f}；出件 中位 {np.median(rnd_f):.3f}")
    apex = np.array([r["比_apex"] for r in ok if r.get("比_apex")])
    bulge = np.array([r["凸度"] for r in ok if r.get("凸度")])
    print(f"  正前方（0°）半径比：中位 {np.median(apex):.3f}"
          f"；|比−1| > {TARGET:.0%} 的 {int((np.abs(apex - 1) > TARGET).sum())} 个")
    print(f"  凸度 d(±45°)/d(0°)：中位 {np.median(bulge):.3f}（理想 2×90° 二次曲线 = 1.061，正圆 = 1.000）")


def main() -> None:
    ap = argparse.ArgumentParser(description="端头圆：r_end / r_half")
    ap.add_argument("--font", type=Path, required=True)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    rows = probe_font(args.font, args.chars)
    summarize(rows)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {args.json}")


if __name__ == "__main__":
    main()
