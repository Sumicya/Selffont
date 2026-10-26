"""覆盖审计：主人贴的 315 个码位，逐一在字库链里找有没有字形。

三档必须分开报，混在一起就会得出「渲染不支持」这种废话结论：
  有墨   —— 有映射且字形有轮廓（彩色字体按 cmap 计，墨在图层里）
  空壳   —— 有映射但无轮廓，声称覆盖却什么也不画
  缺失   —— 链上没有任何字库认这个码位

用法：
    python tools/coverage_audit.py 主字体.ttf [补充字件...]
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_targets import TARGETS, UNASSIGNED  # noqa: E402


def visible(path: str) -> tuple[set[int], set[int]]:
    font = TTFont(path, lazy=True)
    cmap = font.getBestCmap() or {}
    glyphs = font.getGlyphSet()
    color = any(tag in font for tag in ("COLR", "CBDT", "sbix"))
    ink, shell = set(), set()
    for cp in TARGETS:
        name = cmap.get(cp)
        if name is None:
            continue
        if color:
            ink.add(cp)
            continue
        pen = BoundsPen(glyphs)
        try:
            glyphs[name].draw(pen)
        except Exception:
            ink.add(cp)
            continue
        (ink if pen.bounds is not None else shell).add(cp)
    font.close()
    return ink, shell


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    union_ink, union_shell = set(), set()
    for path in sys.argv[1:]:
        ink, shell = visible(path)
        union_ink |= ink
        union_shell |= shell
        print(f"{path:34s} 有墨 {len(ink):3d}  空壳 {len(shell)}")
    missing = [cp for cp in TARGETS if cp not in union_ink and cp not in union_shell]
    total = len(TARGETS)
    print(f"\n合计 {total} 个码位：有墨 {len(union_ink)}  空壳 {len(union_shell)}  "
          f"缺失 {len(missing)}  → 覆盖 {len(union_ink)}/{total}")
    if missing:
        print("缺失:", " ".join(f"U+{cp:05X}" for cp in missing))
    reserved = [cp for cp in union_ink if cp in UNASSIGNED]
    if reserved:
        print(f"其中 {len(reserved)} 个是 Unicode 尚未分配的码位（自绘占位）")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
