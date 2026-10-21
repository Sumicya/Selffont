#!/usr/bin/env python3
"""马路口（Maruko Gothic）笔画粗细一致性 + 笔画比例量化审计工具（2026-10-19）。

背景：主人指出"粗细不统一、做工粗糙、笔画比例不和谐"，本工具把这句话从主观印象
变成可复查的数字，先对马路口原始三档字重（Light/Regular/Medium，未经任何处理）建立
基线，再在后续改造前后做同一套量化对比，不再只靠肉眼截图判断。

做法：
1. 用 fontTools 把每个字形的二次贝塞尔轮廓展平成折线（采样密度够高，不失真）。
2. 按轮廓有向面积正负号区分"实体"和"镂空"，在位图上做填充 + 镂空光栅化。
3. scipy 距离变换得到每个前景像素到最近背景的欧氏距离；skimage 骨架化取中轴线；
   中轴线上的距离值 *2 就是该点的局部笔画宽度估计（排除骨架端点/分叉点附近，那里
   宽度估计本来就不稳定，不是笔画粗细问题）。
4. 每个字算出笔画宽度的均值、标准差、变异系数 CV=std/mean——CV 越大说明这一个字
   内部笔画忽粗忽细越严重；跨字、跨字重再汇总一次，回答"是不是整体做工粗糙"。

用法：
  python3 tools/stroke_width_audit.py --font font-eval/maruko/MarukoGothicCJKsc-Regular.ttf \
      --chars "一二三十口日回国了乙人入八木林森永心必水走建进这远道你好中国语言文字书写规范长美丽颜色锦绣风雨雪龙马鸟虫鱼电子已己巳也包囚暖田"
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from scipy import ndimage
from skimage.morphology import skeletonize


class FlattenPen(BasePen):
    """把一个字形的所有轮廓展平成折线点列表，附带有向面积符号。"""

    def __init__(self, glyphSet, steps_per_curve=12):
        super().__init__(glyphSet)
        self.steps = steps_per_curve
        self.contours = []  # list of list[(x,y)]
        self._cur = []
        self._start = None
        self._last = None

    def _moveTo(self, pt):
        self._cur = [pt]
        self._start = pt
        self._last = pt

    def _lineTo(self, pt):
        self._cur.append(pt)
        self._last = pt

    def _qCurveToOne(self, pt1, pt2):
        p0 = np.array(self._last, dtype=float)
        p1 = np.array(pt1, dtype=float)
        p2 = np.array(pt2, dtype=float)
        for i in range(1, self.steps + 1):
            t = i / self.steps
            pt = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
            self._cur.append((float(pt[0]), float(pt[1])))
        self._last = pt2

    def _closePath(self):
        if self._cur and self._cur[0] != self._cur[-1]:
            self._cur.append(self._start)
        if len(self._cur) >= 3:
            self.contours.append(self._cur)
        self._cur = []

    def _endPath(self):
        self._closePath()


def signed_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def rasterize_glyph(font, glyph_name, px=360, margin_frac=0.08):
    glyph_set = font.getGlyphSet()
    pen = FlattenPen(glyph_set, steps_per_curve=14)
    glyph_set[glyph_name].draw(pen)
    contours = pen.contours
    if not contours:
        return None, None
    all_pts = np.array([p for c in contours for p in c], dtype=float)
    xmin, ymin = all_pts.min(axis=0)
    xmax, ymax = all_pts.max(axis=0)
    w = xmax - xmin
    h = ymax - ymin
    if w <= 0 or h <= 0:
        return None, None
    span = max(w, h)
    margin = span * margin_frac
    scale = (px - 2 * (px * margin_frac)) / span
    # 坐标变换到像素网格（y 轴翻转，图像坐标原点在左上）
    def to_px(pt):
        x, y = pt
        return ((x - xmin) * scale + px * margin_frac,
                px - ((y - ymin) * scale + px * margin_frac))

    cont_px = []
    for c in contours:
        area = signed_area(c)
        cont_px.append((abs(area), area, [to_px(p) for p in c]))
    cont_px.sort(key=lambda t: -t[0])  # 大轮廓先画，保证镂空嵌套顺序

    from PIL import Image, ImageDraw
    img = Image.new("L", (px, px), 0)
    draw = ImageDraw.Draw(img)
    ref_sign = None
    for _, area, pts in cont_px:
        if ref_sign is None:
            ref_sign = 1 if area > 0 else -1
            fill = 255
        else:
            fill = 255 if (1 if area > 0 else -1) == ref_sign else 0
        draw.polygon(pts, fill=fill)
    mask = np.array(img) > 127
    units_per_px = span / (px - 2 * (px * margin_frac))
    return mask, units_per_px


def measure_widths(mask, units_per_px, trim_border=3):
    if mask.sum() == 0:
        return np.array([])
    dist = ndimage.distance_transform_edt(mask)
    skel = skeletonize(mask)
    # 去掉骨架在画布边缘附近的像素（裁切误差），以及用 3x3 邻域内骨架像素数判断
    # 是否为分叉/端点（那里宽度估计本就失真，不计入"笔画宽度"统计）。
    ys, xs = np.nonzero(skel)
    if len(xs) == 0:
        return np.array([])
    neighbor_count = ndimage.convolve(
        skel.astype(int), np.ones((3, 3)), mode="constant", cval=0
    ) - skel.astype(int)
    good = []
    h, w = mask.shape
    for y, x in zip(ys, xs):
        if y < trim_border or x < trim_border or y >= h - trim_border or x >= w - trim_border:
            continue
        if neighbor_count[y, x] >= 3:  # 分叉点，跳过
            continue
        good.append(dist[y, x])
    widths = np.array(good) * 2.0 * units_per_px
    return widths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    ap.add_argument("--chars", required=True)
    ap.add_argument("--px", type=int, default=360)
    args = ap.parse_args()

    font = TTFont(args.font)
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm

    rows = []
    all_widths = []
    for ch in args.chars:
        cp = ord(ch)
        if cp not in cmap:
            print(f"!! {ch} (U+{cp:04X}) 不在 cmap 中，跳过", file=sys.stderr)
            continue
        glyph_name = cmap[cp]
        mask, upx = rasterize_glyph(font, glyph_name, px=args.px)
        if mask is None:
            print(f"!! {ch} 空字形，跳过", file=sys.stderr)
            continue
        widths = measure_widths(mask, upx)
        if len(widths) < 5:
            print(f"!! {ch} 骨架像素太少（{len(widths)}），跳过", file=sys.stderr)
            continue
        mean_w = widths.mean()
        std_w = widths.std()
        cv = std_w / mean_w if mean_w > 0 else float("nan")
        rows.append((ch, mean_w, std_w, cv, len(widths)))
        all_widths.append(widths)

    print(f"字体: {args.font}  upm={upm}")
    print(f"{'字':<4}{'均宽(font units)':>18}{'标准差':>12}{'CV=std/mean':>14}{'采样点数':>10}")
    for ch, mean_w, std_w, cv, n in rows:
        print(f"{ch:<4}{mean_w:>18.1f}{std_w:>12.1f}{cv:>14.3f}{n:>10d}")

    if rows:
        means = np.array([r[1] for r in rows])
        cvs = np.array([r[3] for r in rows])
        print("-" * 58)
        print(f"跨字均宽: 均值={means.mean():.1f}  标准差={means.std():.1f}  "
              f"变异系数={means.std()/means.mean():.3f}  (这一项越大说明不同字之间"
              f"主干笔画粗细越不一致，理论上同一字重所有字的笔画宽度应该高度接近)")
        print(f"单字内部 CV 均值={cvs.mean():.3f}  最大={cvs.max():.3f} "
              f"(字={rows[int(cvs.argmax())][0]})  "
              f"(这一项衡量单个字内部笔画忽粗忽细的程度)")


if __name__ == "__main__":
    main()
