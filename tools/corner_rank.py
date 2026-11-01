"""按「折角半径」给常用字排队：一个字的分 = 它所有凹角里最小的那个拟合半径。

与 `corner_probe.py` 同一把尺（角点邻域内 Kasa 拟合圆），只是把角点换成自动找到的尖点：

1. 1024 px/em 出边界，1 单位重采样，算航向角；±3 单位窗口里转角 >60° 的点是尖点；
2. 只留凹角（墨在边界哪一侧 + 转角符号判）；
3. 每个尖点在 26 单位内拟合圆，得半径与残差；
4. 字分 = 最小半径。**不按残差筛**：尖角的点本来就是两条直线，Kasa 拟合残差必然大
   （篱 的角：本版 15.2 / 残差 2.04，补圆后 25.3 / 0.21）——按残差筛会正好把要修的字筛掉，
   第一版就是这么排出一张「最圆的字」榜单。残差照报，只作旁证。

用法：

    .venv/bin/python tools/corner_rank.py --chars 3500字.txt --limit 3500 \
        --font build/metrics/ours3500/preview.ttf --json build/metrics/corner_rank.json --top 40
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import corner_scan as cs
from corner_probe import kasa_fit

FIT_RADIUS = 26.0
MIN_TURN = 60.0


def char_score(font_path: Path, ch: str, px_per_em: int = 1024):
    rings, mask, origin, to_u = cs.boundary(Path(font_path), ch, px_per_em)
    spots = []
    for P in rings:
        Q = cs.resample(np.vstack([P, P[:1]]), 1.0)
        if len(Q) < 40:
            continue
        k = 3
        h = cs.heading(Q)
        turn = np.array([math.degrees((h[(i + k) % len(Q)] - h[(i - k) % len(Q)] + math.pi)
                                      % (2 * math.pi) - math.pi) for i in range(len(Q))])
        for i, t in cs.sharp_spots(Q, 3.0, MIN_TURN):
            if not cs.is_concave(Q, mask, origin, to_u, i, float(turn[i])):
                continue
            pts = [R[np.linalg.norm(R - Q[i], axis=1) < FIT_RADIUS] for R in rings]
            P2 = np.vstack([p for p in pts if len(p)])
            if len(P2) < 8:
                continue
            r, res = kasa_fit(P2)
            if r is None or res is None:
                continue
            spots.append({"x": round(float(Q[i][0]), 1), "y": round(float(Q[i][1]), 1),
                          "半径": round(r, 1), "残差": round(res, 3)})
    if not spots:
        return None, []
    spots.sort(key=lambda s: s["半径"])
    return spots[0]["半径"], spots


def main() -> None:
    ap = argparse.ArgumentParser(description="按折角半径给字排队")
    ap.add_argument("--font", type=Path, required=True)
    ap.add_argument("--chars", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--progress", type=int, default=200)
    args = ap.parse_args()

    raw = args.chars.read_text(encoding="utf-8")
    chars, seen = [], set()
    for ch in raw:
        if ch.isspace() or ch in seen:
            continue
        seen.add(ch)
        chars.append(ch)
        if args.limit and len(chars) >= args.limit:
            break

    rows = []
    for i, ch in enumerate(chars, 1):
        try:
            r, _ = char_score(args.font, ch)
        except Exception:
            r = None
        if r is not None:
            rows.append({"字": ch, "半径": r})
        if args.progress and i % args.progress == 0:
            print(f"  …{i}/{len(chars)}  当前最差 " +
                  " ".join(f"{d['字']}{d['半径']}" for d in sorted(rows, key=lambda d: d["半径"])[:6]),
                  flush=True)

    rows.sort(key=lambda d: d["半径"])
    print(f"\n扫 {len(chars)} 字，有凹角 {len(rows)} 字；最差 {args.top}：")
    print("  " + " ".join(f"{d['字']}{d['半径']}" for d in rows[:args.top]))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"JSON → {args.json}")


if __name__ == "__main__":
    main()
