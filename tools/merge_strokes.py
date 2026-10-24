"""C 类试做：笔画结构合并（把同一字形内互相重叠的多条轮廓并成真实墨迹边界）。

为什么算"笔画简化"而不是"曲线精简"：Maruko 的字形里相交笔画各自是独立闭合轮廓，靠 TrueType
非零环绕规则叠在一起显示——交叉处有两层轮廓边、T 形接口有一条被压住的暗边。合并后每个字形
只剩真实外边界与真空腔，隐藏重叠消失，属于结构层面的简化，`curve_simplify.py` 那种只重拟合
边界的做法做不到。

实现路线（前两版都错在这里，记下来省得再踩）：
- 直接 `union_all` 全部轮廓 → 内腔被当实心，`国/回/田` 变实心方块。
- 按"有符号面积正负"分实体/孔洞 → Maruko 的内笔与外框绕行方向相同，内笔被当孔洞减掉，
  `国` 的玉字整块消失。
- 现在这条路：**先光栅化出墨迹，再沿墨迹边界重新描线**。光栅化由仓库既有
  `raster_mask()` 完成（它按绕行规则把洞正确挖空），描线复用 `glyph_from_mask()`。
  好处是结果严格等于"原字形看得见的形状"，不依赖对上游绕行约定的猜测。

代价：描线是折线，原始曲线要重拟合才能回到干净的二次贝塞尔；这一步本轮没做，所以原型点数
偏高（见输出），这是明确未完成项，不能当成最终形态。

边界：合并丢弃了"这一笔在哪结束、那一笔在哪开始"的结构信息，字形从此是一个整体轮廓，
后续再想单独调某一笔就不可能了。只适合定稿阶段，且必须逐字看效果。

用法：
    python3 tools/merge_strokes.py 输入.ttf 输出.ttf --chars 国回田 --px 1200
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stroke_width_normalize_prototype import glyph_from_mask, raster_mask  # noqa: E402


def merge_glyph(font, gname, px, margin_frac=0.08):
    mask, transform = raster_mask(font, gname, px, margin_frac)
    return glyph_from_mask(mask, font, transform), mask


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("infont")
    ap.add_argument("outfont")
    ap.add_argument("--chars", required=True)
    ap.add_argument("--px", type=int, default=1200, help="光栅化画布边长（越大越贴近原曲线）")
    args = ap.parse_args()

    if Path(args.infont).resolve() == Path(args.outfont).resolve():
        ap.error("输入与输出不能是同一个文件")

    source = TTFont(args.infont)
    font = TTFont(args.infont)
    cmap = source.getBestCmap()
    done = 0
    for ch in dict.fromkeys(args.chars):
        if ord(ch) not in cmap:
            print(f"{ch}: 不在 cmap 里，跳过")
            continue
        gname = cmap[ord(ch)]
        src_glyph = source["glyf"][gname]
        if src_glyph.isComposite():
            print(f"{ch} ({gname}): composite 字形，跳过")
            continue
        src_coords, src_ends, _ = src_glyph.getCoordinates(source["glyf"])
        try:
            merged, _mask = merge_glyph(source, gname, args.px)
        except ValueError as exc:
            print(f"{ch} ({gname}): 失败 {exc}")
            continue
        font["glyf"][gname] = merged
        print(f"{ch} ({gname}): 源 {len(src_ends)} 轮廓 / {len(src_coords)} 点"
              f" → 合并后 {merged.numberOfContours} 轮廓 / {len(merged.coordinates)} 点")
        done += 1
    font.save(args.outfont)
    print(f"完成 {done} 字 -> {args.outfont}")


if __name__ == "__main__":
    sys.exit(main())
