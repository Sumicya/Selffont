"""原生轮廓去钩：栅格判据定位 + 矢量切。

`hook_cut.py` 的 `find_hooks` 阈值是按别的字体调的，直接跑 Maruko 误报严重（`十`/`大`/`王`/`川`
这些没有钩的字都会被判出钩）。`hook_erase.find_hooks` 的骨架判据在 Maruko 上验证过是对的
（`乙`2/`了`1/`子`1/`也`1/`九`1/`電`1，对照组 `十`/`口`/`大` 全 0）。

所以分工：栅格判断"哪里是钩"，矢量负责"怎么切"——把掩膜坐标的剪除点换回字体单位，在原生
轮廓上找中点离它最近的闸门对，再用 `hook_cut.cut_hook` 补圆头。曲线和点数不动，只切端头。

原型，尚未接流水线。
"""
import sys, math, numpy as np
sys.path.insert(0,'/home/user/Selffont/tools')
from fontTools.ttLib import TTFont
from hook_erase import find_hooks as raster_hooks
from hook_cut import split_contours, apply_hook_cuts
from stroke_width_normalize_prototype import raster_mask

def cut_points_font_units(font, gname, px=2000, margin_frac=0.08):
    mask, tr = raster_mask(font, gname, px, margin_frac)
    xmin, ymin, scale, margin_px, upp, sign = tr
    hooks = raster_hooks(mask)
    pts=[]
    for cut, path, width_px in hooks:
        cy, cx = cut
        x = xmin + (cx - margin_px) * upp
        y = ymin + (px - margin_px - cy) * upp
        pts.append((x, y, width_px * upp))
    return pts

def nearest_gate_pair(contours, target, radius):
    tx, ty, r = target
    best=None
    for ci,c in enumerate(contours):
        n=len(c); anchors=[i for i in range(n) if c[i][2]]
        if len(anchors)<6: continue
        for ai,i in enumerate(anchors):
            for span in (2,3,4,5,6):
                j=anchors[(ai+span)%len(anchors)]
                if i==j: continue
                mx=(c[i][0]+c[j][0])/2; my=(c[i][1]+c[j][1])/2
                d=math.hypot(mx-tx,my-ty)
                if d<radius and (best is None or d<best[0]):
                    best=(d,ci,i,j)
    return best

def run(src, dst, chars, radius=90):
    f=TTFont(src); glyf=f['glyf']; cm=f.getBestCmap(); done=[]
    for ch in chars:
        if ord(ch) not in cm: continue
        gn=cm[ord(ch)]; g=glyf[gn]
        if g.isComposite(): continue
        targets=cut_points_font_units(f,gn)
        if not targets: continue
        coords,ends,flags=g.getCoordinates(glyf)
        contours=split_contours(coords,ends,flags)
        hooks=[]
        for t in targets:
            hit=nearest_gate_pair(contours,t,radius)
            if hit: hooks.append((hit[1],hit[2],hit[3]))
        if hooks:
            made=apply_hook_cuts(g,glyf,hooks)
            done.append((ch,len(targets),made))
    f.save(dst)
    return done

if __name__=='__main__':
    print(run('/tmp/maruko-audit/source/Regular.ttf','/tmp/hy.ttf','乙了子也九包電必心十口大川三王'))
