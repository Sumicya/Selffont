"""报一个（或几个）字件的竖直度量，并和参照字体逐项对读。

为什么要有这个：行高、基线位置跟字重无关、只跟 hhea/typo/win 有关，而这三组数字
在渲染出来的图上不直观——`ā` 与 `日` 的上下沿差 1%，行距却能差 18%。装到设备上
混排时先看到的不是字形难看，是「跳行」「字顶到上一行」，所以这组数字要能一条命令报出来。

用法：
    python tools/metrics_report.py 自研.ttf --reference 母版.ttf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
SAMPLE = "口日国永一丨十田目回中天人大小上下"


def ink_envelope(font: TTFont) -> tuple[int, int] | None:
    glyf = font["glyf"]
    low, high = None, None
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        glyph.expand(glyf)      # 没解包的字形 numberOfContours 读成 0，会把整库当空格子
        if glyph.numberOfContours == 0:
            continue
        low = glyph.yMin if low is None else min(low, glyph.yMin)
        high = glyph.yMax if high is None else max(high, glyph.yMax)
    return None if low is None else (low, high)


def report(path: Path, sample: str) -> dict:
    with TTFont(path, recalcBBoxes=False) as font:
        head, hhea, os2 = font["head"], font["hhea"], font["OS/2"]
        ink = ink_envelope(font)
        cmap, glyphs = font.getBestCmap(), font.getGlyphSet()
        bounds = {}
        for ch in sample:
            name = cmap.get(ord(ch))
            if not name:
                continue
            pen = BoundsPen(glyphs)
            glyphs[name].draw(pen)
            if pen.bounds:
                bounds[ch] = pen.bounds
        metrics = {
            "path": str(path),
            "upm": head.unitsPerEm,
            "hhea": (hhea.ascent, hhea.descent, hhea.lineGap),
            "typo": (os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap),
            "win": (os2.usWinAscent, os2.usWinDescent),
            "useTypoMetrics": bool(os2.fsSelection & 0x80),
            "ink": ink,
            "bounds": bounds,
        }
    metrics["line"] = metrics["hhea"][0] - metrics["hhea"][1]
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path)
    parser.add_argument("--reference", type=Path, help="参照字体（行框应对齐的一方）")
    parser.add_argument("--sample", default=SAMPLE)
    args = parser.parse_args()

    got = report(args.font, args.sample)
    print(f"{args.font}")
    print(f"  upm {got['upm']}  hhea {got['hhea']}  typo {got['typo']}  win {got['win']}"
          f"  useTypo={got['useTypoMetrics']}")
    print(f"  行框 {got['line']}  墨迹包络 {got['ink']}")
    if not args.reference:
        return
    ref = report(args.reference, args.sample)
    print(f"{args.reference}（参照）")
    print(f"  upm {ref['upm']}  hhea {ref['hhea']}  typo {ref['typo']}  win {ref['win']}")
    print(f"  行框 {ref['line']}  墨迹包络 {ref['ink']}")
    print(f"行框差 {got['line'] - ref['line']:+d}（{got['line'] / ref['line'] - 1:+.1%}）")
    print(f"hhea 差 {got['hhea'][0] - ref['hhea'][0]:+d}/{got['hhea'][1] - ref['hhea'][1]:+d}")
    print(f"typo 差 {got['typo'][0] - ref['typo'][0]:+d}/{got['typo'][1] - ref['typo'][1]:+d}")
    deltas = []
    for ch, box in got["bounds"].items():
        if ch not in ref["bounds"]:
            continue
        other = ref["bounds"][ch]
        deltas.append((box[1] - other[1], box[3] - other[3]))
    if deltas:
        low = sorted(d[0] for d in deltas)[len(deltas) // 2]
        high = sorted(d[1] for d in deltas)[len(deltas) // 2]
        print(f"逐字墨迹 中位：下沿 {low:+.0f} 上沿 {high:+.0f}（单位 /{got['upm']} em，n={len(deltas)}）")


if __name__ == "__main__":
    main()
