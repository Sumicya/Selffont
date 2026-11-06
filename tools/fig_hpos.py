"""把「母版墨心偏出字格中线」画出来：修复前 / 修复后 / 叠影，同字同字号并排。

为什么要有这个图
----------------
2026-11-06 的 `2026-11-06-hpos-text.png` 是整段文字对照，1 倍，看得到「有字发飘」但读不出
偏了多少。主人要的是**重定位图**：每格画字身格、500 中线、墨心点，修复前后叠在一起，
一眼能读出「往哪边偏、偏了几个单位」。

画三样（每格）：
- 灰框：字身格（宽 = advance，高 = 1000 单位），灰虚线 = 字格中线 x=500
- 红竖线：墨迹左右边界 xMin / xMax
- 绿点：墨心 (xMin+xMax)/2，它就是 `tools/fix_hpos.py` 要挪到 500 上的那个点
- 每格脚注：dcx = 墨心 − 500（单位：em/1000）

三种模式：
    python tools/fig_hpos.py --master 母版.ttf --fixed 修复.ttf --mode grid \\
        --chars "匕名爿㔾乁扁門國團" --out 图.png
    python tools/fig_hpos.py --master 母版.ttf --fixed 修复.ttf --mode text \\
        --chars "春眠不觉晓" --out 图.png
    python tools/fig_hpos.py --master 母版.ttf --fixed 修复.ttf --mode overlay \\
        --chars "匕名爿㔾" --out 图.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

INK = (26, 26, 26)
GREY = (170, 170, 170)
MID = (120, 120, 120)
BLUE = (36, 104, 210)
RED = (214, 40, 40)
GREEN = (16, 140, 90)
GHOST = (198, 198, 198)


def glyph_box(font: TTFont, cmap: dict, ch: str):
    gname = cmap.get(ord(ch))
    if gname is None:
        return None, None, None
    glyf = font["glyf"]
    g = glyf[gname]
    if g.numberOfContours == 0:
        return None, None, None
    g.recalcBounds(glyf)
    return g, gname, (g.xMin, g.yMin, g.xMax, g.yMax)


def dcx_table(path: Path, chars: str) -> dict[str, float]:
    """每个字的 dcx = (xMin+xMax)/2 − 500。一次读表，别在画图时反复开字体。"""
    out: dict[str, float] = {}
    with TTFont(str(path), lazy=True) as f:
        cmap = f.getBestCmap()
        for ch in chars:
            _, _, bb = glyph_box(f, cmap, ch)
            out[ch] = 0.0 if not bb else (bb[0] + bb[2]) / 2 - 500
    return out


def draw_cell(img: Image.Image, d: ImageDraw.ImageDraw, path: Path, ch: str,
              x0: int, base: int, cell: int, colour=INK, ghost: Path | None = None,
              label: str | None = None, lab_font=None, show_guides: bool = True) -> None:
    ppu = cell / 1000
    fpx = max(4, int(round(1000 * ppu)))
    with TTFont(str(path), lazy=True) as f:
        cmap = f.getBestCmap()
        hmtx, hhea = f["hmtx"], f["hhea"]
        adv = 1000
        gname = cmap.get(ord(ch))
        if gname:
            adv = hmtx[gname][0]
        g, _, bb = glyph_box(f, cmap, ch)
        if show_guides:
            d.rectangle([x0, base - 1000 * ppu, x0 + adv * ppu, base], outline=GREY, width=2)
            for yy in range(int(base - 1000 * ppu), int(base), 14):
                d.line([x0 + 500 * ppu, yy, x0 + 500 * ppu, min(yy + 7, base)], fill=MID, width=1)
            d.line([x0, base, x0 + adv * ppu, base], fill=BLUE, width=2)
            if bb:
                d.line([x0 + bb[0] * ppu, base - 16, x0 + bb[0] * ppu, base + 16], fill=RED, width=2)
                d.line([x0 + bb[2] * ppu, base - 16, x0 + bb[2] * ppu, base + 16], fill=RED, width=2)
        if ghost is not None:
            with TTFont(str(ghost), lazy=True) as gf:
                d.text((x0, base), ch, font=ImageFont.truetype(str(ghost), fpx), fill=GHOST, anchor="ls")
        d.text((x0, base), ch, font=ImageFont.truetype(str(path), fpx), fill=colour, anchor="ls")
        if show_guides and bb:
            cx = x0 + (bb[0] + bb[2]) / 2 * ppu
            cy = base - (bb[1] + bb[3]) / 2 * ppu
            r = 5
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
        if label and lab_font is not None:
            d.text((x0 + 2, base + 10), label, font=lab_font, fill=MID)


def main() -> None:
    ap = argparse.ArgumentParser(description="母版定位（墨心 vs 字格中线）修复前后对照图")
    ap.add_argument("--master", type=Path, required=True, help="母版原样")
    ap.add_argument("--fixed", type=Path, required=True, help="fix_hpos.py 输出的修复件")
    ap.add_argument("--chars", default="匕名爿㔾乁扁門國團日田回")
    ap.add_argument("--mode", choices=("grid", "text", "overlay"), default="grid")
    ap.add_argument("--cell", type=int, default=190, help="每格像素边长（1 倍）")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    chars = args.chars
    m_dcx = dcx_table(args.master, chars)
    x_dcx = dcx_table(args.fixed, chars)

    rows = {"grid": ["母版原样", "定位修复后"], "text": ["母版原样", "定位修复后"],
            "overlay": ["叠影：灰=母版原样，黑=定位修复后"]}[args.mode]
    cell = args.cell
    n = len(chars)
    pad = 34
    W = pad * 2 + n * (cell + 8)
    row_h = cell + 64
    H = 186 + len(rows) * row_h + 30
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(str(args.master), 30)
    f_sub = ImageFont.truetype(str(args.master), 20)
    f_lab = ImageFont.truetype(str(args.master), 17)
    f_small = ImageFont.truetype(str(args.master), 15)

    title = {"grid": "母版定位：墨心（绿点）到字格中线（灰虚线）的距离",
             "text": "母版定位：同一段文字，修复前后同字号对照",
             "overlay": "母版定位：同一格内叠影，看得见往哪边挪"}[args.mode]
    d.text((pad, 18), title, font=f_title, fill=INK)
    d.text((pad, 58), "灰框=字身格(advance×1000)　蓝线=基线　红竖线=墨迹左右界　绿点=墨心　每格下方 dcx=墨心−500",
           font=f_sub, fill=(110, 110, 110))
    d.text((pad, 108), f"字号 {cell}px，字格 1000 单位；{args.master.name} → {args.fixed.name}",
           font=f_small, fill=(150, 150, 150))

    for ri, name in enumerate(rows):
        top = 186 + ri * row_h
        d.text((pad, top - 26), name, font=f_lab, fill=(70, 70, 70))
        base = top + cell - 18
        for ci, ch in enumerate(chars):
            x0 = pad + ci * (cell + 8)
            if args.mode == "grid":
                path = args.master if ri == 0 else args.fixed
                v = m_dcx[ch] if ri == 0 else x_dcx[ch]
                draw_cell(img, d, path, ch, x0, base, cell, INK,
                          label=f"dcx {v:+.0f}", lab_font=f_small)
            elif args.mode == "text":
                path = args.master if ri == 0 else args.fixed
                draw_cell(img, d, path, ch, x0, base, cell, INK)
            else:
                draw_cell(img, d, args.fixed, ch, x0, base, cell, INK,
                          ghost=args.master,
                          label=f"{m_dcx[ch]:+.0f} → {x_dcx[ch]:+.0f}", lab_font=f_small)
    img.save(args.out)
    print("写出", args.out, img.size)


if __name__ == "__main__":
    main()
