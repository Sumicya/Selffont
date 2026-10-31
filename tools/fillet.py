"""生成凹角补丁：在**改动前**的字形上量出圆角几何，写成 `tools/fillet_patches.json`。

补丁 = 一段圆弧围成的多边形环（顶点 C → 切点 T1 → 弧 → 切点 T2）。应用时由
`cjk_vf.build_vf` 追加到该字的环列表末尾，`design_cjk` 的笔画环一条都不改——所以笔宽、
端头、字面高度一个数都不动。

三条硬约束（都是踩出来的）：

1. **绕向必须与笔画环一致（−1）**。nonzero 填充下，同向重叠处 −1 + −1 = −2 仍是墨；
   反向（+1）会在重叠处抵消成 0，渲染出一道发丝白缝，看起来比原来更尖。
2. **弧必须鼓向空气侧**（与折点 C 在弦 T1T2 的同侧）。反了就是弧穿进墨里，出来一个逗号。
3. **圆心取平分线上「空气那一侧」**那个候选。

用法（角点从 `corner_probe.py` 量出来，改前字体上量一次）：

    .venv/bin/python tools/fillet.py --font build/metrics/ours3500/preview.ttf \
        --char 篱 --at 346,710 --at 738,703 --radius 26 --json tools/fillet_patches.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import corner_scan as cs

TARGET = 24.0          # 验收线；补到 24 之上留一点余量，取 26


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


def patch_for(font_path: Path, ch: str, seed, radius: float, px_per_em: int = 1024):
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

    # 取点窗口 16–44 单位：离开折点、又落在两条直边上（窗口换到 36–78 会让交点漂、补丁歪）
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

    # 空气侧 = 沿平分线走得**远**的那一侧。不能用「2 单位处有没有墨」判：小圆角自己的墨
    # 就在 2 单位以内，判反了圆心会跑到另一边，补丁整个歪掉（实测半径从 26 掉回 15）。
    d1, d2 = first_ink(w), first_ink(-w)
    if d2 is not None and (d1 is None or d2 > d1):
        w = -w

    t = radius / math.tan(theta / 2.0)
    T1 = C + u * t
    T2 = C + v * t
    O = C + w * (radius / math.sin(theta / 2.0))
    a1 = math.atan2(*(T1 - O)[::-1])
    a2 = math.atan2(*(T2 - O)[::-1])
    da2 = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    # 弧鼓向空气侧
    mid = (T1 + T2) / 2

    def side(p):
        return (p[0] - mid[0]) * (T2[1] - T1[1]) - (p[1] - mid[1]) * (T2[0] - T1[0])

    arc_mid = np.array([O[0] + radius * math.cos(a1 + da2 / 2), O[1] + radius * math.sin(a1 + da2 / 2)])
    if side(arc_mid) * side(C) < 0:
        da2 -= 2 * math.pi * np.sign(da2)

    seg = 16
    arc = [(float(O[0] + radius * math.cos(a1 + da2 * k / seg)),
            float(O[1] + radius * math.sin(a1 + da2 * k / seg))) for k in range(seg + 1)]
    C_in = C - w * 4.0                    # 顶点往墨里退 4 单位：栅格边界比真边缘略靠外
    pts = [tuple(C_in), tuple(T1)] + arc[1:-1] + [tuple(T2)]
    area = sum(pts[k][0] * pts[(k + 1) % len(pts)][1] - pts[(k + 1) % len(pts)][0] * pts[k][1]
               for k in range(len(pts)))
    if area > 0:                          # 绕向对齐笔画环（−1）
        pts.reverse()
    return {
        "角点": [round(float(C[0]), 2), round(float(C[1]), 2)],
        "夹角": round(math.degrees(theta), 1),
        "圆心": [round(float(O[0]), 2), round(float(O[1]), 2)],
        "半径": radius,
        "多边形": [[round(x, 3), round(y, 3)] for x, y in pts],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="生成凹角补丁（圆弧多边形）")
    ap.add_argument("--font", type=Path, required=True)
    ap.add_argument("--char", required=True)
    ap.add_argument("--at", action="append", required=True, help="角点坐标 x,y")
    ap.add_argument("--radius", type=float, default=TARGET)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()

    seeds = [tuple(float(v) for v in s.split(",")) for s in args.at]
    made = [patch_for(args.font, args.char, s, args.radius) for s in seeds]

    data = json.loads(args.json.read_text(encoding="utf-8")) if args.json.exists() else {}
    data[str(ord(args.char))] = [m["多边形"] for m in made]
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for m in made:
        print(f"  角点 {m['角点']} 夹角 {m['夹角']}° 圆心 {m['圆心']} 半径 {m['半径']} "
              f"多边形 {len(m['多边形'])} 点")
    print(f"{args.char}：{len(made)} 块补丁 → {args.json}")


if __name__ == "__main__":
    main()
