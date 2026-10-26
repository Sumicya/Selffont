"""覆盖审计：给定码位表，报告字体里到底有没有这个字。

三档，必须分开看，混在一起就会得出「渲染不支持」这种废话结论：
  有墨   —— cmap 有映射且字形有轮廓，能看见
  空壳   —— cmap 有映射但字形无轮廓，声称覆盖却什么也不画
  无映射 —— cmap 里没有，系统只会回退或画豆腐

用法：python tools/coverage_audit.py 字体.ttf [更多字体...]
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_targets import TARGETS  # noqa: E402


def audit(path: str):
    font = TTFont(path, lazy=True)
    cmap = font.getBestCmap() or {}
    glyphs = font.getGlyphSet()
    ink, shell = [], []
    for cp in TARGETS:
        name = cmap.get(cp)
        if name is None:
            continue
        pen = BoundsPen(glyphs)
        try:
            glyphs[name].draw(pen)
        except Exception:
            ink.append(cp)
            continue
        (ink if pen.bounds is not None else shell).append(cp)
    missing = [cp for cp in TARGETS if cp not in set(ink) | set(shell)]
    total = len(TARGETS)
    print(f"{path}")
    print(f"  有墨 {len(ink)}/{total}   空壳 {len(shell)}   无映射 {len(missing)}")
    if shell:
        print("  空壳:", " ".join(f"U+{c:04X}" for c in shell[:20]))
    font.close()
    return ink, shell, missing


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for path in sys.argv[1:]:
        audit(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
