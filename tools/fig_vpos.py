"""把「字在行里坐没坐正」画出来：竖向墨心 vs 设计中线，修复前后同字同字号并排。

和 `fig_hpos.py` 的分工：那个画横向（墨心到 x=500），这个画竖向（墨心到设计中线 377.5）。
一张字身格里同时能读出两件事：左右偏多少（红竖线对灰虚线）、上下偏多少（红横线对灰横虚线）。

画四样（每格）：
- 灰框：字身格（宽 = advance，高 = 1000 单位），灰横虚线 = 设计中线（满宽满高字墨心中位数）
- 红横线：墨迹上下界 yMin / yMax
- 绿点：墨心 (yMin+yMax)/2，它就是 `tools/fix_vpos.py` 要挪回中线的那一点
- 每格脚注：dcy = 墨心 − 设计中线（单位：em/1000）

用法：
    python tools/fig_vpos.py --before 只修横向.ttf --after 横竖都修.ttf --mode grid \\
        --chars "羽雨平幵珥研國日田回" --out 图.png
    ... --mode overlay / text / dist
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

INK = (26, 26, 26)
GREY = (170, 170, 170)
MID = (120, 120, 120)
BLUE = (36, 104, 210)
RED = (214, 40, 40)
GREEN = (16, 140, 90)
GHOST = (200, 200, 200)


def box_of(font: TTFont, cmap: dict, ch: str):
    name = cmap.get(ord(ch))
    if name is None:
        return None
    glyph = font["glyf"][name]
    if glyph.numberOfContours == 0:
        return None
    glyph.recalcBounds(font["glyf"])
    return glyph, name, (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax)


def master_boxes() -> dict[int, tuple[int, int, int, int]]:
    """`tools/master_box.bin` 的字面框（去残墨）。没有就退回空表。"""
    try:
        from box_align import load
        return load()
    except Exception:
        return {}


def metrics(path: Path, chars: str, boxes: dict | None = None,
            ref: Path | None = None) -> dict[str, dict]:
    """每字的框与 advance。

    `boxes` 是母版字面框：给了就用它当「真框」（去掉 `日` 右上角那种残墨）。
    修过的字体坐标整体平移过，所以 `ref` 给原字体时按「本字体 glyf 框 − 原字体 glyf 框」
    求出实际位移，再加到母版框上——这样两行的 dcy 是同一把尺子量的。
    """
    boxes = boxes or {}
    out: dict[str, dict] = {}
    base: dict[str, tuple[float, float]] = {}
    if ref is not None:
        with TTFont(str(ref), lazy=True) as rf:
            rcmap = rf.getBestCmap()
            for ch in chars:
                got = box_of(rf, rcmap, ch)
                base[ch] = (0.0, 0.0) if got is None else ((got[2][1] + got[2][3]) / 2,
                                                           got[2][1])
    with TTFont(str(path), lazy=True) as f:
        cmap = f.getBestCmap()
        for ch in chars:
            got = box_of(f, cmap, ch)
            if got is None:
                out[ch] = None
                continue
            glyph, name, box = got
            box = list(box)
            mb = boxes.get(ord(ch))
            if mb is not None:
                dy = 0.0
                if ref is not None:
                    dy = (box[1] + box[3]) / 2 - base[ch][0]
                box[1], box[3] = mb[1] + dy, mb[3] + dy
                box[0], box[2] = mb[0], mb[2]
            out[ch] = {"box": tuple(box), "adv": f["hmtx"][name][0]}
    return out


def design_centre(path: Path) -> float:
    tall = []
    with TTFont(str(path), lazy=True) as f:
        cmap, glyf = f.getBestCmap(), f["glyf"]
        for cp, name in cmap.items():
            if not (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF):
                continue
            g = glyf[name]
            if g.numberOfContours <= 0:
                continue
            if g.xMax - g.xMin >= 850 and g.yMax - g.yMin >= 850:
                tall.append((g.yMin + g.yMax) / 2)
    return statistics.median(tall)


def draw_cell(d: ImageDraw.ImageDraw, img_font: ImageFont.FreeTypeFont, ch: str, meta: dict,
         x0: int, base: int, cell_px: int, centre_units: float, colour=INK,
         ghost_meta: dict | None = None, ghost_font=None, label=None, lab_font=None,
         guides: bool = True) -> None:
    ppu = cell_px / 1000
    fpx = max(4, int(round(1000 * ppu)))
    adv = meta["adv"] if meta else 1000
    top = base - 1000 * ppu
    if guides:
        d.rectangle([x0, top, x0 + adv * ppu, base], outline=GREY, width=2)
        cy_px = base - centre_units * ppu
        for xx in range(int(x0), int(x0 + adv * ppu), 14):
            d.line([xx, cy_px, min(xx + 7, x0 + adv * ppu), cy_px], fill=MID, width=1)
        for xx in range(int(x0), int(x0 + adv * ppu), 14):
            d.line([xx, base, min(xx + 7, x0 + adv * ppu), base], fill=BLUE, width=2)
    if ghost_meta is not None and ghost_font is not None:
        d.text((x0, base), ch, font=ImageFont.truetype(str(ghost_font), fpx), fill=GHOST, anchor="ls")
    d.text((x0, base), ch, font=img_font, fill=colour, anchor="ls")
    if guides and meta:
        x_min, y_min, x_max, y_max = meta["box"]
        d.line([x0, base - y_max * ppu, x0 + adv * ppu, base - y_max * ppu], fill=RED, width=1)
        d.line([x0, base - y_min * ppu, x0 + adv * ppu, base - y_min * ppu], fill=RED, width=1)
        cx = x0 + (x_min + x_max) / 2 * ppu
        cy = base - (y_min + y_max) / 2 * ppu
        d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=GREEN)
    if label and lab_font is not None:
        d.text((x0 + 2, base + 8), label, font=lab_font, fill=MID)


def draw_dist(before: Path, after: Path, out: Path) -> None:
    def devs(path: Path):
        vals = []
        with TTFont(str(path), lazy=True) as f:
            cmap, glyf = f.getBestCmap(), f["glyf"]
            for cp, name in cmap.items():
                if not (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF):
                    continue
                g = glyf[name]
                if g.numberOfContours <= 0:
                    continue
                if g.xMax - g.xMin >= 850 and g.yMax - g.yMin >= 850:
                    vals.append((g.yMin + g.yMax) / 2)
        c = statistics.median(vals)
        return [abs(v - c) for v in vals], c

    a, ca = devs(before)
    b, cb = devs(after)
    bins = list(range(0, 55, 5))
    ha = [sum(1 for v in a if lo <= v < lo + 5) for lo in bins]
    hb = [sum(1 for v in b if lo <= v < lo + 5) for lo in bins]
    W, H = 1660, 720
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_t = ImageFont.truetype(str(before), 30)
    f_s = ImageFont.truetype(str(before), 21)
    f_x = ImageFont.truetype(str(before), 17)
    d.text((60, 18), "母版竖向定位：满宽满高字 |墨心−设计中线| 分布，修复前 / 修复后", font=f_t, fill=INK)
    d.text((60, 58), f"{len(a):,} 个字（墨宽 ≥850、墨高 ≥850）；设计中线 "
                     f"{ca:.1f}；纵轴=字数，横轴=|dcy| 单位（em/1000）", font=f_s, fill=(110, 110, 110))
    x0, y0, w, h = 110, H - 120, 1300, 430
    peak = max(max(ha), max(hb)) or 1
    d.line([x0, y0, x0 + w, y0], fill=GREY, width=2)
    d.line([x0, y0, x0, y0 - h - 20], fill=GREY, width=2)
    bw = w / len(bins)
    for i, lo in enumerate(bins):
        for val, colour, off in ((ha[i], (150, 150, 150), 0), (hb[i], (36, 104, 210), bw / 2)):
            hh = (val / peak) * h
            d.rectangle([x0 + i * bw + off, y0 - hh, x0 + i * bw + off + bw / 2 - 2, y0], fill=colour)
        d.text((x0 + i * bw + 4, y0 + 8), f"{lo}", font=f_x, fill=(90, 90, 90))
    d.text((x0 + w - 60, y0 + 30), "|dcy|", font=f_x, fill=(90, 90, 90))
    for yy, val in ((y0 - h, peak), (y0 - h / 2, peak // 2), (y0, 0)):
        d.text((x0 - 60, yy - 8), f"{val:,}", font=f_x, fill=(90, 90, 90))
    for row, (label, vals, colour, raw) in enumerate((("只修横向", ha, (150, 150, 150), a),
                                                     ("横竖都修", hb, (36, 104, 210), b))):
        over = sum(1 for v in raw if v > 20)
        d.rectangle([1010, 130 + row * 60, 1034, 154 + row * 60], fill=colour)
        d.text((1044, 128 + row * 60),
               f"{label}：|dcy|>20 共 {over:,} 字（{100*over/len(raw):.2f}%）  最大 {max(raw):.1f}",
               font=f_s, fill=INK)
    img.save(out)
    print("写出", out, img.size)


def main() -> None:
    ap = argparse.ArgumentParser(description="母版竖向定位（墨心 vs 设计中线）修复前后对照图")
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--after", type=Path, required=True)
    ap.add_argument("--chars", default="羽雨平幵珥研國日田回")
    ap.add_argument("--mode", choices=("grid", "text", "overlay", "dist"), default="grid")
    ap.add_argument("--cell", type=int, default=230)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--centre", type=float, default=None,
                    help="设计中线（默认按 --before 现算）；量自版预览件时给母版的 377.5，"
                         "两边才是同一把尺子")
    ap.add_argument("--what", default="母版", help="标题里的主语：母版 / 自版")
    ap.add_argument("--label-font", type=Path, default=None,
                    help="写标题/脚注用的字体（默认用 --before）；量自版预览件时要给母版，"
                         "否则预览件里没有汉字，标题全是空白")
    ap.add_argument("--no-table", action="store_true",
                    help="不用母版字面框表，直接量本字体 glyf 框（量自版字体时用）")
    args = ap.parse_args()

    if args.mode == "dist":
        draw_dist(args.before, args.after, args.out)
        return

    chars, cell = args.chars, args.cell
    centre = args.centre if args.centre is not None else design_centre(args.before)
    boxes = {} if args.no_table else master_boxes()
    mb = metrics(args.before, chars, boxes)
    ma = metrics(args.after, chars, boxes, ref=args.before)
    rows = {"grid": ["只修横向（dcy 未修）", "横竖都修"], "text": ["只修横向", "横竖都修"],
            "overlay": ["叠影：灰=只修横向，黑=横竖都修"]}[args.mode]
    pad = 34
    W = pad * 2 + len(chars) * (cell + 8)
    row_h = cell + 64
    H = 190 + len(rows) * row_h + 26
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    lab_src = str(args.label_font or args.before)
    f_title = ImageFont.truetype(lab_src, 30)
    f_sub = ImageFont.truetype(lab_src, 20)
    f_lab = ImageFont.truetype(lab_src, 17)
    f_small = ImageFont.truetype(lab_src, 15)

    title = {"grid": f"{args.what}竖向定位：墨心（绿点）到设计中线（灰横虚线）的距离",
             "text": f"{args.what}竖向定位：同一段文字，修复前后同字号对照",
             "overlay": f"{args.what}竖向定位：同格叠影，看得见往上/往下挪"}[args.mode]
    d.text((pad, 18), title, font=f_title, fill=INK)
    d.text((pad, 58), "灰框=字身格(advance×1000)　灰横虚线=设计中线　红横线=墨迹上下界　蓝线=基线　绿点=墨心",
           font=f_sub, fill=(110, 110, 110))
    d.text((pad, 88), f"字号 {cell}px，字格 1000 单位；设计中线 {centre:.1f}；"
                      f"每格下方 dcy=墨心−中线", font=f_small, fill=(150, 150, 150))

    for ri, name in enumerate(rows):
        top = 190 + ri * row_h
        d.text((pad, top - 26), name, font=f_lab, fill=(70, 70, 70))
        base = top + cell - 16
        for ci, ch in enumerate(chars):
            x0 = pad + ci * (cell + 8)
            if args.mode == "grid":
                meta = mb[ch] if ri == 0 else ma[ch]
                val = 0.0 if not meta else (meta["box"][1] + meta["box"][3]) / 2 - centre
                draw_cell(d, ImageFont.truetype(str(args.before if ri == 0 else args.after), max(4, int(cell))),
                     ch, meta, x0, base, cell, centre, INK, label=f"dcy {val:+.0f}", lab_font=f_small)
            elif args.mode == "text":
                path = args.before if ri == 0 else args.after
                meta = mb[ch] if ri == 0 else ma[ch]
                draw_cell(d, ImageFont.truetype(str(path), max(4, int(cell))), ch, meta,
                     x0, base, cell, centre, INK, guides=False)
            else:
                meta = ma[ch]
                val = 0.0 if not meta else (meta["box"][1] + meta["box"][3]) / 2 - centre
                gval = 0.0 if not mb[ch] else (mb[ch]["box"][1] + mb[ch]["box"][3]) / 2 - centre
                draw_cell(d, ImageFont.truetype(str(args.after), max(4, int(cell))), ch, meta,
                     x0, base, cell, centre, INK, ghost_meta=mb[ch], ghost_font=args.before,
                     label=f"{gval:+.0f} → {val:+.0f}", lab_font=f_small)
    img.save(args.out)
    print("写出", args.out, img.size)


if __name__ == "__main__":
    main()
