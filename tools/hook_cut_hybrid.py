"""原生轮廓去钩：栅格判据定位 + 顺笔势收尖。

定位用 `hook_erase.find_hooks`（骨架判据，在 Maruko 上验证过：`乙`2、`了`/`子`/`也`/`九`/`電`
各 1，对照组 `十`/`口`/`大` 全 0）；`hook_cut.py` 的绝对阈值在 Maruko 上误报，不用。

收尾不是剪断接圆头，而是**顺笔势**：从闸门沿笔势继续走一段，再收成捺尖——
主人给的方向（`九` 横折弯钩、`气` 横折提 → 顺成横捺）。

闸门约束：只切外轮廓（有向面积最大者）、弦长 0.6–2.2 倍笔宽、点跨度 ≤ 6 个锚点。

已知缺陷：笔势只从切口往回取 6 个点估，捺尖左右对称、没按实际笔锋走向，
`九` 收尾会甩、`气` 只剩短桩（见 docs 12.3）。原型，未接流水线。
"""
import sys, math
sys.path.insert(0,'/home/user/Selffont/tools')
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
from hook_cut import split_contours
from hook_erase import find_hooks as raster_hooks
from stroke_width_normalize_prototype import raster_mask
import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

def _area(c):
    return sum(c[i][0]*c[(i+1)%len(c)][1] - c[(i+1)%len(c)][0]*c[i][1] for i in range(len(c)))/2

def nearest_gate(contours, target, width, radius):
    tx, ty = target
    outer = max(range(len(contours)), key=lambda k: abs(_area(contours[k])))
    best = None
    c = contours[outer]; n = len(c)
    anchors = [i for i in range(n) if c[i][2]]
    if len(anchors) < 6: return None
    for ai, i in enumerate(anchors):
        for span in (2,3,4,5,6):
            j = anchors[(ai+span) % len(anchors)]
            if i == j: continue
            chord = math.hypot(c[i][0]-c[j][0], c[i][1]-c[j][1])
            if not (0.6*width <= chord <= 2.2*width): continue
            mx, my = (c[i][0]+c[j][0])/2, (c[i][1]+c[j][1])/2
            d = math.hypot(mx-tx, my-ty)
            if d < radius and (best is None or d < best[0]):
                best = (d, outer, i, j)
    return best

def unroll(contour, i, j):
    """把 i..j 之间的钩换成沿笔势顺下去的捺尖收尾。"""
    n = len(contour)
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    cx, cy = (ax+bx)/2, (ay+by)/2
    w = math.hypot(bx-ax, by-ay)/2
    k = max(1, min(6, n//8))
    px, py = contour[(i-k) % n][0], contour[(i-k) % n][1]
    dx, dy = cx-px, cy-py
    dl = math.hypot(dx, dy) or 1.0
    dx, dy = dx/dl, dy/dl                       # 笔势（朝外）
    # 钩本身探出去多远：取被删掉那段里离闸门中线最远的距离
    span = []
    m = i
    while m != j:
        span.append(contour[m]); m = (m+1) % n
    hook_len = max((math.hypot(p[0]-cx, p[1]-cy) for p in span), default=w)
    ext = max(hook_len*0.55, w*0.8)             # 先顺着笔势走一段
    taper = max(hook_len*0.9, w*1.1)            # 再收成尖
    p1 = (ax+dx*ext, ay+dy*ext)
    p2 = (bx+dx*ext, by+dy*ext)
    tip = (cx+dx*(ext+taper), cy+dy*(ext+taper))
    c1 = (p1[0]+dx*taper*0.55, p1[1]+dy*taper*0.55)
    c2 = (p2[0]+dx*taper*0.55, p2[1]+dy*taper*0.55)
    return [(ax, ay, True), (p1[0], p1[1], True),
            (c1[0], c1[1], False), (tip[0], tip[1], True),
            (c2[0], c2[1], False), (p2[0], p2[1], True), (bx, by, True)]

def run(src, dst, chars, radius=90):
    f = TTFont(src); glyf = f['glyf']; cm = f.getBestCmap(); done=[]
    for ch in chars:
        if ord(ch) not in cm: continue
        gn = cm[ord(ch)]; g = glyf[gn]
        if g.isComposite(): continue
        mask, tr = raster_mask(f, gn, 2000, 0.08)
        xmin, ymin, scale, margin_px, upp, sign = tr
        sk = skeletonize(mask); dist = ndimage.distance_transform_edt(mask)
        width = float(np.median(dist[sk])*2*upp)
        pts = []
        for cut, path, w in raster_hooks(mask):
            cy_, cx_ = cut
            pts.append((xmin+(cx_-margin_px)*upp, ymin+(2000-margin_px-cy_)*upp))
        if not pts: continue
        coords, ends, flags = g.getCoordinates(glyf)
        contours = split_contours(coords, ends, flags)
        hits = [h for h in (nearest_gate(contours, t, width, radius) for t in pts) if h]
        if not hits: continue
        by = {}
        for d, ci, i, j in hits: by.setdefault(ci, (i, j))
        new_all = []
        for ci, c in enumerate(contours):
            if ci not in by: new_all.append(c); continue
            i, j = by[ci]
            out = [c[i]] + unroll(c, i, j)[1:]
            k = j
            while k != i:
                out.append(c[k]); k = (k+1) % n if False else (k+1) % len(c)
            new_all.append(out)
        flat, new_ends = [], []
        for c in new_all:
            flat.extend(c); new_ends.append(len(flat)-1)
        g.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x,y,on in flat])
        g.flags = [bool(on) for _,_,on in flat]
        g.endPtsOfContours = new_ends
        g.recalcBounds(glyf)
        done.append(ch)
    f.save(dst)
    return done

if __name__=='__main__':
    print(run('/tmp/maruko-audit/source/Regular.ttf','/tmp/un.ttf','九气乙也包子了心電必'))
