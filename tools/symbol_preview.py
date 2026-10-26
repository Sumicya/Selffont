"""符号预览：真实二次贝塞尔展开 + 真正的扫描线填充（nonzero 规则）。

为什么不用 PIL 的 polygon 逐条填
-------------------------------
PIL 只能一个一个多边形填，遇到「外框 + 内白 + 内白里再挖一块」这种嵌套，靠
"与最大轮廓同向就填白" 判断会错——方框类字形的内白全被填成了实心块。
这里改成按 nonzero 绕向规则做扫描线，嵌套多少层都正确。
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def flatten(pathobj, subdiv=12):
    """pathops.Path → 折线列表。按 qCurveTo 真实展开（不能把控制点连折线）。"""
    contours = []
    for contour in pathobj.contours:
        pts = [(float(x), float(y)) for x, y in contour.points]
        if not pts:
            continue
        cur = [pts[0]]
        i = 1
        while i < len(pts):
            if i + 1 < len(pts):
                p0, c, p1 = cur[-1], pts[i], pts[i + 1]
                for k in range(1, subdiv + 1):
                    t = k / subdiv
                    cur.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
                                (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1]))
                i += 2
            else:
                cur.append(pts[i])
                i += 1
        contours.append(cur)
    return contours


def render(pathobj, px=300, box=(-40, -40, 1040, 1040), ss=4):
    """扫描线 + nonzero 绕向填充。ss 是超采样倍数。"""
    x0, y0, x1, y1 = box
    size = px * ss
    sc = size / (y1 - y0)
    polys = []
    for c in flatten(pathobj):
        poly = np.asarray([((x - x0) * sc, size - 1 - (y - y0) * sc) for x, y in c], float)
        if len(poly) >= 3:
            polys.append(poly)
    if not polys:
        return Image.new("L", (px, px), 0)

    edges = []
    for poly in polys:
        n = len(poly)
        for i in range(n):
            a = poly[i]
            b = poly[(i + 1) % n]
            if a[1] == b[1]:
                continue
            # 方向对绕向计数：向上为 +1，向下为 -1
            edges.append((a[0], a[1], b[0], b[1], 1 if b[1] > a[1] else -1))

    ys = np.arange(size)
    acc = np.zeros(size, dtype=np.float32)
    buckets = {}
    for ex0, ey0, ex1, ey1, w in edges:
        lo = int(np.ceil(min(ey0, ey1)))
        hi = int(np.floor(max(ey0, ey1)))
        for y in range(max(0, lo), min(size - 1, hi) + 1):
            buckets.setdefault(y, []).append((ex0, ey0, ex1, ey1, w))

    img = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(img)
    for y, items in buckets.items():
        xy = []
        for ex0, ey0, ex1, ey1, w in items:
            t = (y + 0.5 - ey0) / (ey1 - ey0)
            xy.append((ex0 + t * (ex1 - ex0), w))
        xy.sort()
        wind = 0
        span_start = None
        for x, w in xy:
            prev = wind
            wind += w
            if prev == 0 and wind != 0:
                span_start = x
            elif prev != 0 and wind == 0 and span_start is not None:
                dr.line([(span_start, y), (x, y)], fill=255, width=1)
                span_start = None
    return img.resize((px, px), Image.LANCZOS)
