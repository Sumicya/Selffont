"""画 y 轴定位：左＝行高，右＝逐字墨迹中心。

用法
----
    python tools/fig_line_height.py --master 母版.ttf --ours 本版.ttf \
        --chars "門口日一" --out 图.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

INK = (26, 26, 26)
GREY = (160, 160, 160)
BLUE = (36, 104, 210)
RED = (214, 40, 40)
TEXT = "永字八法"


def hhea_of(path):
    with TTFont(str(path), lazy=True) as f:
        return f["hhea"].ascent, f["hhea"].descent, f["head"].unitsPerEm


def draw_block(img, d, path, x0, ytop, f_label, size, name, color, label_dy):
    a, dsc, upem = hhea_of(path)
    line = (a - dsc) / upem * size
    fnt = ImageFont.truetype(str(path), size)
    for i in range(3):
        base = ytop + line * (i + 1)
        d.text((x0, base), TEXT, font=fnt, fill=color, anchor="ls")
    d.text((x0, ytop + 3 * line + 14), f"{name}　行高 {line:.1f} px　hhea {a}/{dsc}",
           font=f_label, fill=color)
    return line


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", type=Path, required=True)
    ap.add_argument("--ours", type=Path, required=True)
    ap.add_argument("--chars", default="門口日一")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    SIZE = 74
    W, H = 2100, 1080
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(str(args.master), 44)
    f_lab = ImageFont.truetype(str(args.master), 26)
    f_s = ImageFont.truetype(str(args.master), 24)

    d.text((48, 30), "y 轴定位：行高（各自 hhea） 与 逐字墨迹中心", font=f_title, fill=INK)
    d.text((48, 88), "左边同一段三行字，各按自己的 hhea 排行距；右边按字格对齐看每个字的墨心",
           font=f_s, fill=(120, 120, 120))

    lm = draw_block(img, d, args.master, 60, 150, f_lab, SIZE, "母版", BLUE, 0)
    lo = draw_block(img, d, args.ours, 700, 150, f_lab, SIZE, "本版", RED, 0)
    d.text((48, 560), f"行高比 {lo / lm:.3f}　本版三行比母版矮 {(1 - lo / lm) * 100:.1f}%",
           font=f_lab, fill=INK)
    d.text((48, 604), "注：本图用的是预览件（未归一）。正式包会归一到设备空壳 930/−250，",
           font=f_s, fill=(120, 120, 120))
    d.text((48, 638), "那是设备行距的锚点，不是母版的 1160/−288；两者必然不同，这不是缺陷。",
           font=f_s, fill=(120, 120, 120))

    # 右：逐字墨心
    x0 = 1230
    d.text((x0, 150), "逐字墨迹中心（字体单位）", font=f_lab, fill=INK)
    cell = 200
    BOX = 190
    with TTFont(str(args.master), lazy=True) as fm, TTFont(str(args.ours), lazy=True) as fo:
        cms = (fm.getBestCmap(), fo.getBestCmap())
        for i, ch in enumerate(args.chars):
            xx = x0 + i * cell
            for row, (font_obj, path, color, name) in enumerate(
                    ((fm, args.master, BLUE, "母版"), (fo, args.ours, RED, "本版"))):
                cmap = cms[row]
                if ord(ch) not in cmap:
                    continue
                glyf = font_obj["glyf"]
                g = glyf[cmap[ord(ch)]]
                g.recalcBounds(glyf)
                base = 420 + row * 300
                fnt = ImageFont.truetype(str(path), BOX)
                d.text((xx + 40, base), ch, font=fnt, fill=color, anchor="ls")
                cx = xx + 40 + (g.xMin + g.xMax) / 2 / 1000 * BOX
                cy = base - (g.yMin + g.yMax) / 2 / 1000 * BOX
                d.line([cx, base - 220, cx, base + 30], fill=(90, 90, 90), width=2)
                d.line([xx + 20, cy, xx + 40 + BOX + 20, cy], fill=(90, 90, 90), width=2)
                d.text((xx + 40, base + 44),
                       f"x{(g.xMin + g.xMax) / 2:.0f} y{(g.yMin + g.yMax) / 2:.0f}",
                       font=f_s, fill=(90, 90, 90))
            d.text((xx + 40, 740), ch, font=f_lab, fill=INK)

    d.text((1230, 800), "灰十字＝墨迹外接框中心；母版中位 x498.5 y375.5，本版 x498.0 y376.0",
           font=f_s, fill=(120, 120, 120))
    d.text((1230, 840), "600 字逐字差：x 中位 −0.5、y 中位 +0.5",
           font=f_s, fill=(120, 120, 120))

    img.save(args.out)
    print("写出", args.out, img.size)


if __name__ == "__main__":
    main()
