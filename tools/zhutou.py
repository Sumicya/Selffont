"""竹头诊断：把「头不够圆」变成可算的数。

主人 2026-10-31 的原话是 `头不够圆（篱·竹头两端与折角偏方），其他未看出`。
「方」落在两处几何上，这一份只量这两处，不做改动：

1. **区域内的接点跳变**（第 4 条同口径）：在 bbox 上半部分的矩形里，相邻段接点的切向夹角，
   > 60° 的角点排除，取中位。只算**同一条轮廓内**的接点——`metrics.py` 的 ④ 把所有轮廓拼成
   一条点列，环与环之间那一处假接点也会被算进去，区域内本来就不该有这种接点。
2. **端头与折角的曲率半径**（在 FreeType 栅格上量，design-principles 2026-10-28 那条）：

   - 端头：两横四个端，量端面高度 h(d)——离端点 d 单位处墨迹的竖向高度。
     圆弧端头 h(d) ≈ 2√(2Rd)，于是 **R = h(d)² / (8d)**；平切端头 h(d) ≈ 笔厚，R 会被高估。
     取 d = 2 单位（笔厚的 1/27），这个距离上圆/平的差别最大。
   - 折角：两横和两竖相接的凹角。量从折点沿 45° 对角线到墨迹的距离 d45；
     圆角半径 r 与它的关系是 **d45 = r(√2 − 1)**，所以 r = d45 / 0.4142。
     尖角 d45 ≈ 0，r ≈ 0。

两者都是「端点处拟合圆」的直接量：一个用弓高、一个用凹角对角线，都不依赖窗口长度，
换字号也不会变。

用法：

    .venv/bin/python tools/zhutou.py --char 篱 \
        --mother build/mother/MarukoGothicCJKsc-Regular.ttf \
        --ours build/metrics/ours3500/preview.ttf \
        --alt build/metrics/ours3500-true/preview.ttf --json build/metrics/zhutou.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

UPEM = 1000.0
JUMP_CORNER = 60.0
N_SAMPLES = 8
RASTER = 2048          # px/em：1 单位 ≈ 2 px，端面 h(2) 有 ±0.5 单位的精度


# ---------------------------------------------------------------- 轮廓（判据 1）

def rings_of(path: Path, ch: str):
    """逐条轮廓返回 (密点, 段起切向, 段终切向, 段起点)；展开规则与 metrics._flatten 相同。"""
    font = TTFont(str(path), lazy=False)
    gs = font.getGlyphSet()
    g = gs[font.getBestCmap()[ord(ch)]]
    pen = DecomposingRecordingPen(gs)
    g.draw(pen)

    rings = []
    pts: list[tuple[float, float]] = []
    tans: list[tuple[tuple[float, float], tuple[float, float]]] = []
    starts: list[tuple[float, float]] = []
    cur = (0.0, 0.0)

    def unit(dx, dy):
        n = math.hypot(dx, dy)
        return (dx / n, dy / n) if n > 1e-9 else (0.0, 0.0)

    for op, args in pen.value:
        if op == "moveTo":
            if pts:
                rings.append((pts, tans, starts))
            pts, tans, starts = [args[0]], [], []
            cur = args[0]
        elif op == "lineTo":
            nxt = args[0]
            d = unit(nxt[0] - cur[0], nxt[1] - cur[1])
            tans.append((d, d))
            starts.append(cur)
            for k in range(1, N_SAMPLES + 1):
                t = k / N_SAMPLES
                pts.append((cur[0] + (nxt[0] - cur[0]) * t, cur[1] + (nxt[1] - cur[1]) * t))
            cur = nxt
        elif op == "qCurveTo":
            *ctrls, end = args
            if end is None:
                end = ctrls.pop(0) if ctrls else cur
            prev, c = cur, list(ctrls)
            while c:
                q = c.pop(0)
                nxt = c[0] if c else end
                e = end if not c else ((q[0] + nxt[0]) / 2, (q[1] + nxt[1]) / 2)
                tans.append((unit(q[0] - prev[0], q[1] - prev[1]), unit(e[0] - q[0], e[1] - q[1])))
                starts.append(prev)
                for k in range(1, N_SAMPLES + 1):
                    t = k / N_SAMPLES
                    pts.append(((1 - t) ** 2 * prev[0] + 2 * (1 - t) * t * q[0] + t * t * e[0],
                                (1 - t) ** 2 * prev[1] + 2 * (1 - t) * t * q[1] + t * t * e[1]))
                prev = e
            cur = end
        elif op == "curveTo":
            c1, c2, end = args[-3:]
            tans.append((unit(c1[0] - cur[0], c1[1] - cur[1]), unit(end[0] - c2[0], end[1] - c2[1])))
            starts.append(cur)
            for k in range(1, N_SAMPLES + 1):
                t = k / N_SAMPLES
                pts.append(((1 - t) ** 3 * cur[0] + 3 * (1 - t) ** 2 * t * c1[0]
                            + 3 * (1 - t) * t * t * c2[0] + t ** 3 * end[0],
                            (1 - t) ** 3 * cur[1] + 3 * (1 - t) ** 2 * t * c1[1]
                            + 3 * (1 - t) * t * t * c2[1] + t ** 3 * end[1]))
            cur = end
        elif op == "closePath":
            if pts:
                rings.append((pts, tans, starts))
            pts, tans, starts = [], [], []
    if pts:
        rings.append((pts, tans, starts))
    return rings


def bbox(rings):
    xs = [p[0] for pts, _, _ in rings for p in pts]
    ys = [p[1] for pts, _, _ in rings for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def region_jumps(rings, region) -> dict:
    """只算同一条轮廓内、接点落在 region 里的切向夹角（> 60° 当角点排除）。"""
    x0, y0, x1, y1 = region
    ok, corner = [], 0
    for pts, tans, starts in rings:
        for i in range(len(tans) - 1):
            (_, a), (b, _) = tans[i], tans[i + 1]
            if a == (0.0, 0.0) or b == (0.0, 0.0):
                continue
            sx, sy = starts[i + 1]
            if not (x0 <= sx <= x1 and y0 <= sy <= y1):
                continue
            dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
            deg = math.degrees(math.acos(dot))
            if deg > JUMP_CORNER:
                corner += 1
            else:
                ok.append(deg)
    if not ok:
        return {"接点数": 0, "中位": None, "P90": None, "被排除的角点数": corner}
    arr = np.asarray(ok)
    return {
        "接点数": len(ok),
        "中位": round(float(np.median(arr)), 3),
        "P90": round(float(np.percentile(arr, 90)), 3),
        "被排除的角点数": corner,
    }


# ---------------------------------------------------------------- 栅格（判据 2）

def raster(path: Path, ch: str, px_per_em: int = RASTER):
    """FreeType 栅格，anchor="ls"：像素坐标能直接换成字体单位。"""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(path), px_per_em)
    size = int(px_per_em * 1.6)
    ox, oy = int(px_per_em * 0.4), int(px_per_em * 1.3)
    canvas = Image.new("L", (size, size), 255)
    ImageDraw.Draw(canvas).text((ox, oy), ch, font=font, fill=0, anchor="ls")
    return np.asarray(canvas) < 128, px_per_em, (ox, oy)


def runs_of(row):
    if not row.any():
        return []
    e = np.diff(np.concatenate(([0], row.astype(int), [0])))
    s, t = np.where(e == 1)[0], np.where(e == -1)[0]
    return [(int(a), int(b)) for a, b in zip(s, t)]


def ink_bbox(m):
    ys, xs = np.where(m)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def find_bars(m, ppe):
    """上半部分最上面那一段长横 = 竹头两横；返回单位坐标。"""
    x0, y0, x1, y1 = ink_bbox(m)
    to_u = UPEM / ppe
    y_mid = (y0 + y1) // 2
    widths = []
    for row in range(y0, y_mid + 1):
        widths.append(max((b - a for a, b in runs_of(m[row])), default=0))
    widths = np.asarray(widths)
    rows = np.where(widths >= 0.25 * (x1 - x0))[0]
    if len(rows) == 0:
        raise SystemExit("上半部分找不到长横")
    groups, cur = [], [rows[0]]
    for r in rows[1:]:
        if r == cur[-1] + 1:
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)
    band = groups[0]                      # 最上面那一段 = 竹头两横
    band_top, band_bot = y0 + int(band[0]), y0 + int(band[-1])
    y_cut = (band_top + band_bot) // 2
    bars = sorted([r for r in runs_of(m[y_cut]) if (r[1] - r[0]) > 0.15 * (x1 - x0)])
    return {
        "band_top": band_top, "band_bot": band_bot, "y_cut": y_cut,
        "bars": bars, "to_u": to_u,
        "thick": (band_bot - band_top) * to_u,
        "x_span": (x0, x1),
    }


def height_at(m, col_px, row_px):
    """在 (col_px, row_px) 所在的那段墨迹上，量竖向高度（像素）。"""
    col = m[:, col_px]
    # 从 row_px 往上、下各走到空白为止
    top = row_px
    while top - 1 >= 0 and col[top - 1]:
        top -= 1
    bot = row_px
    while bot + 1 < len(col) and col[bot + 1]:
        bot += 1
    return bot - top + 1


def end_radius(m, ppe, x_end_px, y_cut_px, d_units=2.0):
    """端头半径：量端面高度 h(d)，按 h(d)² ≈ 8Rd 折成圆的半径。

    圆弧端头 h(d) 随 √d 增长，平切端头 h(d) 一开始就等于笔厚。d 取 2 单位
    （笔厚的 1/27），这个距离上圆与平的差别最大，也最不怕字形整体平移。
    """
    to_px = ppe / UPEM
    d_px = max(1, int(round(d_units * to_px)))
    h = height_at(m, x_end_px - d_px, y_cut_px)
    h_u = h / to_px
    return h_u * h_u / (8.0 * d_units), h_u


def _vertical_runs(m, ppe, row, x_lo, x_hi):
    """在 row 这行里，找出真正的「竖」：竖直向下 14 单位后中心几乎不横移的那几段。

    竹头的两横下面各有两段墨：一撇（斜，往左下走）和一竖（直）。撇与竖的横截面宽度
    在同一高度上只差 10%，靠宽度分不开；靠「往下走时中心动不动」分得开。
    """
    to_px = ppe / UPEM
    def centers(r):
        return [((a + b) / 2, a, b) for a, b in runs_of(m[r]) if x_lo <= a and b <= x_hi]
    c1 = centers(row)
    c2 = centers(row + int(round(14 * to_px)))
    out = []
    for cx, a, b in c1:
        near = [v for v in c2 if abs(v[0] - cx) < 20 * to_px]
        if len(near) == 1 and abs(near[0][0] - cx) < 6 * to_px:
            out.append((a, b))
    return out


def corner_radius(m, ppe, x_edge_px, y_bar_bot_px, reach_units=34.0):
    """折角半径：数「空象限」里多出来的墨，按圆角面积 A = r²(1−π/4) 反解。

    空象限 = 折点右下方那块长方形（右边界 34 单位、下边界 34 单位）。尖角那里是纯空气，
    数出来接近 0；有圆角时墨会鼓进这块面积，A 与半径一一对应，不依赖任何窗口拟合。
    """
    to_px = ppe / UPEM
    w = int(round(reach_units * to_px))
    sub = m[y_bar_bot_px + 2: y_bar_bot_px + w, x_edge_px + 2: x_edge_px + w]
    area = float(sub.sum()) / (to_px * to_px)
    r = math.sqrt(area / (1.0 - math.pi / 4.0)) if area > 0 else 0.0
    return r, area


# ---------------------------------------------------------------- 一次性跑完

def diagnose(path: Path, ch: str, region=None) -> dict:
    rings = rings_of(path, ch)
    x0, y0, x1, y1 = bbox(rings)
    reg = region or (x0, (y0 + y1) / 2, x1, y1)
    jumps = region_jumps(rings, reg)

    m, ppe, (ox, oy) = raster(path, ch)
    info = find_bars(m, ppe)
    to_u = info["to_u"]
    y_cut_px = info["y_cut"]

    ends = []
    for i, (a, b) in enumerate(info["bars"]):
        for side, col in (("左", a), ("右", b - 1)):
            R, h = end_radius(m, ppe, col, y_cut_px)
            ends.append({"横": i + 1, "端": side,
                         "x": round((col - ox) * to_u, 1),
                         "y": round((oy - y_cut_px) * to_u, 1),
                         "端面高": round(h, 1), "半径": round(R, 1)})

    # 折角：横带下沿往下 6 单位，取两条「竖」的右缘当折点
    row = int(round(info["band_bot"] + 6 * ppe / UPEM))
    x_lo, x_hi = info["x_span"][0], info["x_span"][1]
    corners = []
    for (a, b) in _vertical_runs(m, ppe, row, x_lo, x_hi):
        R, area = corner_radius(m, ppe, b, info["band_bot"])
        corners.append({"x": round((b - ox) * to_u, 1),
                        "y": round((oy - info["band_bot"]) * to_u, 1),
                        "空象限墨": round(area, 1),
                        "半径": round(R, 1)})

    def pct(vals, p):
        vals = [v for v in vals if v is not None]
        return round(float(np.percentile(vals, p)), 1) if vals else None

    return {
        "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
        "区域": [round(v, 1) for v in reg],
        "区域接点": jumps,
        "横带": {"y": [round((oy - info["band_bot"]) * to_u, 1),
                       round((oy - info["band_top"]) * to_u, 1)],
                 "厚": round(info["thick"], 1),
                 "两横": [{"x0": round((a - ox) * to_u, 1), "x1": round((b - ox) * to_u, 1)}
                          for a, b in info["bars"]]},
        "端头": ends,
        # 左端合并进撇、没有端面（h≈0），只把两个自由端计入 P50/P90
        "端头半径_P50": pct([e["半径"] for e in ends if e["端面高"] > 5], 50),
        "端头半径_P90": pct([e["半径"] for e in ends if e["端面高"] > 5], 90),
        "无端面的端": [f"横{e['横']}{e['端']}" for e in ends if e["端面高"] <= 5],
        "折角": corners,
        "折角半径_P50": pct([c["半径"] for c in corners], 50) if corners else None,
        "折角半径_P90": pct([c["半径"] for c in corners], 90) if corners else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="竹头诊断：区域内接点跳变 + 端头/折角拟合半径")
    ap.add_argument("--char", default="篱")
    ap.add_argument("--mother", type=Path, required=True)
    ap.add_argument("--ours", type=Path, required=True)
    ap.add_argument("--alt", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    base = diagnose(args.ours, args.char)
    region = tuple(base["区域"])
    result = {"字": args.char, "区域": list(region), "母版": diagnose(args.mother, args.char, region), "本版": base}
    if args.alt:
        result["对照"] = diagnose(args.alt, args.char, region)

    print(f"字 {args.char}｜区域（本版 bbox 上半部分）= x [{region[0]}, {region[2]}] "
          f"y [{region[1]}, {region[3]}]（字体单位 /1000 em）")
    print()
    print(f"{'版本':<8}{'接点':>6}{'中位':>8}{'P90':>8}{'角点':>6}{'端R_P50':>9}{'端R_P90':>9}"
          f"{'折R_P50':>9}{'折R_P90':>9}")
    for tag in ("母版", "本版", "对照"):
        if tag not in result:
            continue
        d = result[tag]
        j = d["区域接点"]
        print(f"{tag:<8}{j['接点数']:>6}{j['中位']:>8.2f}{j['P90']:>8.2f}{j['被排除的角点数']:>6}"
              f"{d['端头半径_P50']:>9.1f}{d['端头半径_P90']:>9.1f}"
              f"{(d['折角半径_P50'] or 0):>9.1f}{(d['折角半径_P90'] or 0):>9.1f}")
    print()
    for tag in ("母版", "本版", "对照"):
        if tag not in result:
            continue
        d = result[tag]
        print(f"{tag} 横带 y={d['横带']['y']} 厚={d['横带']['厚']} 两横={d['横带']['两横']}")
        print("   四端：" + "  ".join(f"横{e['横']}{e['端']}@({e['x']},{e['y']}) h={e['端面高']} R={e['半径']}"
                                    for e in d["端头"]))
        print("   折角：" + ("  ".join(f"@{c['x']} 空象限墨={c['空象限墨']}u² r={c['半径']}" for c in d["折角"])
                            or "无"))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nJSON → {args.json}")


if __name__ == "__main__":
    main()
