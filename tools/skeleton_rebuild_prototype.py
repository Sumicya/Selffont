#!/usr/bin/env python3
"""用骨架重画字形：等宽圆头笔画 + 半圆端点。研究用原型。

`hook_taper` 是在**原有轮廓**上切一刀再扣半圆，所以切口一定带着原笔画的走势。
主人要的「一条直 + 半圆」是另一件事：端头必须是直笔身收的标准半圆，不能是
把弯的外扬弧横切一段。这个原型换个做法——丢掉原轮廓，只留骨架，按骨架重画：

1. 字形栅格化成 2000 px/em 的掩膜；
2. `skeletonize` 取骨架，`distance_transform_edt` 读骨架上的半笔宽；
3. 用半径 = **整字骨架半宽中位数**的圆盘膨胀骨架，得到等宽圆头笔画；
4. `find_contours` 取边界，`approximate_polygon` 简化，按原字形最大轮廓的
   环绕方向写成直线段轮廓。

端点天然是半圆（圆盘膨胀的端头就是半圆），也没有钩尖——钩尖在骨架上是一根
弯到 20 像素内的短刺，膨胀后被圆头取代。

**这一版只做到等宽**，全局半径会把细笔画吃掉：`包` 的内框糊成一团、`必` 的
「心」和 `電` 的「雨」都丢了（图见 docs/round-preview/2026-10-24-modern-maruko-pipeline/
skeleton-rebuild-v1.png）。下一步要按**骨架点的局部半宽**膨胀，而不是全局中位数。

用法：
    python tools/skeleton_rebuild_prototype.py 源.ttf 输出.ttf --chars 九乙了
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from scipy import ndimage
from skimage.measure import approximate_polygon
from skimage.morphology import disk, skeletonize

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.hook_cut import split_contours  # noqa: E402
from tools.stroke_centerline_rebuild_prototype import (  # noqa: E402
    _closed_contours,
    _contour_area,
)
from tools.stroke_width_normalize_prototype import raster_mask  # noqa: E402


def _outer_sign(glyf, gname):
    """原字形最大轮廓的环绕方向（TrueType 用非零环绕，方向反了会挖成洞）。"""
    coords, ends, flags = glyf[gname].getCoordinates(glyf)
    biggest = max(split_contours(coords, ends, flags), key=len)
    area = sum(biggest[i][0] * biggest[(i + 1) % len(biggest)][1]
               - biggest[(i + 1) % len(biggest)][0] * biggest[i][1]
               for i in range(len(biggest)))
    return 1 if area > 0 else -1


def rebuild(font, gname, px=2000, tolerance=1.2, verbose=True):
    """把一个字形按骨架重画成等宽圆头笔画。返回 (轮廓数, 总点数)。"""
    mask, (xmin, ymin, scale, margin, upp, _sign) = raster_mask(font, gname, px, 0.08)
    dist = ndimage.distance_transform_edt(mask)
    sk = skeletonize(mask)
    radius = float(np.median(dist[sk]))
    thick = ndimage.binary_dilation(sk, disk(int(round(radius))))
    contours = _closed_contours(thick, upp)
    want_outer = _outer_sign(font["glyf"], gname)

    pen = TTGlyphPen(font.getGlyphSet())
    order = sorted(range(len(contours)), key=lambda k: -abs(_contour_area(contours[k])))
    total = 0
    for rank, k in enumerate(order):
        poly = approximate_polygon(contours[k], tolerance=tolerance)
        pts = [((col - margin) / scale + xmin, ((px - row) - margin) / scale + ymin)
               for row, col in poly]
        area = 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                         - pts[(i + 1) % len(pts)][0] * pts[i][1]
                         for i in range(len(pts)))
        want = want_outer if rank == 0 else -want_outer
        if area and (1 if area > 0 else -1) != want:
            pts.reverse()
        pts = [(int(round(x)), int(round(y))) for x, y in pts]
        if len(set(pts)) < 3:
            continue
        pen.moveTo(pts[0])
        for point in pts[1:]:
            pen.lineTo(point)
        pen.closePath()
        total += len(pts)
    glyph = pen.glyph()
    glyph.recalcBounds(font["glyf"])
    font["glyf"][gname] = glyph
    if verbose:
        print(f"  {gname}: 半径 {radius:.1f} 轮廓 {len(contours)} 点 {total}")
    return len(contours), total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    parser.add_argument("--chars", required=True)
    parser.add_argument("--px", type=int, default=2000)
    args = parser.parse_args()
    font = TTFont(args.infont)
    cmap = font.getBestCmap()
    for ch in dict.fromkeys(args.chars):
        if ord(ch) not in cmap:
            continue
        gname = cmap[ord(ch)]
        if font["glyf"][gname].isComposite():
            continue
        print(ch)
        rebuild(font, gname, args.px)
    font.save(args.outfont)
    print(args.outfont)


if __name__ == "__main__":
    main()
