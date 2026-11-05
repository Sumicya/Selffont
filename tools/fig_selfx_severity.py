"""把「真缺口」画出来：左母版、右本版，红圈＝环面积差 > 阈值的自交点。

与 tools/selfx_severity.py 同一套判定（shapely 多边形有效性 + 环面积差分级），
只画被判「真缺口」的那些点，毛刺不画——毛刺看不见，画上去只会把图弄脏。

用法
----
    python tools/fig_selfx_severity.py --master 母版.ttf --ours 本版.ttf \
        --chars "館尸胈門限鴸鶠覸鸈" --out 图.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import shapely.geometry as sg
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_self_intersect import FlattenPen, check_glyph  # noqa: E402
from selfx_severity import SLIVER_AREA, SLIVER_RATIO  # noqa: E402

INK = (24, 24, 24)
RED = (214, 32, 32)
GREY = (150, 150, 150)


def contour_data(path: Path, ch: str):
    with TTFont(str(path), lazy=True) as font:
        cmap = font.getBestCmap()
        if ord(ch) not in cmap:
            return None, [], []
        pen = FlattenPen(font.getGlyphSet())
        font.getGlyphSet()[cmap[ord(ch)]].draw(pen)
        bad, _ = check_glyph(font, cmap[ord(ch)])
        real = []
        for ci in bad:
            poly = sg.Polygon(pen.contours[ci])
            if poly.is_valid:
                continue
            delta = abs(poly.area) - poly.buffer(0).area
            if delta > SLIVER_AREA:
                real.append((ci, delta, poly))
    return pen.contours, bad, real


def crossing_points(poly):
    """把无效多边形拆成线段后的重复端点，即自交点。"""
    from shapely.ops import unary_union
    line = sg.LineString(list(poly.exterior.coords))
    parts = unary_union(line)
    seen, out = {}, []
    for g in (parts.geoms if hasattr(parts, "geoms") else [parts]):
        for c in g.coords:
            key = (round(c[0], 1), round(c[1], 1))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 1:
                out.append(key)
    return [p for p, n in seen.items() if n > 1]


def draw_cell(img, d, path, ch, box, marks, label, label_font):
    x0, y0, w, h = box
    contours, _, _ = contour_data(path, ch)
    if contours is None:
        d.text((x0 + 8, y0 + 8), f"{ch} 缺字", font=label_font, fill=GREY)
        return
    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    scale = min(w / (bx1 - bx0), h / (by1 - by0)) * 0.90
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2

    def T(p):
        return (x0 + w / 2 + (p[0] - cx) * scale, y0 + h / 2 - (p[1] - cy) * scale)

    f = ImageFont.truetype(str(path), int(1000 * scale))
    cell = Image.new("L", (int(w * 1.8), int(h * 1.8)), 255)
    ImageDraw.Draw(cell).text((cell.size[0] // 2, cell.size[1] // 2), ch, font=f, fill=0, anchor="mm")
    bb = cell.point(lambda v: 255 - v).getbbox()
    if bb:
        cell = cell.crop(bb)
        img.paste(cell, (int(x0 + w / 2 - cell.size[0] / 2), int(y0 + h / 2 - cell.size[1] / 2)))
    for p in marks:
        x, y = T(p)
        r = 13
        d.ellipse([x - r, y - r, x + r, y + r], outline=RED, width=4)
    d.text((x0 + 6, y0 - 34), label, font=label_font, fill=(60, 60, 60))


def main() -> None:
    ap = argparse.ArgumentParser(description="画真自交：母版 vs 本版，红圈标自交点")
    ap.add_argument("--master", type=Path, required=True)
    ap.add_argument("--ours", type=Path, required=True)
    ap.add_argument("--chars", default="館尸胈門限鴸鶠覸鸈")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cell", type=int, default=210)
    ap.add_argument("--cols", type=int, default=9)
    args = ap.parse_args()

    chars = args.chars
    n = len(chars)
    cols = min(args.cols, n)
    rows = (n + cols - 1) // cols
    W = 100 + cols * (args.cell + 16)
    H = 250 + rows * 2 * (args.cell + 28)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(str(args.master), 40)
    f_lab = ImageFont.truetype(str(args.master), 26)
    f_s = ImageFont.truetype(str(args.master), 23)

    d.text((40, 26), "真自交长在哪：上排母版、下排本版，红圈＝环面积差超阈的自交点", font=f_title, fill=INK)
    d.text((40, 78), "毛刺（面积差 ≤10 平方单位）不画；本图只画 9 个真缺口", font=f_s, fill=(120, 120, 120))

    for i, ch in enumerate(chars):
        r, c = divmod(i, cols)
        x = 44 + c * (args.cell + 16)
        ytop = 150 + r * 2 * (args.cell + 28)
        draw_cell(img, d, args.master, ch, (x, ytop, args.cell, args.cell), [], "母版", f_lab)
        _, _, real = contour_data(args.ours, ch)
        marks = []
        for ci, delta, poly in real:
            marks.extend(crossing_points(poly))
        lab = "本版 " + f"{ch} 真缺口" if real else f"本版 {ch} 干净"
        draw_cell(img, d, args.ours, ch, (x, ytop + args.cell + 28, args.cell, args.cell),
                  marks, lab, f_lab)

    img.save(args.out)
    print("写出", args.out, img.size)


if __name__ == "__main__":
    main()
