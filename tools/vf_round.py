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


def detect(glyph, glyf_table):
    """只做判断，不改坐标。返回 (cap_plan, tip_plan)：
    cap_plan[contour_idx] = {k 值集合}（k 是该轮廓 anchors 列表里的序号）
    tip_plan[contour_idx] = {anchor 原始点序号集合}
    """
    cap_plan, tip_plan = {}, {}
    if glyph.isComposite() or glyph.numberOfContours <= 0:
        return cap_plan, tip_plan
    for c, contour in enumerate(_split_contours(glyph, glyf_table)):
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
            caps.add(k)
        if caps:
            cap_plan[c] = caps
    return cap_plan, tip_plan


def apply_tips(glyph, glyf_table, tip_plan):
    if not tip_plan or glyph.isComposite() or glyph.numberOfContours <= 0:
        return 0
    made = 0
    new_all = []
    for c, contour in enumerate(_split_contours(glyph, glyf_table)):
        n = len(contour)
        tip_idx = tip_plan.get(c, set())
        if not tip_idx:
            new_all.append(contour)
            continue
        anchors = [i for i in range(n) if contour[i][2]]
        anchor_pos = {i: k for k, i in enumerate(anchors)}
        out = []
        for k, i in enumerate(anchors):
            j = anchors[(k + 1) % len(anchors)]
            if i in tip_idx and i in anchor_pos:
                h = anchors[(k - 1) % len(anchors)]
                d_in, _ = _unit(contour[h], contour[i])
                d_out, _ = _unit(contour[i], contour[j])
                vx, vy = contour[i][0], contour[i][1]
                p1 = (vx + d_in[0] * TIP_R, vy + d_in[1] * TIP_R)
                p2 = (vx + d_out[0] * TIP_R, vy + d_out[1] * TIP_R)
                bis, _ = _unit(p1, p2)
                dist = TIP_R * 0.9
                apex = ((p1[0] + p2[0]) / 2 + bis[0] * dist, (p1[1] + p2[1]) / 2 + bis[1] * dist)
                q1 = (vx + d_in[0] * TIP_R * 0.2, vy + d_in[1] * TIP_R * 0.2)
                q2 = (vx + d_out[0] * TIP_R * 0.2, vy + d_out[1] * TIP_R * 0.2)
                out.append(p1 + (True,))
                out.append(q1 + (False,))
                out.append(apex + (True,))
                out.append(q2 + (False,))
                made += 1
            else:
                out.append(contour[i])
            out.extend(contour[t] for t in (list(range(i + 1, j)) if i < j
                                            else list(range(i + 1, n)) + list(range(0, j))))
        new_all.append(out)
    _write_back(glyph, glyf_table, new_all, made)
    return made


def apply_caps(glyph, glyf_table, cap_plan):
    if not cap_plan or glyph.isComposite() or glyph.numberOfContours <= 0:
        return 0
    made = 0
    new_all = []
    for c, contour in enumerate(_split_contours(glyph, glyf_table)):
        n = len(contour)
        cap_ks = cap_plan.get(c, set())
        if not cap_ks:
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
        for seg in segs:
            if seg["cap"]:
                i = seg["a"]
                b = (i + 1 + len(seg["interior"])) % n
                ax, ay = contour[i][0], contour[i][1]
                bx, by = contour[b][0], contour[b][1]
                d_cap, cap_len = _unit(contour[i], contour[b])
                # 用本字重自己的坐标重算方向：沿封口两端取相邻锚点，再取垂直于封口的"外向"。
                k_idx = anchors.index(i)
                prev_i = anchors[(k_idx - 1) % len(anchors)]
                d_in, _ = _unit(contour[i], contour[prev_i])
                d = (-d_in[0], -d_in[1])
                r = cap_len * 0.5
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
                continue
            if not skip_anchor:
                out.append(contour[seg["a"]])
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
    args = parser.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    ref_font = TTFont(args.ref)
    ref_glyf = ref_font["glyf"]
    cap_plans, tip_plans = {}, {}
    for name in ref_font.getGlyphOrder():
        g = ref_glyf[name]
        cap_plan, tip_plan = detect(g, ref_glyf)
        if cap_plan:
            cap_plans[name] = cap_plan
        if tip_plan:
            tip_plans[name] = tip_plan
    print(f"参照字重检测出 {len(cap_plans)} 个字形有端头、{len(tip_plans)} 个字形有尖锋")

    for spec in args.instances:
        name, path = spec.split("=", 1)
        font = TTFont(path)
        glyf = font["glyf"]
        total = rounded = 0
        for gname in font.getGlyphOrder():
            g = glyf[gname]
            made = apply_tips(g, glyf, tip_plans.get(gname, {})) \
                 + apply_caps(g, glyf, cap_plans.get(gname, {}))
            if made:
                rounded += 1
                total += made
        out_path = os.path.join(args.outdir, f"Selffont-Round-{name}.ttf")
        R.rename_family(font, "Selffont Round SC")
        font.save(out_path)
        print(f"{name}: rounded {total} caps in {rounded} glyphs -> {out_path}")


if __name__ == "__main__":
    main()
