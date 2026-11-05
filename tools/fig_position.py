"""把「字在字格里放没放正」画出来：同一批字、同一字号，叠上字格线与基线。

为什么要有这个图
----------------
2026-11-05 主人问「水平 y 轴定位问题」。此前的对照图都是把每个字按各自墨迹裁切再居中贴，
等于先把位置差抹平了再比形状——位置这一项从来没被看见过。这张图不裁墨迹，按字格
（advance × upem）对齐，画三样东西：

- 灰框：这个字的字身格（宽 = advance，高 = 1000 单位）
- 蓝线：基线 y = 0
- 红虚线：左右边距（xMin / xMax），偏了就能直接读出来

用法
----
    python tools/fig_position.py --master 母版.ttf --ours 本版.ttf \
        --chars "门口国团日一" --out 图.png
    python tools/fig_position.py --master 母版.ttf --chars "门口国团日一" --out 图.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

INK = (26, 26, 26)
GREY = (176, 176, 176)
BLUE = (36, 104, 210)
RED = (214, 40, 40)


def bbox(font, gname):
    glyf = font["glyf"]
    g = glyf[gname]
    if g.numberOfContours == 0:
        return None
    g.recalcBounds(glyf)
    return (g.xMin, g.yMin, g.xMax, g.yMax)


def draw_row(img, d, path, chars, ytop, cell, name, label_font, show_guides=True):
    with TTFont(str(path), lazy=True) as f:
        cmap = f.getBestCmap()
        hmtx = f["hmtx"]
        hhea = f["hhea"]
        png_font = ImageFont.truetype(str(path), int(cell * 0.62))
        x = 40
        for ch in chars:
            cp = ord(ch)
            if cp not in cmap:
                x += cell
                continue
            gname = cmap[cp]
            adv, _ = hmtx[gname]
            bb = bbox(f, gname)
            # 字格：宽 adv、高 1000，基线在 ytop+cell*0.78
            base = ytop + cell * 0.78
            sx = cell / max(adv, 1) * 0.86
            gx0 = x + (cell - adv * sx) / 2
            gy0 = base - 1000 * sx * 0.78 / 0.78  # 顶部（1000 单位高）
            # 画字：按字格缩放渲染，锚在基线上
            fpx = ImageFont.truetype(str(path), int(1000 * sx))
            d.text((gx0, base), ch, font=fpx, fill=INK, anchor="ls")
            if show_guides:
                d.rectangle([gx0, base - 1000 * sx, gx0 + adv * sx, base], outline=GREY, width=2)
                d.line([gx0, base, gx0 + adv * sx, base], fill=BLUE, width=3)
                if bb:
                    d.line([gx0 + bb[0] * sx, base - 40, gx0 + bb[0] * sx, base + 40], fill=RED, width=2)
                    d.line([gx0 + bb[2] * sx, base - 40, gx0 + bb[2] * sx, base + 40], fill=RED, width=2)
                # 中线
                midx = gx0 + adv * sx / 2
                d.line([midx, base - 1000 * sx, midx, base], fill=GREY, width=1)
            x += cell
        d.text((40, ytop - 34), name, font=label_font, fill=(110, 110, 110))


def main() -> None:
    ap = argparse.ArgumentParser(description="画字格对齐图（花：母版 vs 本版）")
    ap.add_argument("--master", type=Path, required=True)
    ap.add_argument("--ours", type=Path, default=None)
    ap.add_argument("--chars", default="门口国团日一")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cell", type=int, default=260)
    args = ap.parse_args()

    chars = args.chars
    rows = 1 if args.ours is None else 2
    W = 80 + len(chars) * args.cell
    H = 210 + rows * (args.cell + 60)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(str(args.master), 40)
    f_lab = ImageFont.truetype(str(args.master), 28)
    f_s = ImageFont.truetype(str(args.master), 24)

    d.text((40, 26), "字在字格里放没放正：灰框字身格，蓝线基线，红竖线左右边距", font=f_title, fill=INK)
    d.text((40, 80), f"同字号；整行按字格对齐，不裁墨迹", font=f_s, fill=(120, 120, 120))

    draw_row(img, d, args.master, chars, 210, args.cell, "母版", f_lab)
    if args.ours is not None:
        draw_row(img, d, args.ours, chars, 210 + args.cell + 60, args.cell, "本版", f_lab)

    img.save(args.out)
    print("写出", args.out, img.size)


if __name__ == "__main__":
    main()
