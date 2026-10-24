"""原生流水线：直接读 glyf 轮廓，用保留曲线的布尔并集合并重叠笔画。

为什么不再重描
--------------
`modernize_maruko.py` 把字形光栅化到 2000 px 再描线，一条轮廓展开成几千个采样点。
原版 `龍` 只有 210 个点、其中 58 段是真曲线；重描之后变成 7657 个点，再"精简"也只能
把折线拟合成折线——实测输出 276 点、0 段曲线，边缘峰峰 4 px（原版 2 px）。

实测 Maruko 的轮廓本来就是干净的：214 个部首里 **0 个**有重叠轮廓，随机抽 400 个
常用字只有 **1 个**（`蝈`）需要并集。也就是说重描对 99.75% 的字只是降质。

本工具的做法
------------
1. 直接读 glyf 的原生二次曲线（不展平）；
2. 用 `pathops.simplify()` 做**保留曲线**的布尔并集，只在真有重叠时改变拓扑；
3. 可选地把自由端头改成真半圆（复用 `round.py`，本来就是按原生控制点写的）。

实测往返损失：`龍` 210→214 点、IoU 0.999952；`龜` 235→247、0.999930；
`鬱` 409→438、0.999757。对比重描流水线是 0.9841。

用法：
    python3 tools/native_modern.py 输入.ttf 输出.ttf --chars 龍龜鬱 --caps
    python3 tools/native_modern.py 输入.ttf 输出.ttf --all-mapped
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path as FilePath

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from pathops import Path, PathPen, simplify

sys.path.insert(0, str(FilePath(__file__).resolve().parent))
from curve_simplify import unique_mapped_chars  # noqa: E402
from round import round_glyph  # noqa: E402


def _path_of(glyph, glyf):
    path = Path()
    glyph.draw(PathPen(path), glyf)
    return path


def process_font(font, chars, union=True, caps=False, source_font=None):
    source_font = source_font or font
    source_glyf = source_font["glyf"]
    output_glyf = font["glyf"]
    cmap = source_font.getBestCmap() or {}
    report, processed = [], set()
    for ch in chars:
        if ord(ch) not in cmap:
            report.append((ch, None, "missing"))
            continue
        gname = cmap[ord(ch)]
        if gname in processed:
            continue
        processed.add(gname)
        glyph = source_glyf[gname]
        if glyph.numberOfContours == 0:
            report.append((ch, gname, "空白字形，跳过"))
            continue

        before_pts = 0 if glyph.isComposite() else len(glyph.getCoordinates(source_glyf)[0])
        before_contours = glyph.numberOfContours

        path = _path_of(glyph, source_glyf)
        if union:
            path = simplify(path)

        pen = TTGlyphPen(None)
        path.draw(pen)
        new_glyph = pen.glyph()
        caps_made = 0
        if caps:
            caps_made = round_glyph(new_glyph, output_glyf)
        new_glyph.recalcBounds(output_glyf)
        output_glyf[gname] = new_glyph
        advance = font["hmtx"][gname][0]
        font["hmtx"][gname] = (advance, new_glyph.xMin)

        after_pts = len(new_glyph.getCoordinates(output_glyf)[0]) if new_glyph.numberOfContours else 0
        note = f"{before_pts} -> {after_pts} 点"
        if before_contours != new_glyph.numberOfContours:
            note += f"，轮廓 {before_contours} -> {new_glyph.numberOfContours}（合并重叠）"
        if caps:
            note += f"，半圆端头 {caps_made}"
        report.append((ch, gname, note))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--chars")
    selection.add_argument("--all-mapped", action="store_true")
    parser.add_argument("--no-union", action="store_true", help="不做布尔并集，原样读回")
    parser.add_argument("--caps", action="store_true", help="自由端头改真半圆")
    args = parser.parse_args()

    source = TTFont(args.infont)
    font = TTFont(args.infont)
    chars = unique_mapped_chars(source) if args.all_mapped else list(args.chars or "龍")
    report = process_font(font, chars, not args.no_union, args.caps, source_font=source)
    font.save(args.outfont)
    print(f"处理 {len(report)} 字")
    if not args.all_mapped:
        for ch, gname, note in report:
            print(f"  {ch} ({gname}): {note}")
    print(f"saved -> {args.outfont}")


if __name__ == "__main__":
    sys.exit(main())
