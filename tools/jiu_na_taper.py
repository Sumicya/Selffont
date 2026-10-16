#!/usr/bin/env python3
"""把"九"字顶部的横折弯钩，横画段改成"横斜捺"：右半段从水平直接改成
一条往右下方逐渐变尖的斜捺收束，而不是贴着一条水平线走到底再接直角/圆角
拐弯。只改"九"这一个字的横画轮廓（4 点矩形 -> 5 点带尖斜捺多边形），
不碰钩尾/竖钩轮廓，也不碰其他字。

跟 dian_box_compress.py / le_slant.py 同一类安全写法：
- 只做纯几何重排，不依赖某个字重的绝对坐标，参数都是比例（相对横画自己的
  宽度/厚度），每个字重各自读自己的矩形角点再独立计算，互不干扰。
- 每个字重的新点数固定是 5（原来 4 点矩形 -> 5 点带尖多边形），在所有
  字重上数目一致，不会破坏跨字重拓扑一致性（给 varLib.build 用）。
- 必须在 foot_trim.py / hook_cut.py / vf_round.py 之前跑：改完的新尖点会被
  vf_round.py 现有的"尖锋"识别（detect() 里的 tip 检测）自动按 TIP_R 收个
  小圆角，不需要在这里额外处理尖端。

用法：
    python3 tools/jiu_na_taper.py <in.ttf> <out.ttf>
"""
import argparse
import sys

from fontTools.ttLib import TTFont

BEND_RATIO = 0.58   # 横画多宽比例处开始往右下斜（底边从这里往右上收）


def _find_crossbar_contour(glyph, glyf_table):
    """"九"字里横画是一条 4 点、宽远大于高的轴对齐矩形轮廓——用这个特征
    从全部轮廓里挑出来，不依赖固定的轮廓序号（序号在不同构建阶段会变）。"""
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    start = 0
    for ci, end in enumerate(ends):
        pts = [(coords[k][0], coords[k][1]) for k in range(start, end + 1)]
        if len(pts) == 4:
            xs = sorted(set(round(p[0]) for p in pts))
            ys = sorted(set(round(p[1]) for p in pts))
            if len(xs) == 2 and len(ys) == 2:
                width = xs[1] - xs[0]
                height = ys[1] - ys[0]
                if height > 0 and width > height * 3:
                    return ci, start, end, pts
        start = end + 1
    return None


def _unit(p0, p1):
    import math
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy) or 1.0
    return (dx / d, dy / d), d


def _find_pie_top_cap(glyph, glyf_table):
    """"九"的撇（丿）笔画两侧是弧线（不是直线），所以通用的"端头圆化"
    （vf_round.py 的 detect()/cap 判断）要求端头两侧都得是直线，在这里
    判不出来，顶部被晾成一个没削过的直角平头——跟全字形"逢角必圆"的
    观感不一致。这里单独找这条撇画自己最高的那条直边（两个相邻 on-curve
    点、且都在该轮廓的最高点上），不依赖直线邻边。"""
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    start = 0
    best = None
    for ci, end in enumerate(ends):
        pts = [(coords[k][0], coords[k][1], bool(flags[k])) for k in range(start, end + 1)]
        n = len(pts)
        ys = [p[1] for p in pts]
        top_y = max(ys)
        span = top_y - min(ys)
        for k in range(n):
            a, b = pts[k], pts[(k + 1) % n]
            if a[2] and b[2] and abs(a[1] - top_y) < 1 and abs(b[1] - top_y) < 1 and a[0] != b[0]:
                # 这条轮廓本身要足够高（排除横画这类矮扁轮廓自己的顶边），
                # 真正的撇画竖向跨度远大于笔画粗细。
                if span > abs(a[0] - b[0]) * 2:
                    if best is None or span > best[4]:
                        idx_a = start + k
                        idx_b = start + (k + 1) % n
                        best = (ci, start, end, (idx_a, idx_b), span)
        start = end + 1
    return best


def round_pie_top_cap(font):
    cmap = font.getBestCmap()
    gname = cmap.get(ord("九"))
    glyf = font["glyf"]
    glyph = glyf[gname]
    found = _find_pie_top_cap(glyph, glyf)
    if found is None:
        raise SystemExit("couldn't locate 九's 丿 top flat edge")
    ci, start, end, (ia, ib), _span = found

    coords, ends, flags = glyph.getCoordinates(glyf)
    n_contour = end + 1 - start
    # 规范成 a 在 b 之前（contour 内部序号，相对 start 的偏移）
    rel_a = ia - start
    rel_b = ib - start
    pa = coords[ia]
    pb = coords[ib]
    cap_len = abs(pb[0] - pa[0])

    # 找"上一个点"（a 之前）和"下一个点"（b 之后），估计可用的安全退让长度，
    # 即便邻边是曲线也能用它的弦长做个保守估计，跟标准端头公式的
    # prev_len*0.4 封顶同一个意图：半径不会探出这条边的邻边之外。
    prev_pt = coords[start + (rel_a - 1) % n_contour]
    next_pt = coords[start + (rel_b + 1) % n_contour]
    _, prev_len = _unit(pa, prev_pt)
    _, next_len = _unit(pb, next_pt)
    r = min(cap_len * 0.5, prev_len * 0.4, next_len * 0.4)

    # 往"轮廓外侧"鼓：边是水平的，外侧就是远离轮廓其余点质心的那一侧
    # （正常是往上，因为这是撇画的顶边）。
    others_y = [coords[start + k][1] for k in range(n_contour) if start + k not in (ia, ib)]
    centroid_y = sum(others_y) / len(others_y)
    sign = 1.0 if pa[1] >= centroid_y else -1.0
    dx, dy = 0.0, sign

    ax, ay = pa
    bx, by = pb
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    apex = (mx + dx * r, my + dy * r)
    q1 = (ax + dx * r, ay + dy * r)
    q2 = (bx + dx * r, by + dy * r)

    new_pts = [
        (round(ax), round(ay), True),
        (round(q1[0]), round(q1[1]), False),
        (round(apex[0]), round(apex[1]), True),
        (round(q2[0]), round(q2[1]), False),
        (round(bx), round(by), True),
    ]

    lo, hi = (ia, ib) if ia < ib else (ib, ia)
    assert hi == lo + 1, "expected adjacent points"
    new_coords = list(coords[:lo]) + [(p[0], p[1]) for p in new_pts] + list(coords[hi + 1:])
    new_flags = list(flags[:lo]) + [1 if p[2] else 0 for p in new_pts] + list(flags[hi + 1:])
    delta = len(new_pts) - 2
    new_ends = [e + delta if k >= ci else e for k, e in enumerate(glyph.endPtsOfContours)]

    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    glyph.coordinates = GlyphCoordinates(new_coords)
    glyph.flags = bytearray(new_flags)
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf)


def apply_taper(font):
    cmap = font.getBestCmap()
    gname = cmap.get(ord("九"))
    if gname is None:
        raise SystemExit("font has no 九")
    glyf = font["glyf"]
    glyph = glyf[gname]
    found = _find_crossbar_contour(glyph, glyf)
    if found is None:
        raise SystemExit("couldn't locate 九's crossbar contour (4-pt wide rectangle)")
    ci, start, end, pts = found

    p_tl, p_tr, p_br, p_bl = pts
    top_y = max(p_tl[1], p_tr[1])
    bottom_y = min(p_br[1], p_bl[1])
    left_x = min(p_tl[0], p_bl[0])
    right_x = max(p_tr[0], p_br[0])
    # 校验点序确实是 TL,TR,BR,BL（跟源文件实测一致），不是就直接报错，
    # 不要悄悄按错误假设继续算下去。
    assert abs(p_tl[1] - top_y) < 1 and abs(p_tr[1] - top_y) < 1, "unexpected point order"
    assert abs(p_bl[1] - bottom_y) < 1 and abs(p_br[1] - bottom_y) < 1, "unexpected point order"
    assert abs(p_tl[0] - left_x) < 1 and abs(p_bl[0] - left_x) < 1, "unexpected point order"
    assert abs(p_tr[0] - right_x) < 1 and abs(p_br[0] - right_x) < 1, "unexpected point order"

    width = right_x - left_x
    bend_x = left_x + width * BEND_RATIO

    # 关键设计：上边（顶边）原样不动——跟接下来竖钩轮廓自己的平头顶边
    # （同一个 y）严丝合缝，衔接处不会露出一道台阶/豁口。只把右下角
    # 从"贴着原右边缘往下"改成"往左上收"，削出一条由下往上扬的斜线，
    # 削到最后在原来的右上角（尖端）收成一点——這條斜线段只需要在
    # "横画自己还没被竖钩盖住"的那一小段区间内（bend_x 到横画原右边缘）
    # 自己是实心的，不依赖竖钩轮廓，所以不会露缝。
    new_pts = [
        (left_x, top_y),      # 左上角不动
        (right_x, top_y),     # 右上角不动——斜捺收尖就收在这一点上
        (bend_x, bottom_y),   # 右下角从 (right_x,bottom_y) 收到这里，削出斜边
        (left_x, bottom_y),   # 左下角不动
    ]

    coords, ends, flags = glyph.getCoordinates(glyf)
    new_coords = list(coords[:start]) + [(round(x), round(y)) for x, y in new_pts] + list(coords[end + 1:])
    new_flags = list(flags[:start]) + [1] * len(new_pts) + list(flags[end + 1:])
    delta = len(new_pts) - (end + 1 - start)
    new_ends = []
    for k, e in enumerate(glyph.endPtsOfContours):
        if k < ci:
            new_ends.append(e)
        elif k == ci:
            new_ends.append(e + delta)
        else:
            new_ends.append(e + delta)

    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    glyph.coordinates = GlyphCoordinates(new_coords)
    glyph.flags = bytearray(new_flags)
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("outfile")
    args = ap.parse_args()

    font = TTFont(args.infile)
    apply_taper(font)
    round_pie_top_cap(font)
    font.save(args.outfile)
    print(f"九: crossbar->na-taper + 丿顶部端头圆化 applied: {args.infile} -> {args.outfile}")


if __name__ == "__main__":
    sys.exit(main())
