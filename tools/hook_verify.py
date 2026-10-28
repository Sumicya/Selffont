"""钩残留核验：切完之后，**原钩尖那个位置必须空出来**。

为什么前面两个判据都不行
------------------------
1. 骨架净转角：`包` 顶部那撇的端头本身就有 55.9° 的弯（那是 Maruko 的设计，不是钩），
   `九` 的真钩反而只有 26.6°。转角大小与「是不是钩」无关，这条判据从原理上就错。
2. 「钩尖附近还有多少墨」：标准半圆端头本来就有墨，切得越干净墨越多（`乙` 48188→49010
   反而是涨的）。这条判据方向反了。

唯一没有歧义的判据
------------------
切口在新端头处，新端头到**旧钩尖**的距离 ≥ 钩长 − 半笔宽 ≈ 2r（实测被删弧长 3.1–3.7r）。
所以：**旧钩尖周围 0.9r 的球里，切完之后必须一个墨点都没有。** 有墨 = 钩还在。

比较前后两张图时必须用**同一个坐标系**。`raster_mask` 的缩放来自字形自己的外接框，
切过之后外接框变了、整字会平移几个像素，逐像素比较会得出假结论。这里的 `render_fixed`
用调用方给定的固定框，前后共用。

用法：
    python3 tools/hook_verify.py 原版.ttf 切后.ttf --chars 九乙了子也包必電
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from scipy import ndimage
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_erase import find_hooks as raster_hooks  # noqa: E402
from stroke_width_normalize_prototype import FlattenPen  # noqa: E402

TIP_BALL = 0.9   # 旧钩尖周围这个半径（单位 r）内的墨
FILL_MAX = 0.20  # 球内墨迹占比上限。用**比例**而不是绝对像素：短钩的新端头
                 # 会正常压到球边（`九` 剩 91 px、球面积 1854 px = 5%），
                 # 而真钩的球是 85% 满的。绝对阈值在这里没法同时容下两者。


def _outline(font, gname):
    pen = FlattenPen(font.getGlyphSet(), steps_per_curve=20)
    font["glyf"][gname].draw(pen, font["glyf"])
    return pen.contours


def frame_of(font, gname, pad=0.12):
    """固定框：以原字外接框为准，前后共用。"""
    pts = np.asarray([p for c in _outline(font, gname) for p in c], dtype=float)
    xmin, ymin = pts.min(axis=0)
    xmax, ymax = pts.max(axis=0)
    span = max(xmax - xmin, ymax - ymin) * (1 + 2 * pad)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    return (cx - span / 2, cy - span / 2, span)


def render_fixed(font, gname, frame, px):
    fx, fy, span = frame
    margin = px * 0.05
    scale = (px - 2 * margin) / span

    def to_px(p):
        return ((p[0] - fx) * scale + margin, px - ((p[1] - fy) * scale + margin))

    contours = _outline(font, gname)
    rows = []
    for c in contours:
        a = sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1]
                for i in range(len(c))) / 2
        rows.append((abs(a), a, [to_px(p) for p in c]))
    rows.sort(key=lambda r: -r[0])
    img = Image.new("L", (px, px), 0)
    dr = ImageDraw.Draw(img)
    if not rows:
        return np.zeros((px, px), bool), scale
    outer_sign = 1 if rows[0][1] > 0 else -1
    for _, a, poly in rows:
        if a == 0:
            continue
        dr.polygon(poly, fill=255 if (1 if a > 0 else -1) == outer_sign else 0)
    return np.asarray(img) > 127, scale


def hooks_of(font, gname, frame, px):
    mask, scale = render_fixed(font, gname, frame, px)
    sk = skeletonize(mask)
    dist = ndimage.distance_transform_edt(mask)
    out = []
    for cut, removed, w in raster_hooks(mask, sk, dist):
        y, x = int(removed[0][0]), int(removed[0][1])
        r = float(dist[y, x])
        if not np.isfinite(r) or r <= 1:
            continue
        out.append(dict(tip=(x, y), r_px=r, r=r / scale, path=removed, width=w))
    return out, mask


def tips_of(font, gname, px=2000):
    """用**和切割完全相同**的栅格检出钩，返回字体坐标下的 (tip, r, root)。

    核验必须复用切割时的栅格，否则两边检出的是不同的钩——第一版用 `render_fixed`
    重检，`了` 在那边一处钩都没有，而在 `raster_mask` 这边有一处，核验和切割各说各话。
    """
    from stroke_width_normalize_prototype import raster_mask

    mask, tr = raster_mask(font, gname, px, 0.08)
    xmin, ymin, scale, margin, upp, sign = tr
    sk = skeletonize(mask)
    dist = ndimage.distance_transform_edt(mask)
    out = []
    for _cut, removed, _w in raster_hooks(mask, sk, dist):
        y, x = int(removed[0][0]), int(removed[0][1])
        ry, rx = int(removed[-1][0]), int(removed[-1][1])
        to_font = lambda p: (xmin + (p[1] - margin) * upp,
                             ymin + (px - margin - p[0]) * upp)
        out.append(dict(tip=to_font((y, x)), root=to_font((ry, rx)),
                        r=float(dist[ry, rx]) * upp, path=removed))
    return out


def verify(before, after, gname, px=2000, tips=None):
    """每个原钩尖在切完之后 0.9r 球内应无墨。返回 [(tip, r, ink, gone)]。"""
    tips = tips_of(before, gname, px) if tips is None else tips
    frame = frame_of(before, gname)
    mask_after, scale = render_fixed(after, gname, frame, px)
    fx, fy, span = frame
    margin = px * 0.05
    sc = (px - 2 * margin) / span
    rows = []
    for h in tips:
        # 字体坐标 → 固定框像素
        tx = (h["tip"][0] - fx) * sc + margin
        ty = px - ((h["tip"][1] - fy) * sc + margin)
        rad = TIP_BALL * h["r"] * sc
        x0, x1 = max(0, int(tx - rad) - 1), min(mask_after.shape[1], int(tx + rad) + 2)
        y0, y1 = max(0, int(ty - rad) - 1), min(mask_after.shape[0], int(ty + rad) + 2)
        if x1 <= x0 or y1 <= y0:
            rows.append(dict(tip=h["tip"], r=h["r"], ink=-1, gone=False))
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        ball = (yy - ty) ** 2 + (xx - tx) ** 2 <= rad ** 2
        ink = int((mask_after[y0:y1, x0:x1] & ball).sum())
        frac = ink / max(1, int(ball.sum()))
        rows.append(dict(tip=h["tip"], r=h["r"], ink=ink, frac=frac,
                         gone=frac <= FILL_MAX))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--chars", default="九乙了子也包必電")
    ap.add_argument("--px", type=int, default=2000)
    args = ap.parse_args()
    b, a = TTFont(args.before), TTFont(args.after)
    cmap = b.getBestCmap()
    total = fail = 0
    for ch in args.chars:
        g = cmap[ord(ch)]
        rows = verify(b, a, g, args.px)
        total += len(rows)
        bad = [r for r in rows if not r["gone"]]
        fail += len(bad)
        cells = "  ".join(f'{"✓" if r["gone"] else "✗"}{r["frac"]*100:>5.0f}%' for r in rows)
        print(f"{ch}  r={rows[0]['r']:.1f}  " + cells if rows else f"{ch}  （原版未检出钩）")
    print(f"\n钩 {total} 处，未清除 {fail} 处")


if __name__ == "__main__":
    main()
