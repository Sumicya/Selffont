"""只删三个逐字量过的碎块，靠 bbox 精确匹配，不做启发式。

为什么不用规则：试过 5 种（同形兄弟/比主体低/整块沉底/形状分桶/跨字部件），
每一种都会误删真部件（壘的六个田、劙的四个刂、靐的三个田、龘的部件）。
所以这里写死三个字的 bbox，删不到就报错，绝不"大概删掉"。

逐字读数（upm 1000，母版 mother.ttf）：
  日 uni65E5 轮廓0 bbox(773,788)-(828,833) 面积1971  ← 飘在日框上沿 y=763 之外 25
  让 uni8BA9 轮廓3 bbox(117,-49)-(211,34)  面积4576  ← 沉到言旁底 y=10 之下 59
  论 uni8BBA 轮廓4 bbox(109,-39)-(161,16)  面积1804  ← 沉到言旁底之下 49
"""
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

TARGETS = {
    0x65E5: (773, 788, 828, 833),   # 日
    0x8BA9: (117, -49, 211, 34),    # 让
    0x8BBA: (109, -39, 161, 16),    # 论
}

src, dst = sys.argv[1], sys.argv[2]
font = TTFont(src)
gs = font.getGlyphSet()
cmap = font.getBestCmap()
glyf = font["glyf"]

def split_ops(gname):
    pen = RecordingPen(); gs[gname].draw(pen)
    out, cur = [], []
    for op, a in pen.value:
        if op == "moveTo":
            if cur: out.append(cur)
            cur = [(op, a)]
        elif op == "closePath":
            cur.append((op, a)); out.append(cur); cur = []
        else:
            cur.append((op, a))
    if cur: out.append(cur)
    return out

def pts_of(c):
    return [p for _o, a in c for p in a if isinstance(p, tuple)]

removed = []
for cp, box in TARGETS.items():
    ch = chr(cp)
    g = cmap[cp]
    cs = split_ops(g)
    keep, hit = [], None
    for c in cs:
        p = pts_of(c)
        if not p:
            keep.append(c); continue
        bb = (min(q[0] for q in p), min(q[1] for q in p),
              max(q[0] for q in p), max(q[1] for q in p))
        if bb == box:
            hit = (bb, len(p)); continue      # 精确匹配才删
        keep.append(c)
    if hit is None:
        print(f"[失败] {ch} 找不到 bbox={box} 的轮廓，未改动")
        continue
    if len(keep) == len(cs):
        continue
    tp = TTGlyphPen(None)
    for c in keep:
        for op, a in c:
            getattr(tp, op)(*a)
    glyf[g] = tp.glyph()
    removed.append((ch, hit[0], hit[1]))

print(f"删除 {len(removed)} 个轮廓：")
for ch, bb, n in removed:
    print(f"  {ch} bbox={bb} 点数={n}")
assert len(removed) == 3, f"只删到 {len(removed)}/3 个，中止"
font.save(dst)
print(f"写出 {dst}")
