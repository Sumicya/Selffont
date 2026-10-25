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

import math

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


def _trim_ends(sk, trim, mask):
    """从每个骨架端点沿骨架往里走 `trim` 倍局部半宽，把走过的一段删掉。

    钩在骨架上不是分叉，是笔画末端的连续外扬（实测 `九` 从笔尖走 334 步无分叉、
    弯曲率只有 1.05），所以不能靠剪枝去掉，只能按长度截。截完再盖盘，端头
    自然是标准半圆。
    """
    sk = sk.copy()
    dist0 = ndimage.distance_transform_edt(mask)
    ys, xs = np.nonzero(sk)
    deg = np.zeros_like(sk, dtype=int)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.zeros_like(sk)
            ys2 = slice(max(0, dy), sk.shape[0] + min(0, dy))
            xs2 = slice(max(0, dx), sk.shape[1] + min(0, dx))
            ys1 = slice(max(0, -dy), sk.shape[0] + min(0, -dy))
            xs1 = slice(max(0, -dx), sk.shape[1] + min(0, -dx))
            shifted[ys2, xs2] = sk[ys1, xs1]
            deg += shifted.astype(int)
    ends = [(int(y), int(x)) for y, x in zip(*np.nonzero(sk & (deg == 1)))]
    for y0, x0 in ends:
        if not sk[y0, x0]:
            continue
        need = trim * max(1.0, dist0[y0, x0])
        seen = {(y0, x0)}
        cur = (y0, x0)
        walk = [(y0, x0)]
        total = 0.0
        while total < need:
            nxt = None
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    p = (cur[0] + dy, cur[1] + dx)
                    if 0 <= p[0] < sk.shape[0] and 0 <= p[1] < sk.shape[1] \
                            and sk[p] and p not in seen:
                        nxt = p
                        break
                if nxt:
                    break
            if nxt is None:
                break
            total += math.hypot(nxt[0] - cur[0], nxt[1] - cur[1])
            seen.add(nxt)
            walk.append(nxt)
            cur = nxt
        for p in walk:
            sk[p] = False
    return sk


def _stamp(sk, dist, extra=0):
    """把每个骨架点按**它自己的**半宽盖一个圆盘，返回并集。

    上一版用整字半宽中位数，细笔画被粗笔画撑出来的半径吃掉（`包` 内框糊成一团、
    `必` 的心、`電` 的雨全丢）。按骨架点的局部半宽盖盘，才是「等宽笔画」的正确含义：
    每一笔自己等宽。
    """
    h, w = sk.shape
    out = np.zeros((h, w), dtype=bool)
    ys, xs = np.nonzero(sk)
    cache = {}
    for y, x in zip(ys, xs):
        r = int(round(dist[y, x])) + extra
        if r < 1:
            out[y, x] = True
            continue
        d = cache.get(r)
        if d is None:
            d = disk(r).astype(bool)
            cache[r] = d
        y0, y1 = max(0, y - r), min(h, y + r + 1)
        x0, x1 = max(0, x - r), min(w, x + r + 1)
        out[y0:y1, x0:x1] |= d[(y0 - y + r):(y1 - y + r), (x0 - x + r):(x1 - x + r)]
    return out


def rebuild(font, gname, px=2000, tolerance=1.2, trim=0.0, verbose=True):
    """把一个字形按骨架重画成等宽圆头笔画。返回 (轮廓数, 总点数)。

    `trim` > 0 时，先沿骨架从每个端点往里截掉 `trim` 倍局部半宽，再盖盘。截掉
    钩的就是这一步：端头变成半径 = 半笔宽的标准半圆，笔身是直的等宽段，
    不会留下横向残桩。
    """
    mask, (xmin, ymin, scale, margin, upp, _sign) = raster_mask(font, gname, px, 0.08)
    dist = ndimage.distance_transform_edt(mask)
    sk = skeletonize(mask)
    if trim > 0:
        sk = _trim_ends(sk, trim, mask)
    thick = _stamp(sk, dist)
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
    # lsb 必须跟 xMin 走：重画后 xMin 会变，不同步的话 FreeType 按旧 lsb 定位，
    # 整字在格子里偏移（`hook_taper` 里同一个坑，`了` 曾偏 172 单位）。
    if "hmtx" in font and gname in font["hmtx"].metrics:
        adv, _lsb = font["hmtx"][gname]
        font["hmtx"][gname] = (adv, glyph.xMin)
    if verbose:
        print(f"  {gname}: 轮廓 {len(contours)} 点 {total}")
    return len(contours), total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("infont")
    parser.add_argument("outfont")
    parser.add_argument("--chars", required=True)
    parser.add_argument("--px", type=int, default=2000)
    parser.add_argument("--trim", type=float, default=0.0,
                        help="沿骨架截掉端头多少倍局部半宽（>0 会去掉钩）")
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
        rebuild(font, gname, args.px, trim=args.trim)
    font.save(args.outfont)
    print(args.outfont)


if __name__ == "__main__":
    main()
