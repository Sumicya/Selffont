"""五条判据的量具：把「本版 vs 母版」的差量成数，不再用观感词。

五条（每轮都报同一套，不许换口径）：

1. **逐字轮廓距离**：每个字取「四方向 Hausdorff」。对本版轮廓上每一点 a、方向 d ∈ {+x,−x,+y,−y}，
   沿 d 走到母版轮廓的最小距离 `min_{b: (b−a)·d ≥ 0} (b−a)·d`；一个字取这四个方向的最大值。
   报 P50 / P90 / P99（单位 = em 的 1/1000）。
2. **笔画宽度**：512 px/em 用 FreeType 栅格（与 `docs/design-principles.md` 2026-10-28 同一条：
   自制渲染器不算验收），逐行取墨迹游程中位 = 竖笔宽，逐列 = 横笔宽；比值 = 本版 / 母版。
   报 |比值 − 1| 的 P50 / P90 / P95，横竖分别报。
3. **侧距**：`hmtx` 逐字差（lsb 与 advance 各一份），报 |diff| ≤ 20 单位的占比，以及 |diff| 的 P50/P90。
4. **曲线连续性**：相邻段接点处，前段末切向与后段首切向的夹角（度）。转角落差 > 60° 的按
   「角点」排除（母版与本体都排除，口径一致）。逐字取均值，报全库中位与 P90，**并报相对
   母版的增量**（本版中位 − 母版中位）。不设「母版 + 某度」这种阈值：母版自己就有 4.36°，
   增量是唯一能跨字体、跨轮次比较的量。
5. **渲染对照**：12 / 16 / 24 px 三档、同一批 20 字，母版一排、本版一排；像素按 3× 最近邻放大
   （等价 3x 屏幕上看见的密度，不引入重采样模糊）。输出 PNG 由调用方贴进回复。

用法：

    python tools/metrics.py --ours build/metrics/ours3500/preview.ttf \
        --mother build/mother/MarukoGothicCJKsc-Regular.ttf \
        --chars /tmp/gb3500.txt --render docs/evidence/metrics-baseline.png

    python tools/metrics.py --baseline --mother ...        # 母版 vs 母版：基准（应全 0 / 比值 1.000）

「母版直通」版本的基准值由 `--baseline` 跑出来：距离 0、比值 1.000、侧距 100%、
切向 = 母版自身。任何改动都对着这组数比，不对着感觉比。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

JUMP_CORNER = 60.0      # 超过这个角度的接点按角点排除（直角、锐角都是设计，不是缺陷）
N_CURVE_SAMPLES = 8     # 曲线展平：每段取样点数（与尺子的分辨率匹配）


def _flatten(glyph, glyph_set):
    """把轮廓展平成 [(x, y), …] 与分段 [(起点切向, 终点切向)]。

    二次曲线按 TrueType 规范处理连续 off 控制点（相邻控制点中点为隐含 on 点）——
    2026-10-31 那一轮就是在这里把 `e` 的环展开错了，`te` 宽了 46 单位。
    """
    pen = DecomposingRecordingPen(glyph_set)
    glyph.draw(pen)
    points: list[tuple[float, float]] = []
    tangents: list[tuple[tuple[float, float], tuple[float, float]]] = []
    cur = (0.0, 0.0)

    def unit(vx, vy):
        n = math.hypot(vx, vy)
        return (vx / n, vy / n) if n > 1e-9 else (0.0, 0.0)

    for op, args in pen.value:
        if op == "moveTo":
            cur = args[0]
            points.append(cur)
        elif op == "lineTo":
            nxt = args[0]
            tangents.append((unit(nxt[0] - cur[0], nxt[1] - cur[1]),
                             unit(nxt[0] - cur[0], nxt[1] - cur[1])))
            for k in range(1, N_CURVE_SAMPLES + 1):
                t = k / N_CURVE_SAMPLES
                points.append((cur[0] + (nxt[0] - cur[0]) * t, cur[1] + (nxt[1] - cur[1]) * t))
            cur = nxt
        elif op == "qCurveTo":
            *controls, end = args
            if end is None:      # 闭合轮廓的写法
                end = controls.pop(0) if controls else cur
            ctrl = list(controls)
            prev = cur
            while ctrl:
                c = ctrl.pop(0)
                nxt = ctrl[0] if ctrl else end
                if not ctrl:
                    e = end
                else:
                    e = ((c[0] + ctrl[0][0]) / 2, (c[1] + ctrl[0][1]) / 2)
                tangents.append((unit(c[0] - prev[0], c[1] - prev[1]),
                                 unit(e[0] - c[0], e[1] - c[1])))
                for k in range(1, N_CURVE_SAMPLES + 1):
                    t = k / N_CURVE_SAMPLES
                    x = (1 - t) ** 2 * prev[0] + 2 * (1 - t) * t * c[0] + t * t * e[0]
                    y = (1 - t) ** 2 * prev[1] + 2 * (1 - t) * t * c[1] + t * t * e[1]
                    points.append((x, y))
                prev = e
            cur = end
        elif op == "curveTo":
            c1, c2, end = args[-3], args[-2], args[-1]
            tangents.append((unit(c1[0] - cur[0], c1[1] - cur[1]),
                             unit(end[0] - c2[0], end[1] - c2[1])))
            for k in range(1, N_CURVE_SAMPLES + 1):
                t = k / N_CURVE_SAMPLES
                x = ((1 - t) ** 3 * cur[0] + 3 * (1 - t) ** 2 * t * c1[0]
                     + 3 * (1 - t) * t * t * c2[0] + t ** 3 * end[0])
                y = ((1 - t) ** 3 * cur[1] + 3 * (1 - t) ** 2 * t * c1[1]
                     + 3 * (1 - t) * t * t * c2[1] + t ** 3 * end[1])
                points.append((x, y))
            cur = end
        elif op == "closePath":
            cur = points[0] if points else cur
    return np.asarray(points, dtype=float), tangents


def directional_hausdorff(a: np.ndarray, b: np.ndarray) -> float:
    """四方向 Hausdorff：沿 ±x / ±y 从 a 的每一点走到 b 的最小距离，取四者最大。"""
    if len(a) == 0 or len(b) == 0:
        return float("inf")
    worst = 0.0
    for axis in (0, 1):
        for sign in (1, -1):
            av = a[:, axis] * sign
            bv = np.sort(b[:, axis] * sign)
            # 每个 a 点：bv 里 >= av 的最小值，减 av
            idx = np.searchsorted(bv, av, side="left")
            ok = idx < len(bv)
            if not ok.any():
                continue
            d = bv[idx[ok]] - av[ok]
            # 方向不对（bv 全在 av 左边）时允许 0：那说明这一点被完全覆盖
            worst = max(worst, float(d.max()) if len(d) else 0.0)
    return worst


def stroke_widths(path: Path, ch: str, px_per_em: int = 256) -> tuple[float, float] | None:
    """横竖笔宽：竖笔按逐行游程（水平长度），横笔按逐列游程（垂直长度）。"""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(str(path), px_per_em)
    except OSError:
        return None
    canvas = Image.new("L", (px_per_em * 2, px_per_em * 2), 255)
    ImageDraw.Draw(canvas).text((px_per_em // 2, px_per_em // 2), ch, font=font, fill=0)
    ink = np.asarray(canvas) < 128
    if not ink.any():
        return None

    def runs(mask_1d):
        if not mask_1d.any():
            return []
        edges = np.diff(np.concatenate(([0], mask_1d.astype(int), [0])))
        starts = np.where(edges == 1)[0]
        ends = np.where(edges == -1)[0]
        return (ends - starts).tolist()

    horizontal_runs: list[int] = []   # 逐行 → 竖笔的宽度
    for row in ink:
        horizontal_runs.extend(runs(row))
    vertical_runs: list[int] = []     # 逐列 → 横笔的高度
    for col in ink.T:
        vertical_runs.extend(runs(col))
    if not horizontal_runs or not vertical_runs:
        return None
    return float(np.median(horizontal_runs)), float(np.median(vertical_runs))


def tangent_jumps(tangents) -> float | None:
    """相邻段接点的切向跳变：返回逐字均值（度），角点（> 60°）排除。"""
    angles = []
    for i in range(len(tangents) - 1):
        (_, end_dir) = tangents[i]
        (start_dir, _) = tangents[i + 1]
        if end_dir == (0.0, 0.0) or start_dir == (0.0, 0.0):
            continue
        dot = max(-1.0, min(1.0, end_dir[0] * start_dir[0] + end_dir[1] * start_dir[1]))
        deg = math.degrees(math.acos(dot))
        if deg <= JUMP_CORNER:
            angles.append(deg)
    return float(np.mean(angles)) if angles else None


def load_chars(path: Path | None, text: str | None, limit: int) -> list[str]:
    raw = path.read_text(encoding="utf-8") if path else (text or "")
    seen, out = set(), []
    for ch in raw:
        if ch in seen or ch.isspace():
            continue
        seen.add(ch)
        out.append(ch)
        if limit and len(out) >= limit:
            break
    return out


def pct(values, ps=(50, 90, 99)):
    if not values:
        return {f"P{p}": None for p in ps}
    arr = np.asarray(values, dtype=float)
    return {f"P{p}": float(np.percentile(arr, p)) for p in ps}


def render_compare(ours: Path, mother: Path, chars: list[str], out: Path,
                   sizes=(12, 16, 24), scale=3) -> Path:
    """三档字号 × 一批字，母版一排、本版一排。像素按整数倍最近邻放大（不引入重采样）。"""
    from PIL import Image, ImageDraw, ImageFont

    pad, gutter, label_w, row_gap = 6, 8, 34, 6
    tiles = []
    for size in sizes:
        cell_w = int(size * 1.5) + pad * 2
        cell_h = int(size * 1.7) + 4
        width = label_w + len(chars) * (cell_w + gutter) + 8
        for tag, path in (("M", mother), ("S", ours)):
            font = ImageFont.truetype(str(path), size)
            tile = Image.new("L", (width, cell_h), 255)
            pen = ImageDraw.Draw(tile)
            pen.text((2, 2), f"{tag}{size}", font=ImageFont.load_default(), fill=0)
            for i, ch in enumerate(chars):
                pen.text((label_w + i * (cell_w + gutter) + pad, 2), ch, font=font, fill=0)
            tiles.append((size, tag, tile))
    width = max(t.width for _, _, t in tiles)
    height = sum(t.height + row_gap for _, _, t in tiles) + 8
    canvas = Image.new("L", (width, height), 255)
    y = 4
    for _, _, tile in tiles:
        canvas.paste(tile, (0, y))
        y += tile.height + row_gap
    canvas = canvas.resize((canvas.width * scale, canvas.height * scale), Image.NEAREST)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def worst_jumps(ours_path: Path, mother_path: Path, chars: list[str], top: int = 5):
    """逐字切向跳变均值，返回 (本版最差 top 字, 母版同字的值)。

    4× 局部放大图就按这份名单挑字：只看跳变最大的几个，不挑「看起来有问题」的字。
    """
    ours = TTFont(str(ours_path), lazy=False)
    mother = TTFont(str(mother_path), lazy=False)
    o_cmap, m_cmap = ours.getBestCmap(), mother.getBestCmap()
    o_gs, m_gs = ours.getGlyphSet(), mother.getGlyphSet()
    rows = []
    for ch in chars:
        cp = ord(ch)
        if cp not in o_cmap or cp not in m_cmap:
            continue
        jo = tangent_jumps(_flatten(o_gs[o_cmap[cp]], o_gs)[1])
        jm = tangent_jumps(_flatten(m_gs[m_cmap[cp]], m_gs)[1])
        if jo is None:
            continue
        rows.append((jo, jm, ch))
    rows.sort(reverse=True)
    return [(ch, round(jo, 3), round(jm, 3) if jm is not None else None)
            for jo, jm, ch in rows[:top]]


def render_pixel_zoom(ours: Path, mother: Path, chars: list[str], out: Path,
                      size: int = 96, scale: int = 4, max_width: int = 900) -> Path:
    """局部放大图：只给最差的几个字，96 px 渲染、裁到墨迹、最近邻 4×，图宽不超过 900。

    这张图只用来判第 4 条（接点有没有硬折）。每行一个字：左母版、右本版，同一字号同一基线。
    行内的两块都按 4× 放大后再贴，所以看到的是 384 px 见方的字形，接点是不是折一目了然。
    """
    from PIL import Image, ImageDraw, ImageFont

    cell = size * scale
    label_w = 26
    width = min(max_width, label_w + cell + 8 + cell + 8)
    row_h = cell + 6
    canvas = Image.new("L", (width, row_h * len(chars) + 6), 255)
    pen = ImageDraw.Draw(canvas)

    def tile(path: Path, ch: str) -> Image.Image:
        font = ImageFont.truetype(str(path), size)
        pad = size
        raw = Image.new("L", (size + pad * 2, size + pad * 2), 255)
        ImageDraw.Draw(raw).text((pad, pad), ch, font=font, fill=0)
        box = raw.point(lambda v: 255 - v).getbbox()
        if box:
            left, top, right, bottom = box
            m = 3
            raw = raw.crop((max(left - m, 0), max(top - m, 0),
                            min(right + m, raw.width), min(bottom + m, raw.height)))
        return raw.resize((raw.width * scale, raw.height * scale), Image.NEAREST)

    tag_font = ImageFont.truetype(str(mother), 20)
    for row, ch in enumerate(chars):
        y = 3 + row * row_h
        box = pen.textbbox((0, 0), ch, font=tag_font)
        pen.text((4, y + (row_h - box[3]) / 2), ch, font=tag_font, fill=0)  # 默认字体没有汉字，标签用母版自己画
        for col, path in enumerate((mother, ours)):
            img = tile(path, ch)
            x = label_w + col * (cell + 8) + max((cell - img.width) // 2, 0)
            y2 = y + max((cell - img.height) // 2, 0)
            canvas.paste(img.crop((0, 0, min(img.width, cell), min(img.height, cell))), (x, y2))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def measure(ours_path: Path, mother_path: Path, chars: list[str],
            render_out: Path | None, sizes, scale) -> dict:
    mother = TTFont(str(mother_path), lazy=False)
    ours = TTFont(str(ours_path), lazy=False)
    m_cmap, o_cmap = mother.getBestCmap(), ours.getBestCmap()
    m_upem = mother["head"].unitsPerEm
    o_upem = ours["head"].unitsPerEm
    m_hmtx, o_hmtx = mother["hmtx"], ours["hmtx"]
    m_gs, o_gs = mother.getGlyphSet(), ours.getGlyphSet()

    haus, ratios_v, ratios_h, lsb_diff, adv_diff, jumps_o, jumps_m = [], [], [], [], [], [], []
    missing = 0
    for ch in chars:
        cp = ord(ch)
        if cp not in m_cmap or cp not in o_cmap:
            missing += 1
            continue
        mn, on = m_cmap[cp], o_cmap[cp]
        mp, mt = _flatten(m_gs[mn], m_gs)      # 母版只展平一次，切向复用
        op, ot = _flatten(o_gs[on], o_gs)
        if len(mp) == 0 or len(op) == 0:
            missing += 1
            continue
        mp = mp * (1000.0 / m_upem)
        op = op * (1000.0 / o_upem)
        haus.append(directional_hausdorff(op, mp))

        mv = stroke_widths(mother_path, ch)
        ov = stroke_widths(ours_path, ch)
        if mv and ov and mv[0] > 0 and mv[1] > 0:
            ratios_v.append(abs(ov[0] / mv[0] - 1.0))
            ratios_h.append(abs(ov[1] / mv[1] - 1.0))

        m_adv, m_lsb = m_hmtx[mn]
        o_adv, o_lsb = o_hmtx[on]
        lsb_diff.append(abs(o_lsb - m_lsb))
        adv_diff.append(abs(o_adv - m_adv))

        jo = tangent_jumps(ot)
        jm = tangent_jumps(mt)
        if jo is not None:
            jumps_o.append(jo)
        if jm is not None:
            jumps_m.append(jm)

    within_lsb = sum(1 for d in lsb_diff if d <= 20) / len(lsb_diff) * 100 if lsb_diff else 0.0
    within_adv = sum(1 for d in adv_diff if d <= 20) / len(adv_diff) * 100 if adv_diff else 0.0
    result = {
        "字数": {"要求": len(chars), "实算": len(haus), "缺": missing},
        "1_逐字轮廓距离": pct(haus),
        "2_笔画宽度": {
            "竖笔|比值-1|": pct(ratios_v, (50, 90, 95)),
            "横笔|比值-1|": pct(ratios_h, (50, 90, 95)),
        },
        "3_侧距": {
            "lsb|diff|≤20_占比": round(within_lsb, 2),
            "advance|diff|≤20_占比": round(within_adv, 2),
            "lsb|diff|": pct(lsb_diff, (50, 90)),
        },
        "4_曲线连续性": {
            "本版中位": round(float(np.median(jumps_o)), 3) if jumps_o else None,
            "本版P90": round(float(np.percentile(jumps_o, 90)), 3) if jumps_o else None,
            "母版中位": round(float(np.median(jumps_m)), 3) if jumps_m else None,
            "母版P90": round(float(np.percentile(jumps_m, 90)), 3) if jumps_m else None,
        },
    }
    if jumps_o and jumps_m:
        result["4_曲线连续性"]["差值"] = round(float(np.median(jumps_o) - np.median(jumps_m)), 3)
    if render_out is not None:
        render_compare(ours_path, mother_path, chars[:20], render_out, sizes=sizes, scale=scale)
        result["5_渲染对照"] = str(render_out)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ours", type=Path, help="本版字体；--baseline 时可省")
    parser.add_argument("--mother", type=Path, required=True, help="母版 TTF（钉住 sha256）")
    parser.add_argument("--chars", type=Path, help="字表文件（UTF-8，一行或整段都行）")
    parser.add_argument("--text", help="直接给字串（与 --chars 二选一）")
    parser.add_argument("--limit", type=int, default=3500, help="最多量多少字（默认 3500）")
    parser.add_argument("--baseline", action="store_true", help="母版 vs 母版：基准值")
    parser.add_argument("--render", type=Path, help="渲染对照 PNG 输出路径")
    parser.add_argument("--sizes", default="12,16,24", help="渲染档位（px，默认 12,16,24）")
    parser.add_argument("--scale", type=int, default=3, help="像素放大倍数（最近邻，默认 3）")
    parser.add_argument("--json", type=Path, help="把结果同时写成 JSON")
    parser.add_argument("--worst-jumps", type=int, default=0,
                        help="列出切向跳变最大的 N 个字（给 4× 局部放大图挑字）")
    parser.add_argument("--pixel-zoom", type=Path,
                        help="出 4× 局部放大图（96 px 渲染、图宽 ≤900、文件名带 -pixel）")
    args = parser.parse_args()

    ours = args.mother if args.baseline else args.ours
    if ours is None:
        parser.error("要么给 --ours，要么给 --baseline")
    chars = load_chars(args.chars, args.text, args.limit)
    sizes = tuple(int(s) for s in args.sizes.split(","))
    result = measure(ours, args.mother, chars, args.render, sizes, args.scale)
    if args.worst_jumps:
        worst = worst_jumps(ours, args.mother, chars, args.worst_jumps)
        result["最差切向跳变"] = [{"字": ch, "本版": j, "母版": m} for ch, j, m in worst]
        if args.pixel_zoom:
            assert "-pixel" in args.pixel_zoom.name, "局部放大图的文件名要带 -pixel"
            render_pixel_zoom(ours, args.mother, [ch for ch, _, _ in worst], args.pixel_zoom)
            result["4×局部放大图"] = str(args.pixel_zoom)
    result["母版"] = str(args.mother)
    result["本版"] = str(ours)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
