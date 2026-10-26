"""把自研字形注入主字体（不改动原有任何字形）。

为什么不走「补充字体 + fallback 链」
----------------------------------
补充字体要靠 fonts.xml / font_fallback.xml 的家族链才能被找到，而不同 app 的回退
行为不一致（主人在真机上就遇到「有的 app 覆盖不到」）。把 cmap 直接补进主字体，
是同一份字体自己认这些码位，任何 app 都绕不过去。

为什么不动原有字形：只追加 glyf/hmtx/cmap 条目，原有 glyph 一个字节不改。
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.boundsPen import BoundsPen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design_symbols as ds  # noqa: E402


def path_to_glyph(path_obj, glyph_set):
    """pathops 路径 → TrueType 字形。绕向已由 canon 规范化（外轮廓顺时针=面积为负）。"""
    pen = TTGlyphPen(glyph_set)
    path_obj.draw(pen)
    return pen.glyph()


def inject(font_path: Path, out_path: Path, glyphs=None) -> dict:
    glyphs = glyphs if glyphs is not None else ds.GLYPHS
    font = TTFont(str(font_path))
    order = list(font.getGlyphOrder())
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap() or {}

    added, skipped = {}, []
    for cp, (name, builder) in sorted(glyphs.items()):
        if cp in cmap:
            skipped.append(cp)          # 上游已有：绝不覆盖
            continue
        path_obj = builder()
        glyph = path_to_glyph(path_obj, glyph_set)
        if glyph.numberOfContours == 0:
            skipped.append(cp)
            continue
        gname = f"selffont.u{cp:05X}"
        if gname in font["glyf"]:
            skipped.append(cp)
            continue
        font["glyf"][gname] = glyph
        # 边界从 pathops 路径上取：刚构造的 Glyph 还没算 xMin/xMax，
        # glyph.recalcBounds() 要等 glyf 表编好，不如直接用源路径的 bounds。
        lsb = int(round(path_obj.bounds[0])) if path_obj.bounds else 0
        # 横排和竖排度量都要补：CJK 字体的 vmtx 复用 hmtx 的 compile，
        # 只补 hmtx 会在保存时报 KeyError（我第一次就被这个卡住）。
        for tag in ("hmtx", "vmtx"):
            if tag in font:
                font[tag].metrics[gname] = (1000, lsb)
        order.append(gname)
        added[cp] = gname

    if not added:
        font.close()
        return {"added": 0, "skipped": skipped}

    # 两边共用同一个列表对象。不要用 font.setGlyphOrder()：它会把新名字再往
    # glyf.glyphOrder 追加一次，长度和 glyphs 对不上，maxp 重算时 assert 炸。
    font.glyphOrder = order
    font["glyf"].glyphOrder = order
    for table in font["cmap"].tables:
        if table.format == 4:
            for cp, gname in added.items():
                if cp <= 0xFFFF:
                    table.cmap[cp] = gname
        elif table.format == 12:
            for cp, gname in added.items():
                table.cmap[cp] = gname
    font.save(str(out_path))
    font.close()
    return {"added": len(added), "skipped": skipped, "path": str(out_path)}


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/wenyuan.ttf")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/wenyuan_sym.ttf")
    result = inject(src, out)
    print(f"注入 {result['added']} 个字形 → {result['path']}")
    if result["skipped"]:
        print("  跳过（上游已有或空壳）:", " ".join(f"U+{c:04X}" for c in result["skipped"]))


if __name__ == "__main__":
    main()
