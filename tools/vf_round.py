#!/usr/bin/env python3
"""VF 版 Selffont Round:在多个字重实例间共用同一套"该不该圆"的结构判断,
只在参照字重(默认 Regular)上跑一次检测,把"哪些锚点是端头/尖锋"的结论
(按锚点在轮廓里的序号记,不是坐标)原样套到其余字重的同名字形上——
每个字重用自己的坐标重新算方向向量/半径,但「切哪一段、切几刀」对
所有字重完全一致，因此圆角之后各字重之间仍然点数/点序一致，能喂给
fontTools.varLib.build 重建可变字体。

前提（已验证）：同一支 VF 用 varLib.instancer 钉出的静态实例之间，
圆角前本来就是逐字形点数/点序相同（本仓库 build/round_test 下验证过
WenYuanSansSCVF 的 35139 个非空形全部一致，0 处不同）。

用法：
  python3 vf_round.py --ref Regular.ttf <name1=path1> <name2=path2> ... --outdir OUT
"""
import argparse
import math
import os

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates

import round as R  # 复用阈值常量、_unit、_is_straight_wrap、rename_family

MIN_CAP, MAX_CAP = R.MIN_CAP, R.MAX_CAP
NEIGHBOR, COS_LIMIT, PARALLEL = R.NEIGHBOR, R.COS_LIMIT, R.PARALLEL
TIP_DOT, TIP_R = R.TIP_DOT, R.TIP_R
_unit = R._unit
_is_straight_wrap = R._is_straight_wrap


def _split_contours(glyph, glyf_table):
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    points = [(float(x), float(y), bool(on)) for (x, y), on in zip(coords, flags)]
    contours = []
    start = 0
    for end in ends:
        contours.append(points[start:end + 1])
        start = end + 1
    return contours


CORNER_MIN_ANGLE = math.radians(60)   # 转角须落在这个范围内才算"该不该圆"的直角拐角
CORNER_MAX_ANGLE = math.radians(120)  # （太尖是尖锋走 round_tips，太钝不像拐角）
CORNER_NEIGHBOR = 3.0                 # 两侧边至少是圆角半径的倍数，避免拐角贴得太近互相吃穿
CORNER_R_RATIO = 0.42                 # 圆角半径 = min(两侧边长) * 这个比例（经验值，先在国/回/田上试）
CORNER_R_MAX = 130                    # 绝对半径上限（1000upm）。实测量过筑紫"回"外框拐角的实际
                                       # 切角跨度约 120-130 单位，原来定的 70 太保守、肉眼看不出来，
                                       # 这版按参照实测值改大，让效果在正常网页字号下也看得见。
CORNER_SHARED_RATIO = 0.16            # 两个拐角紧挨着同一截短连接段时，各自改用这个更保守
                                       # 的比例（两头加起来约 0.32，留三分之二不碰，避免互相自交）
CORNER_SHORT_SHARED = 200              # 两个拐角之间的连接段短于这个值(1000upm)才算"短段"，
                                        # 两头都不圆；国/回外框那种长边不受影响


def _contour_winding(contour, anchors):
    """锚点多边形的有向面积符号：正=逆时针，负=顺时针（标准数学 y 朝上坐标）。"""
    area = 0.0
    pts = [(contour[i][0], contour[i][1]) for i in anchors]
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return 1 if area > 0 else -1


def _glyph_polys(contours):
    """把整个字形的所有轮廓近似成多边形（只取各轮廓点序列，曲线按折线近似——本
    字体笔画基本是直线/浅弧，够用于"这一点算不算落在字形实心区域里"的粗判断）。
    用来识别："这段看起来像笔画端头的直边，是不是其实已经被另一个轮廓盖住了"——
    比如王字中间那一竖往往故意多画一截插进横画里保证压字不露缝，这截独立看长度
    符合"端头"判定，但它根本没有暴露在背景里，不该被削成一个鼓包。
    """
    polys = []
    for contour in contours:
        pts = [(p[0], p[1]) for p in contour]
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def _winding_number(x, y, polys):
    """标准环绕数算法（nonzero 填充规则），测试 (x,y) 是否落在多边形并集内部。"""
    wn = 0
    for poly in polys:
        n = len(poly)
        for k in range(n):
            x1, y1 = poly[k]
            x2, y2 = poly[(k + 1) % n]
            if y1 <= y:
                if y2 > y and (x2 - x1) * (y - y1) - (x - x1) * (y2 - y1) > 0:
                    wn += 1
            else:
                if y2 <= y and (x2 - x1) * (y - y1) - (x - x1) * (y2 - y1) < 0:
                    wn -= 1
    return wn


def _point_covered(x, y, polys):
    return _winding_number(x, y, polys) != 0


def detect_corners(contour, n, anchors, straight, cap_anchor_set, tip_set):
    """找"该不该仿筑紫逢角必圆"的直角拐角：两条长直线之间的凸角（不是自由端头、
    不是尖锋、也不是 T 形接口留下的凹切口——凹切口用绕行方向的凸/凹判断剔除）。
    返回 {anchor 原始点序号: half_radius_hint}（半径按该字重自己的边长重算，这里
    只记录"要不要圆"这个结构决定，跟 cap/tip 共用同一套"检测一次、各字重复用"的模型）。
    """
    if len(anchors) < 4:
        return set()
    winding = _contour_winding(contour, anchors)
    corners = set()
    for k, i in enumerate(anchors):
        if i in cap_anchor_set or i in tip_set:
            continue
        h = anchors[(k - 1) % len(anchors)]
        j = anchors[(k + 1) % len(anchors)]
        if not (straight.get((h, i)) and straight.get((i, j))):
            continue
        d_in, len_in = _unit(contour[h], contour[i])
        d_out, len_out = _unit(contour[i], contour[j])
        if len_in < 4 or len_out < 4:
            continue
        cross = d_in[0] * d_out[1] - d_in[1] * d_out[0]
        dot = max(-1.0, min(1.0, d_in[0] * d_out[0] + d_in[1] * d_out[1]))
        angle = math.acos(dot)  # 转角大小（0~180°），不含方向
        if not (CORNER_MIN_ANGLE <= angle <= CORNER_MAX_ANGLE):
            continue
        turn_sign = 1 if cross > 0 else -1
        if turn_sign != winding:
            continue  # 转向跟整条轮廓的绕行方向相反 = 凹切口（T 形接口的痕迹），不碰
        # 半径按 min(len_in, len_out)*CORNER_R_RATIO（<0.5）取，天然不会吃穿任何一边，
        # 这里不需要再叠一层"边长须是半径几倍"的门槛（之前写的那层在两边长度接近时
        # 数学上永远不可能满足，等于把所有正常方角都滤掉了）。
        corners.add(i)
    if not corners:
        return corners
    # 两个拐角紧挨着同一截"短"连接段（比如钩笔的钩尖，两头各是一个 ~90°拐角、
    # 中间就隔几十到一百多单位）：各自削一刀圆出来的两段弧在中间碰头，哪怕各自
    # 半径都收得很小也会在接缝处留一个方向不连续的小凹痕（Heavy 字重"电"的钩尖
    # 实测复现过，不是靠调半径比例能根治的）。但像"国/回"外框那种两个拐角隔着
    # 一整条长边(几百单位)的情况完全没有这个风险，不能只按"是不是相邻拐角"一刀
    # 切——要看中间这截连接段本身短不短。
    anchor_pos = {a: k for k, a in enumerate(anchors)}
    safe = set()
    for i in corners:
        k = anchor_pos[i]
        h = anchors[(k - 1) % len(anchors)]
        j = anchors[(k + 1) % len(anchors)]
        risky = False
        if h in corners:
            _, shared_len = _unit(contour[h], contour[i])
            if shared_len < CORNER_SHORT_SHARED:
                risky = True
        if j in corners:
            _, shared_len = _unit(contour[i], contour[j])
            if shared_len < CORNER_SHORT_SHARED:
                risky = True
        if not risky:
            safe.add(i)
    return safe


def detect(glyph, glyf_table):
    """只做判断，不改坐标。返回 (cap_plan, tip_plan, corner_plan)：
    cap_plan[contour_idx] = {k 值集合}（k 是该轮廓 anchors 列表里的序号）
    tip_plan[contour_idx] = {anchor 原始点序号集合}
    corner_plan[contour_idx] = {anchor 原始点序号集合}
    """
    cap_plan, tip_plan, corner_plan = {}, {}, {}
    if glyph.isComposite() or glyph.numberOfContours <= 0:
        return cap_plan, tip_plan, corner_plan
    all_contours = list(_split_contours(glyph, glyf_table))
    all_polys = _glyph_polys(all_contours)
    for c, contour in enumerate(all_contours):
        n = len(contour)
        anchors = [i for i in range(n) if contour[i][2]]
        if n < 4 or len(anchors) < 3:
            continue
        straight = {}
        for k, i in enumerate(anchors):
            j = anchors[(k + 1) % len(anchors)]
            straight[(i, j)] = _is_straight_wrap(contour, i, j, n)
        # 尖锋
        tips = set()
        for k, i in enumerate(anchors):
            h = anchors[(k - 1) % len(anchors)]
            j = anchors[(k + 1) % len(anchors)]
            if not (straight.get((h, i)) and straight.get((i, j))):
                continue
            d_in, len_in = _unit(contour[h], contour[i])
            d_out, len_out = _unit(contour[i], contour[j])
            if len_in < TIP_R * 3 or len_out < TIP_R * 3:
                continue
            if d_in[0] * d_out[0] + d_in[1] * d_out[1] > TIP_DOT:
                continue
            tips.add(i)
        if tips:
            tip_plan[c] = tips
        # 端头(平头)
        caps = set()
        for k, i in enumerate(anchors):
            j = anchors[(k + 1) % len(anchors)]
            if not straight.get((i, j)):
                continue
            _, cap_len = _unit(contour[i], contour[j])
            if not (MIN_CAP <= cap_len <= MAX_CAP):
                continue
            prev_i = anchors[(k - 1) % len(anchors)]
            next_j = anchors[(k + 2) % len(anchors)]
            if not straight.get((prev_i, i)) or not straight.get((j, next_j)):
                continue
            d_in, prev_len = _unit(contour[i], contour[prev_i])
            d_out, next_len = _unit(contour[next_j], contour[j])
            if prev_len < NEIGHBOR * cap_len or next_len < NEIGHBOR * cap_len:
                continue
            d_cap = _unit(contour[i], contour[j])[0]
            d_in_fwd = (-d_in[0], -d_in[1])
            if abs(d_in_fwd[0] * d_cap[0] + d_in_fwd[1] * d_cap[1]) > COS_LIMIT:
                continue
            if abs(d_out[0] * d_cap[0] + d_out[1] * d_cap[1]) > COS_LIMIT:
                continue
            if (d_in[0] * d_out[0] + d_in[1] * d_out[1]) > PARALLEL:
                continue
            # 判断这段直边本身现在是不是已经被同一字形里另一条笔画盖住了（比如王字
            # 中间那一竖往上下各插进横画一截，保证叠压不露缝——这截的边原样摆在那里
            # 就已经被盖住，根本没暴露在背景里）。只探边缘外侧贴着的一小步，不是探
            # 削圆后鼓包鼓到多远——因为"削不削"取决于这段边此刻是不是真边界，不是
            # 削完之后鼓包够不够远；盖住了就跳过，不然鼓包会从盖住它的那条笔画里
            # 探出头，变成贴在笔画上的小圆点/小尾巴。
            eps = 1.5
            mid = ((contour[i][0] + contour[j][0]) / 2.0, (contour[i][1] + contour[j][1]) / 2.0)
            edge_probe = (mid[0] + d_in_fwd[0] * eps, mid[1] + d_in_fwd[1] * eps)
            if _point_covered(edge_probe[0], edge_probe[1], all_polys):
                continue
            caps.add(k)
        if caps:
            cap_plan[c] = caps
        cap_anchor_points = set()
        for k in caps:
            i = anchors[k]
            b = anchors[(k + 1) % len(anchors)]
            cap_anchor_points.add(i)
            cap_anchor_points.add(b)
        corners = detect_corners(contour, n, anchors, straight, cap_anchor_points, tips)
        if corners:
            corner_plan[c] = corners
    return cap_plan, tip_plan, corner_plan


def apply_all(glyph, glyf_table, tip_plan, cap_plan, corner_plan):
    """单趟组合应用：尖锋/端头/拐角三种变换在同一份原始锚点快照上一次性算完，
    不再分三次调用、不再在两次调用之间重新扫描锚点——避免前一遍改了点数后，
    后一遍按老的"第 k 个锚点"编号去套会对错位置（tip/cap 都会让锚点数变多）。
    """
    if glyph.isComposite() or glyph.numberOfContours <= 0:
        return 0
    if not (tip_plan or cap_plan or corner_plan):
        return 0
    made = 0
    new_all = []
    for c, contour in enumerate(_split_contours(glyph, glyf_table)):
        n = len(contour)
        tip_idx = tip_plan.get(c, set())
        cap_ks = cap_plan.get(c, set())
        corner_idx = corner_plan.get(c, set())
        if not (tip_idx or cap_ks or corner_idx):
            new_all.append(contour)
            continue
        anchors = [i for i in range(n) if contour[i][2]]
        if not anchors:
            new_all.append(contour)
            continue
        segs = []
        for k in range(len(anchors)):
            i = anchors[k]
            j = anchors[(k + 1) % len(anchors)]
            interior = (list(range(i + 1, j)) if i < j
                        else list(range(i + 1, n)) + list(range(0, j)))
            segs.append({"a": i, "interior": interior, "cap": k in cap_ks})
        out = []
        skip_anchor = False
        for k, seg in enumerate(segs):
            i = seg["a"]
            if seg["cap"]:
                b = (i + 1 + len(seg["interior"])) % n
                ax, ay = contour[i][0], contour[i][1]
                bx, by = contour[b][0], contour[b][1]
                _, cap_len = _unit(contour[i], contour[b])
                prev_i = anchors[(k - 1) % len(anchors)]
                d_in, prev_len = _unit(contour[i], contour[prev_i])
                d = (-d_in[0], -d_in[1])
                # 哪段是端头是按参照字重（Regular）的比例判出来的；粗字重同一截线段可能
                # 比参照字重短很多，固定按 cap_len*0.5 鼓出去可能比这截线段本身还长，把
                # 圆弧鼓到线段另一头外面去。这里按当前字重自己的相邻线段长度封顶半径。
                r = min(cap_len * 0.5, prev_len * 0.4)
                mx, my = (ax + bx) / 2, (ay + by) / 2
                apex = (mx + d[0] * r, my + d[1] * r)
                q1 = (ax + d[0] * r, ay + d[1] * r)
                q2 = (bx + d[0] * r, by + d[1] * r)
                if not skip_anchor:
                    out.append((ax, ay, True))
                out.append((q1[0], q1[1], False))
                out.append((apex[0], apex[1], True))
                out.append((q2[0], q2[1], False))
                out.append((bx, by, True))
                skip_anchor = True
                made += 1
                out.extend(contour[t] for t in seg["interior"])
                continue
            if i in tip_idx:
                h = anchors[(k - 1) % len(anchors)]
                j = anchors[(k + 1) % len(anchors)]
                d_in, len_in = _unit(contour[h], contour[i])
                d_out, len_out = _unit(contour[i], contour[j])
                # 哪些点是尖锋是按参照字重（Regular）的比例判出来的，但每个字重自己的
                # 坐标不一样——粗字重同一个钩子，相邻线段可能比参照字重短很多，固定的
                # TIP_R 偏移量会探出这段线段本身，削出来的弧线段自我交叉，变成一团乱线
                # （Heavy 的"电"钩尖实测复现过）。这里按当前字重自己的线段长度封顶半径，
                # 不再直接信一个跨字重通用的绝对值。
                r_tip = min(TIP_R, len_in * 0.3, len_out * 0.3)
                vx, vy = contour[i][0], contour[i][1]
                p1 = (vx + d_in[0] * r_tip, vy + d_in[1] * r_tip)
                p2 = (vx + d_out[0] * r_tip, vy + d_out[1] * r_tip)
                bis, _ = _unit(p1, p2)
                dist = r_tip * 0.9
                apex = ((p1[0] + p2[0]) / 2 + bis[0] * dist, (p1[1] + p2[1]) / 2 + bis[1] * dist)
                q1 = (vx + d_in[0] * r_tip * 0.2, vy + d_in[1] * r_tip * 0.2)
                q2 = (vx + d_out[0] * r_tip * 0.2, vy + d_out[1] * r_tip * 0.2)
                if not skip_anchor:
                    out.append(p1 + (True,))
                out.append(q1 + (False,))
                out.append(apex + (True,))
                out.append(q2 + (False,))
                made += 1
            elif i in corner_idx:
                h = anchors[(k - 1) % len(anchors)]
                j = anchors[(k + 1) % len(anchors)]
                d_in, len_in = _unit(contour[h], contour[i])
                d_out, len_out = _unit(contour[i], contour[j])
                # 钩笔常见：两个拐角紧挨着同一截短连接段（比如"电"的钩尖，两头各是一个
                # ~90°拐角），各按 0.42 吃一刀加起来快吃穿整段，两段圆弧在中间撞上/
                # 自交——实测在 Heavy 字重的"电"上复现过。这段两头都是拐角时，各自改用
                # 更保守的比例，总共最多吃掉这段一半，留足安全余量。
                ratio_in = CORNER_SHARED_RATIO if h in corner_idx else CORNER_R_RATIO
                ratio_out = CORNER_SHARED_RATIO if j in corner_idx else CORNER_R_RATIO
                r = min(len_in * ratio_in, len_out * ratio_out, CORNER_R_MAX)
                vx, vy = contour[i][0], contour[i][1]
                p1 = (vx - d_in[0] * r, vy - d_in[1] * r)
                p2 = (vx + d_out[0] * r, vy + d_out[1] * r)
                if not skip_anchor:
                    out.append(p1 + (True,))
                out.append((vx, vy, False))
                out.append(p2 + (True,))
                made += 1
            else:
                if not skip_anchor:
                    out.append(contour[i])
            skip_anchor = False
            out.extend(contour[t] for t in seg["interior"])
        new_all.append(out)
    _write_back(glyph, glyf_table, new_all, made)
    return made


def _write_back(glyph, glyf_table, new_points_all, made):
    if not made:
        return
    flat, ends_out = [], []
    for contour in new_points_all:
        for x, y, on in contour:
            flat.append((x, y, on))
        ends_out.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x, y, on in flat])
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = ends_out
    glyph.recalcBounds(glyf_table)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="参照字重 TTF（用来做结构判断）")
    parser.add_argument("instances", nargs="+", help="NAME=PATH.ttf，所有要同步圆角的字重实例")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--corners", action="store_true",
                         help="仿筑紫逢角必圆：L 形直角拐角（如国/回/田的外框角）也圆，默认关闭")
    args = parser.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    ref_font = TTFont(args.ref)
    ref_glyf = ref_font["glyf"]
    cap_plans, tip_plans, corner_plans = {}, {}, {}
    for name in ref_font.getGlyphOrder():
        g = ref_glyf[name]
        cap_plan, tip_plan, corner_plan = detect(g, ref_glyf)
        if cap_plan:
            cap_plans[name] = cap_plan
        if tip_plan:
            tip_plans[name] = tip_plan
        if corner_plan:
            corner_plans[name] = corner_plan
    print(f"参照字重检测出 {len(cap_plans)} 个字形有端头、{len(tip_plans)} 个字形有尖锋、"
          f"{len(corner_plans)} 个字形有直角拐角" + ("（本次已套用）" if args.corners else "（本次未套用，加 --corners 打开）"))

    for spec in args.instances:
        name, path = spec.split("=", 1)
        font = TTFont(path)
        glyf = font["glyf"]
        total = rounded = 0
        for gname in font.getGlyphOrder():
            g = glyf[gname]
            made = apply_all(g, glyf, tip_plans.get(gname, {}), cap_plans.get(gname, {}),
                              corner_plans.get(gname, {}) if args.corners else {})
            if made:
                rounded += 1
                total += made
        out_path = os.path.join(args.outdir, f"Selffont-Round-{name}.ttf")
        R.rename_family(font, "Selffont Round SC")
        font.save(out_path)
        print(f"{name}: rounded {total} caps in {rounded} glyphs -> {out_path}")


if __name__ == "__main__":
    main()
