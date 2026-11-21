"""把「自交」分级：是真缺口，还是零点几单位的毛刺。

为什么要有这个工具
------------------
2026-11-05 复算发现：`check_self_intersect.py` 报 200 字里 130 字自交，但其中 121 字的
自交环面积差 **不到 50 平方单位**（中位 0.38），换句话说轮廓在收笔端头自己打了个
不到半个单位的回折——shapely 判它无效，肉眼和光栅化都看不见。

把两者混成一个数，会把「9 个字真有缺口」说成「130 个字烂了」，也会让「开了某个默认
多了 15 个自交」这种结论失去意义（多出来的 15 个里 12 个是毛刺）。

判据
----
- `sliver`：环面积差 ≤ 10 平方单位，或者占该字墨量 < 0.1%
- `real`：环面积差 > 10 平方单位且占比 ≥ 0.1%

用法
----
    python tools/selfx_severity.py 字体.ttf --chars "$(head -1 tools/endcap_sample200.txt)"
    python tools/selfx_severity.py 字体.ttf --chars "字串" --json out.json --top 12
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import shapely.geometry as sg
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_self_intersect import FlattenPen, check_glyph  # noqa: E402

SLIVER_AREA = 10.0      # 平方单位
SLIVER_RATIO = 0.001    # 占该字被检轮廓总面积的比例


def scan(path: Path, chars: str):
    rows = {}
    with TTFont(str(path), lazy=True) as font:
        cmap = font.getBestCmap()
        glyphs = font.getGlyphSet()
        for ch in dict.fromkeys(chars):
            cp = ord(ch)
            if cp not in cmap:
                continue
            pen = FlattenPen(glyphs)
            glyphs[cmap[cp]].draw(pen)
            bad, _ = check_glyph(font, cmap[cp])
            if not bad:
                continue
            worst, ink, detail = 0.0, 0.0, []
            for ci in bad:
                poly = sg.Polygon(pen.contours[ci])
                if poly.is_valid:
                    continue
                delta = abs(poly.area) - poly.buffer(0).area
                worst = max(worst, delta)
                ink += abs(poly.area)
                detail.append(dict(contour=ci, points=len(pen.contours[ci]),
                                   area_delta=round(delta, 2)))
            rows[ch] = dict(worst=round(worst, 2), ink=round(ink, 1),
                            ratio=round(worst / max(ink, 1.0), 6), contours=detail)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="给自交分级：真缺口 vs 亚单位毛刺")
    ap.add_argument("font", type=Path)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    rows = scan(args.font, args.chars)
    real = {c: v for c, v in rows.items()
            if v["worst"] > SLIVER_AREA and v["ratio"] >= SLIVER_RATIO}
    sliver = {c: v for c, v in rows.items() if c not in real}

    print(f"被判自交 {len(rows)} 字：真缺口 {len(real)}，毛刺 {len(sliver)}")
    print(f"  毛刺环面积差 中位 {sorted(v['worst'] for v in sliver.values())[len(sliver) // 2] if sliver else 0:.2f} 平方单位"
          f"（{SLIVER_AREA:.0f} 以下算毛刺）")
    print("  真缺口：" + "  ".join(f"{c}{v['worst']:.0f}" for c, v in
                                 sorted(real.items(), key=lambda kv: -kv[1]["worst"])[:args.top]))
    if args.json:
        args.json.write_text(json.dumps(dict(real=real, sliver=sliver),
                                        ensure_ascii=False, indent=1), encoding="utf-8")
        print("写入", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
