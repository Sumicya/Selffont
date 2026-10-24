"""原生轮廓去钩：栅格判据定位 + 矢量真半圆收笔。

`hook_cut.py` 的阈值是按别的字体调的，直接跑 Maruko 会把 `十`/`大` 判出钩、`電` 判出 8 处。
`hook_erase.find_hooks` 的骨架判据在 Maruko 上验证过是对的（`乙`2、`了`/`子`/`也`/`九`/`電`
各 1，对照组 `十`/`口`/`大` 全 0），所以用它定位。

收笔用真半圆（以闸门连线为直径，4 段二次贝塞尔），替换 `cut_hook` 的凸包。
闸门约束：只切外轮廓、弦长 0.6–2.2 倍笔宽、点跨度 ≤ 6 个锚点。

已知缺陷：闸门连线不垂直于笔身时，切口两端会留小毛刺（见 docs 第十二节），
下一步把直径强制转到垂直于笔身。原型，未接流水线。
"""
import sys, math
sys.path.insert(0,'/home/user/Selffont/tools')
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from hook_cut import split_contours
from hook_erase import find_hooks as raster_hooks
from stroke_width_normalize_prototype import raster_mask
import numpy as np

def _norm(a):
    while a <= -math.pi: a += 2*math.pi
    while a > math.pi: a -= 2*math.pi
    return a

def semicircle(contour, n, i, j, quads=4):
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    cx, cy = (ax+bx)/2, (ay+by)/2
    r = math.hypot(bx-ax, by-ay)/2
    k = max(1, min(6, n//8))
    px, py = contour[(i-k) % n][0], contour[(i-k) % n][1]
    dx, dy = ax-px, ay-py
    dl = math.hypot(dx, dy) or 1.0
    dx, dy = dx/dl, dy/dl                      # 笔身方向（指向切口）
    ox, oy = -dx, -dy                          # 外侧
    ta, tb = math.atan2(ay-cy, ax-cx), math.atan2(by-cy, bx-cx)
    to = math.atan2(oy, ox)
    # 从 ta 出发，选能经过外侧方向 to 的那一侧扫到 tb
    d1 = _norm(tb-ta); d2 = _norm(to-ta)
    if d1 >= 0:
        ok = (d2 >= 0 and d2 <= d1)
    else:
        ok = (d2 <= 0 and d2 >= d1)
    sweep = d1 if ok else (d1 - 2*math.pi if d1 > 0 else d1 + 2*math.pi)
    out = [(ax, ay, True)]
    n = quads
    for q in range(n):
        t0 = ta + sweep*q/n
        t1 = ta + sweep*(q+1)/n
        tm = (t0+t1)/2
        ctrl = (cx + r/math.cos(sweep/(2*n))*math.cos(tm),
                cy + r/math.cos(sweep/(2*n))*math.sin(tm))
        out.append((ctrl[0], ctrl[1], False))
        if q < n-1:
            p3 = (cx + r*math.cos(t1), cy + r*math.sin(t1))
            out.append((p3[0], p3[1], True))
    out.append((bx, by, True))
    return out

def _area(c):
    return sum(c[i][0]*c[(i+1) % len(c)][1] - c[(i+1) % len(c)][0]*c[i][1] for i in range(len(c)))/2

def nearest_gate(contours, target, width=None):
    tx, ty = target[0], target[1]
    radius = target[2] if len(target) > 2 else 90
    areas = [_area(c) for c in contours]
    outer = max(range(len(contours)), key=lambda k: abs(areas[k]))
    best = None
    for ci, c in enumerate(contours):
        if ci != outer:            # 只切外轮廓，内腔一律不动
            continue
        n = len(c); anchors = [i for i in range(n) if c[i][2]]
        if len(anchors) < 6: continue
        for ai, i in enumerate(anchors):
            for span in (2,3,4,5,6):
                j = anchors[(ai+span) % len(anchors)]
                if i == j: continue
                chord = math.hypot(c[i][0]-c[j][0], c[i][1]-c[j][1])
                if width and not (0.6*width <= chord <= 2.2*width):
                    continue           # 弦长必须是一笔宽的量级
                mx, my = (c[i][0]+c[j][0])/2, (c[i][1]+c[j][1])/2
                d = math.hypot(mx-tx, my-ty)
                if d < radius and (best is None or d < best[0]):
                    best = (d, ci, i, j)
    return best

def run(src, dst, chars, radius=90):
    f = TTFont(src); glyf = f['glyf']; cm = f.getBestCmap()
    done = []
    for ch in chars:
        if ord(ch) not in cm: continue
        gn = cm[ord(ch)]; g = glyf[gn]
        if g.isComposite(): continue
        mask, tr = raster_mask(f, gn, 2000, 0.08)
        xmin, ymin, scale, margin_px, upp, sign = tr
        pts = []
        for cut, path, w in raster_hooks(mask):
            cy_, cx_ = cut
            pts.append((xmin + (cx_-margin_px)*upp, ymin + (2000-margin_px-cy_)*upp))
        if not pts: continue
        coords, ends, flags = g.getCoordinates(glyf)
        contours = split_contours(coords, ends, flags)
        hits = []
        # 笔宽：骨架距离变换的中位数×2，换回字体单位
        from scipy import ndimage
        from skimage.morphology import skeletonize as _sk
        sk = _sk(mask); dist = ndimage.distance_transform_edt(mask)
        width = float(np.median(dist[sk])*2*upp)
        for t in pts:
            h = nearest_gate(contours, (t[0], t[1], radius), width)
            if h: hits.append(h)
        if not hits: continue
        new_all = []
        by = {}
        for d, ci, i, j in hits: by.setdefault(ci, (i, j))
        made = 0
        for ci, c in enumerate(contours):
            if ci not in by:
                new_all.append(c); continue
            i, j = by[ci]; n = len(c)
            rep = semicircle(c, n, i, j)
            out = [c[i]] + rep[1:]
            k = j
            while k != i:
                out.append(c[k]); k = (k+1) % n
            new_all.append(out); made += 1
        flat, new_ends = [], []
        for c in new_all:
            flat.extend(c); new_ends.append(len(flat)-1)
        g.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x, y, on in flat])
        g.flags = [bool(on) for _, _, on in flat]
        g.endPtsOfContours = new_ends
        g.recalcBounds(glyf)
        done.append((ch, made))
    f.save(dst)
    return done

if __name__ == '__main__':
    print(run('/tmp/maruko-audit/source/Regular.ttf', '/tmp/hy2.ttf', '乙了子也九包電必心十口大川三王'))
