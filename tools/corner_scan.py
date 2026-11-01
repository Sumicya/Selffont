"""凹角扫描：逐字量「折角半径」，给 3,500 常用字排个队。

主人 2026-10-31 定的方向：观感优先，凹角半径目标 **≥24**（母版的 21.9 只当底，不当验收尺）。
按这个方向，先把最差的那批字找出来，再谈改法。

量法（在 FreeType 栅格上量画出来的字形，不量理想轮廓）：

1. 1024 px/em 渲染，marching squares 取墨迹边界，按 1 单位重采样。
2. 逐点算航向角；在 ±3 单位的窗口里累计转角，转角最大的那些点就是「尖锐处」。
3. 用「墨在左边还是右边」判凹/凸：边界朝墨侧拐的是凹角（平切、直角、内凹都在这里）。
4. 对每个凹角，从角点往两边走，累计转角到 90° 时就停，记下走过的弧长 L，
   **半径 r = L / (π/2)**。这正是「折角处拟合圆」的半径，不依赖窗口长度。
5. 一个字的分 = 所有凹角里最小的那个 r（一个字只要有一处尖，它就是尖的）。

已知标定（`篱`，本版 15.1 / 母版 21.9，用 `zhutou.py` 的空象限墨量法量得）——
两种量法在同一处要给出同一量级的数，否则尺子是坏的。

用法：

    .venv/bin/python tools/corner_scan.py --chars 3500字.txt --limit 3500 \
        --font A.ttf --json build/metrics/corners.json --top 40
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage import measure

EM = 1000.0


def boundary(font_path: Path, ch: str, px_per_em: int = 1024):
    font = ImageFont.truetype(str(font_path), px_per_em)
    side = int(px_per_em * 1.6)
    ox, oy = int(px_per_em * 0.4), int(px_per_em * 1.3)
    canvas = Image.new("L", (side, side), 255)
    ImageDraw.Draw(canvas).text((ox, oy), ch, font=font, fill=0, anchor="ls")
    mask = np.asarray(canvas) < 128
    to_u = EM / px_per_em
    out = []
    for c in measure.find_contours(mask.astype(float), 0.5):
        if len(c) < 40:
            continue
        out.append(np.column_stack([(c[:, 1] - ox) * to_u, (oy - c[:, 0]) * to_u]))
    return out, mask, (ox, oy), to_u


def resample(P: np.ndarray, step: float = 1.0) -> np.ndarray:
    out = [P[0]]
    acc = 0.0
    for i in range(1, len(P)):
        a, b = P[i - 1], P[i]
        d = float(np.linalg.norm(b - a))
        while acc + d >= step and d > 1e-9:
            t = (step - acc) / d
            p = a + (b - a) * t
            out.append(p)
            a = p
            d = float(np.linalg.norm(b - a))
            acc = 0.0
        acc += d
    return np.asarray(out)


def heading(Q: np.ndarray) -> np.ndarray:
    d = np.roll(Q, -1, axis=0) - Q
    return np.arctan2(d[:, 1], d[:, 0])


def sharp_spots(Q: np.ndarray, half: float = 3.0, min_turn: float = 60.0):
    """返回 [(点数索引, 转角°)]：±half 单位窗口两端的航向差，就是这一段累计转过的角。"""
    n = len(Q)
    k = max(1, int(round(half)))
    h = heading(Q)
    turn = np.array([
        math.degrees((h[(i + k) % n] - h[(i - k) % n] + math.pi) % (2 * math.pi) - math.pi)
        for i in range(n)
    ])
    spots = []
    for i in range(n):
        if abs(turn[i]) < min_turn:
            continue
        if abs(turn[i]) >= abs(turn[(i - k) % n]) and abs(turn[i]) >= abs(turn[(i + k) % n]):
            spots.append((i, float(turn[i])))
    spots.sort()
    merged = []
    for i, t in spots:
        if merged and i - merged[-1][0] <= 4:
            if abs(t) > abs(merged[-1][1]):
                merged[-1] = (i, t)
            continue
        merged.append((i, t))
    return merged


def is_concave(Q, mask, origin, to_u, i: int, turn: float) -> bool:
    """边界在这一点的左侧还是右侧是墨：朝墨侧拐 = 凹角。"""
    n = len(Q)
    a, b = Q[(i - 1) % n], Q[(i + 1) % n]
    d = b - a
    ln = float(np.linalg.norm(d))
    if ln < 1e-9:
        return False
    left = np.array([-d[1], d[0]]) / ln
    ox, oy = origin
    def ink_at(p):
        px = int(round(ox + p[0] / to_u))
        py = int(round(oy - p[1] / to_u))
        return mask[py, px] if (0 <= py < mask.shape[0] and 0 <= px < mask.shape[1]) else False
    q = Q[i]
    left_ink = ink_at(q + left * 1.5)
    right_ink = ink_at(q - left * 1.5)
    if left_ink == right_ink:
        return False
    # 墨在左 + 向右拐，或墨在右 + 向左拐 = 凹；两边同向 = 凸
    return left_ink != (turn > 0)


def corner_radius(Q, h, i, target: float = 90.0, limit: int = 300):
    """从角点往两边走，累计 |转角| 到 target 度时停，r = 弧长 / (target·π/180)。"""
    n = len(Q)
    total = 0.0
    prev = h[i]
    steps = 0
    j = i
    while total < target and steps < limit:
        j = (j + 1) % n
        d = (h[j] - prev + math.pi) % (2 * math.pi) - math.pi
        total += abs(math.degrees(d))
        prev = h[j]
        steps += 1
    if total < target * 0.8:
        return None
    return steps * 1.0 / (target * math.pi / 180.0)


def scan_char(font_path: Path, ch: str, px_per_em: int = 1024):
    rings, mask, origin, to_u = boundary(font_path, ch, px_per_em)
    best = None
    spots_all = []
    for P in rings:
        Q = resample(np.vstack([P, P[:1]]), 1.0)
        if len(Q) < 20:
            continue
        h = heading(Q)
        for i, turn in sharp_spots(Q):
            if not is_concave(Q, mask, origin, to_u, i, turn):
                continue
            r = corner_radius(Q, h, i)
            if r is None:
                continue
            spots_all.append({"x": round(float(Q[i][0]), 1), "y": round(float(Q[i][1]), 1),
                              "转角": round(turn, 1), "半径": round(r, 1)})
            if best is None or r < best:
                best = r
    spots_all.sort(key=lambda s: s["半径"])
    return best, spots_all


def main() -> None:
    ap = argparse.ArgumentParser(description="逐字凹角半径扫描")
    ap.add_argument("--font", type=Path, required=True)
    ap.add_argument("--chars", type=Path)
    ap.add_argument("--text", type=str)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--detail", type=str, help="只详查这一个字，打印它的凹角列表")
    args = ap.parse_args()

    if args.detail:
        best, spots = scan_char(args.font, args.detail)
        print(f"{args.detail}：最小凹角半径 {best}")
        for s in spots[:10]:
            print(f"   @({s['x']}, {s['y']}) 转角 {s['转角']}° 半径 {s['半径']}")
        return

    raw = args.chars.read_text(encoding="utf-8") if args.chars else (args.text or "")
    chars = []
    seen = set()
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
            r, _ = scan_char(args.font, ch)
        except Exception:
            r = None
        if r is not None:
            rows.append({"字": ch, "半径": round(r, 1)})
        if i % 200 == 0:
            print(f"  …{i}/{len(chars)}", flush=True)

    rows.sort(key=lambda d: d["半径"])
    print(f"\n扫完 {len(chars)} 字，有凹角的 {len(rows)} 字；最小 10："
          + " ".join(f"{d['字']}{d['半径']}" for d in rows[:10]))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"JSON → {args.json}")
    print(f"最差 {args.top}：", " ".join(d["字"] for d in rows[:args.top]))


if __name__ == "__main__":
    main()
