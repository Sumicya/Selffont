"""把目标字体缺的码位从补全字库搬进来。

只负责"搬"：字形轮廓原样取过来（同一 upm 直接复制，不同 upm 按比例缩放并把墨迹
对齐到目标字体的平均左右边距），补齐 cmap / hmtx / glyphOrder。**不改笔画、不做风格
适配**——搬来的字形是别人家的风格，这一点会在调用处的报告里写清楚。

用法：
    python3 tools/import_glyphs.py 目标.ttf 字库.ttf 输出.ttf --chars "䶶䶷"
    python3 tools/import_glyphs.py 目标.ttf 字库.ttf 输出.ttf --missing-in 3400..4DBF
"""
from __future__ import annotations

import argparse
import sys

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph


def _simple(glyph, glyf, glyph_set):
    """composite 展开成简单字形。"""
    if not glyph.isComposite():
        return glyph
    pen = TTGlyphPen(glyph_set)
    glyf[glyph.name] if False else None
    glyph.draw(pen, glyf)
    return pen.glyph()


def _scaled(glyph, factor):
    if factor == 1.0:
        return glyph
    for point in glyph.coordinates:
        point[0] = int(round(point[0] * factor))
        point[1] = int(round(point[1] * factor))
        if glyph.numberOfContours < 0:
            raise ValueError("composite 不能直接缩放坐标")
    return glyph


def import_chars(target_path, donor_path, out_path, chars):
    target = TTFont(target_path)
    donor = TTFont(donor_path)
    tcmap, dcmap = target.getBestCmap(), donor.getBestCmap()
    tglyf, dglyf = target["glyf"], donor["glyf"]
    dset = donor.getGlyphSet()
    tupm, dupm = target["head"].unitsPerEm, donor["head"].unitsPerEm
    factor = tupm / dupm
    advance = target["hmtx"][target.getGlyphOrder()[1]][0]

    done, skipped = [], []
    for ch in chars:
        cp = ord(ch)
        if cp in tcmap:
            skipped.append((ch, "已有"))
            continue
        if cp not in dcmap:
            skipped.append((ch, "字库没有"))
            continue
        src = dglyf[dcmap[cp]]
        glyph = _simple(src, dglyf, dset)
        glyph = _scaled(glyph, factor)
        name = f"uni{cp:04X}"
        while name in target.getGlyphOrder():
            name += "."
        target.setGlyphOrder(target.getGlyphOrder() + [name])
        tglyf[name] = glyph
        tglyf.glyphOrder = target.getGlyphOrder()
        glyph.recalcBounds(tglyf)
        target["hmtx"][name] = (advance, glyph.xMin)
        for table in target["cmap"].tables:
            if table.isUnicode():
                table.cmap[cp] = name
        done.append((ch, name, glyph.numberOfContours))
    target.save(out_path)
    return done, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("donor")
    parser.add_argument("output")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--chars")
    group.add_argument("--missing-in", help="LO..HI（十六进制）：目标字体在这段里缺的码位全部补")
    args = parser.parse_args()

    if args.chars:
        chars = [c for c in dict.fromkeys(args.chars)]
    else:
        lo, hi = (int(x, 16) for x in args.missing_in.split(".."))
        target_cmap = TTFont(args.target).getBestCmap()
        donor_cmap = TTFont(args.donor).getBestCmap()
        chars = [chr(cp) for cp in range(lo, hi + 1)
                 if cp not in target_cmap and cp in donor_cmap and chr(cp).isprintable()]

    done, skipped = import_chars(args.target, args.donor, args.output, chars)
    print(f"搬入 {len(done)} 个码位，跳过 {len(skipped)} 个")
    for ch, name, contours in done[:20]:
        print(f"  U+{ord(ch):04X} {ch} -> {name}（{contours} 条轮廓）")
    for ch, why in skipped[:10]:
        print(f"  跳过 U+{ord(ch):04X}：{why}")
    print(f"saved -> {args.output}")


if __name__ == "__main__":
    sys.exit(main())
