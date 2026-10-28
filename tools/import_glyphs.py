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
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates


def _simple(glyph, glyf, glyph_set):
    """composite 展开成简单字形。

    不能把 `TTGlyphPen` 直接喂给 `glyph.draw`：TTGlyphPen 有 addComponent，
    复合字形会被原样写成新的复合字形，缩放时仍然报「composite 不能直接缩放」。
    必须用 DecomposingRecordingPen 把部件真正展开成轮廓。
    """
    if not glyph.isComposite():
        return glyph
    rec = DecomposingRecordingPen(glyph_set)
    glyph.draw(rec, glyf)
    pen = TTGlyphPen(glyph_set)
    rec.replay(pen)
    return pen.glyph()


def _scaled(glyph, factor):
    """按 upm 比例缩放。composite 必须先经 `_simple` 展开再进来。

    `glyph.coordinates` 是 GlyphCoordinates，不是可变点列表；逐点赋值会报
    `'tuple' object does not support item assignment`。
    """
    if factor == 1.0:
        return glyph
    if glyph.numberOfContours < 0:
        raise ValueError("composite 不能直接缩放坐标")
    glyph.coordinates = GlyphCoordinates(
        [(x * factor, y * factor) for x, y in glyph.coordinates])
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

    # 可变表必须在改 glyphOrder 之前反序列化：gvar.decompile 会断言
    # `len(glyphOrder) == glyphCount`，改完顺序再读必炸。
    gvar = target["gvar"] if "gvar" in target else None

    done, skipped = [], []
    order = list(target.getGlyphOrder())
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
        while name in order:
            name += "."
        order.append(name)
        tglyf[name] = glyph
        glyph.recalcBounds(tglyf)
        # hmtx / vmtx 的存储都是 .metrics；CJK 目标字体带 vmtx，漏了保存就是 KeyError
        for tag in ("hmtx", "vmtx"):
            if tag in target:
                target[tag].metrics[name] = (advance, glyph.xMin)
        for table in target["cmap"].tables:
            # format 4 只能放 16 位码位，塞辅助平面会 OverflowError
            if not table.isUnicode() or table.format not in (4, 12):
                continue
            if table.format == 4 and cp > 0xFFFF:
                continue
            table.cmap[cp] = name
        done.append((ch, name, glyph.numberOfContours))
    if gvar is not None:
        for _ch, new_name, _n in done:
            gvar.variations.setdefault(new_name, [])
    target.glyphOrder = order
    tglyf.glyphOrder = order
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
