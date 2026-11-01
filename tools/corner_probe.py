"""凹角半径：在**固定角点**邻域里对边界点拟合圆，报半径与拟合残差。

这是「折角处拟合圆」的直接实现，也是本轮的验收尺（主人 2026-10-31：凹角半径 ≥24，
母版只作底）。两个数一起看：

- **半径**：角点 26 单位内的边界点做 Kasa 最小二乘拟合。
- **残差 RMS**：点真的落在一条圆弧上时 <0.5 单位；两条直边相交时 1.5–2.5 单位。
  半径小而残差大 = 尖角；半径大而残差小 = 真的圆角。只有半径不看残差会被「斜边拼出来的
  近似圆」骗过去，所以两个一起报。

为什么不用「空象限墨量」那一种（上一轮的写法）：那个框锚在「横带下沿 6 单位处墨迹的右缘」，
而右缘本身会随补圆一起右移——补完之后框落到弧上，量出来 7.2，图上看却是圆的。锚点必须选
**不受改动影响**的东西，这里是角点坐标本身（两条直边的交点，改前量一次，三个版本共用）。

用法：

    .venv/bin/python tools/corner_probe.py --char 篱 --seed 346,710 --seed 738,703 \
        --font 母版.ttf --font 改前.ttf --font 改后.ttf \
        --label 母版 --label 改前 --label 改后
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

import corner_scan as cs

FIT_RADIUS = 26.0      # 角点邻域半径（单位）：够装下 26 的圆角，又不会被相邻笔画污染


def kasa_fit(P):
    """Kasa 最小二乘圆：返回 (半径, 残差 RMS)。半径不存在时返回 (None, None)。"""
    x, y = P[:, 0], P[:, 1]
    A = np.column_stack([x, y, np.ones(len(P))])
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None, None
    r = math.sqrt(r2)
    res = float(np.sqrt(np.mean((np.hypot(x - cx, y - cy) - r) ** 2)))
    return r, res


def corner_radius(font_path: Path, ch: str, corner, px_per_em: int = 2048):
    rings, _mask, _origin, _to_u = cs.boundary(Path(font_path), ch, px_per_em)
    c = np.asarray(corner, float)
    picks = [P[np.linalg.norm(P - c, axis=1) < FIT_RADIUS] for P in rings]
    P = np.vstack(picks) if picks else np.empty((0, 2))
    if len(P) < 8:
        return None, None, len(P)
    r, res = kasa_fit(P)
    return r, res, len(P)


def main() -> None:
    ap = argparse.ArgumentParser(description="凹角半径：角点邻域内拟合圆")
    ap.add_argument("--char", default="篱")
    ap.add_argument("--seed", action="append", required=True, help="角点坐标 x,y（改前字体上量一次）")
    ap.add_argument("--font", type=Path, action="append", required=True)
    ap.add_argument("--label", action="append", default=None)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    seeds = [tuple(float(v) for v in s.split(",")) for s in args.seed]
    labels = args.label or [f.stem for f in args.font]
    header = f"{'版本':<8}" + "".join(
        f"{'角' + str(i + 1) + ' R':>9}{'残差':>8}" for i in range(len(seeds)))
    print(header)
    data = {}
    for label, font in zip(labels, args.font):
        rows = [corner_radius(font, args.char, s) for s in seeds]
        cells = "".join(
            f"{(r if r is not None else 0):>9.1f}{(res if res is not None else 0):>8.2f}"
            for r, res, _n in rows)
        print(f"{label:<8}{cells}")
        data[label] = [{"半径": None if r is None else round(r, 1),
                        "残差": None if res is None else round(res, 3),
                        "点数": n} for r, res, n in rows]

    if args.json:
        import json
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"字": args.char, "角点": seeds, "读点半径": FIT_RADIUS,
                                         "各版本": data}, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"JSON → {args.json}")


if __name__ == "__main__":
    main()
