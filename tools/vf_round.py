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
import copy
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
CORNER_SHARED_RATIO = 0.32            # 两个拐角紧挨着同一截短连接段时，各自改用这个更保守
                                       # 的比例（两头加起来约 0.64，留三分之一左右不碰，避免互相自交）。
                                       # 2026-10-15 四续：原来定的 0.16 本身在数学上过度保守——两个拐角
                                       # 各用同一个比例 R 吃同一截长度 L 的边，只要 R<0.5 就保证
                                       # 2*R*L < L，两段弧不会碰头，这个安全边界本来就跟 L 的具体长度
                                       # 无关，不需要再额外留三分之二的安全垫。原 0.16 的问题是在"电"这
                                       # 类独立细墙轮廓（contour3，墙宽本身只有 70~150 单位量级）上实测
                                       # 暴露出来的：细墙四个角全部互为"紧邻同一截短边"的拐角，按 0.16
                                       # 算出来的半径只有个位数到十几个单位，在正常字号下跟完全没削圆
                                       # 几乎看不出区别（用户实测反馈"电左未圆角"）。改到 0.32 后两段弧
                                       # 之间仍留约三分之一的边长不碰，留了足够余量，同时半径视觉上翻倍，
                                       # 11 个口字框字 + 电 在三档字重下逐字复核过，没有出现新的自交/鼓包。
CORNER_SHORT_SHARED = 200              # 两个拐角之间的连接段短于这个值(1000upm)才算"短段"，
                                        # 两头都不圆；国/回外框那种长边不受影响


CORNER_COLLINEAR_TOL = 2.5  # 单位(1000upm)。detect_corners 专用的更严格共线判断：
                            # straight[(i,j)] 原本的定义只看"i、j 之间有没有 on-curve
                            # 点"，但这个条件对"中间插了好几个 off-curve 点、靠数量凑
                            # 跨字重点数一致"的边够用——它没有检查这些 off-curve 点是否
                            # 真的落在 i-j 的直线上。拐角削圆的公式假设两边都是真直线，
                            # 如果其中一边其实是一段很浅的曲线（比如"戈"钩笔中部那种几
                            # 个单位的轻微弯折，实测偏离直线约 4 个单位），按直线套用这
                            # 套公式会裁错位置，在 Heavy 字重复现过自相交（"成"字戈钩
                            # 实测复现）。这里额外核一遍所有中间点到弦的垂直距离，超过
                            # 容差就不当拐角候选处理——跟本仓库"不确定就不碰"一致。


def _collinear_enough(contour, i, j, n, tol=CORNER_COLLINEAR_TOL):
    """i→j 之间的所有点（含 off-curve）是否都落在弦 i-j 的直线附近（容差 tol）。"""
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return True
    rng = range(i + 1, j) if i < j else (list(range(i + 1, n)) + list(range(0, j)))
    for k in rng:
        px, py = contour[k][0], contour[k][1]
        cross = dx * (py - ay) - dy * (px - ax)
        if abs(cross) / length > tol:
            return False
    return True


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


def detect_corners(contour, n, anchors, straight, cap_anchor_set, tip_set, all_polys=None,
                    force_corners=None):
    """找"该不该仿筑紫逢角必圆"的直角拐角——凸角和凹角都找，不是只找凸角。

    上一版只认"转向跟轮廓绕行方向相同"的凸角（国/回/田外框的四个角），把转向相反的
    一律当成"T 形接口留下的凹切口"跳过不碰。这个判断是错的：凹角（两条笔画相交内侧
    形成的直角，比如"口"字内框四角、横竖相交的内侧角）跟 T 形接口在"转向跟整条轮廓
    绕行方向相反"这一个几何特征上完全没法区分，上一版把两者混为一谈，导致凡是凹角
    一律不处理——但凹角在筑紫这类丸ゴシック里跟凸角一样会削成小圆角（往里填一点点
    让缺口变圆，不是往外切），是"逢角必圆"里真实存在、肉眼能看到的那一半，不是可以
    跳过的边缘情况。

    凸角：削圆是把尖角往内收一点（圆弧控制点取原顶点，端点在两边各退 r），削掉一点
    突出的材料。凹角：同一套公式原样套用，几何效果反过来——圆弧端点落在两边上，控制
    点仍是原顶点，但顶点此刻正对着"缺口"（背景），弧线比直接连两个端点的弦更靠近顶点，
    相当于往缺口里填一点点材料，把直角缺口变成一个小圆角缺口——这正是内角该有的效果，
    公式不用改，只需要不再按转向把它们滤掉。

    凹角比凸角多一层真实风险：往缺口里"填"材料，如果这个缺口本身很窄（对面就是另一条
    笔画，比如"回"字外框跟内框之间的间距、或者两条笔画交叉留下的窄缝），半径稍大就会
    把缺口糊住，啃到不该碰的地方。这里用环绕数在削圆圆弧的大致探入深度处探一下背景：
    如果探测点已经被（这个字形里任何轮廓的）材料盖住，说明这个"缺口"比半径窄，这一个
    角不安全，跳过不碰，跟本仓库"不确定就不碰"的一贯原则一致；凸角没有这层风险（削圆
    只会让材料变少，不会主动去够旁边的东西），不需要这层探测。

    半径按该字重自己的边长重算，这里只记录"要不要圆"这个结构决定，跟 cap/tip
    共用同一套"检测一次、各字重复用"的模型。

    force_corners: 可选，{原始点序号}——外部（detect()，配合 foot_trim.py 的
    skip_caps）已经判定"这个点结构上是个直角，但不该走端头圆化"的点，强制当成
    拐角处理，跳过下面"两个拐角紧挨着同一截短连接段"的保守否决（那条否决是给
    "钩笔钩尖两头各一个拐角、中间几十单位"这种真有撞刀风险的场景写的；电/国/田
    这类被削平贴靠在背景上的细墙，两头拐角之间那截"短"边本来就是墙的厚度本身，
    半径按 CORNER_SHARED_RATIO 收紧后两边远够不着碰头，没有同样的风险，但如果
    不强制纳入，会被这条保守阈值一并否决，端头从"鼓包"变成完全没有圆角的直角——
    跟全字形"逢角必圆"的观感不一致）。仍然要过前面角度/共线等基本检查，只跳过
    "risky"这一步否决。

    2026-10-17：新增第三种处理——两个拐角紧挨同一截短连接段、且转向(turn_sign)一致
    （同一个方向连续转弯，比如钩笔"从竖笔转到钩尖"这种一笔到底的弯，不是两个方向
    相反的 Z 字形折角）时，不再回退成两个都不圆的尖角，改成**合并成一条连续圆弧**：
    起止点分别退到两个拐角各自"外侧"的长边上（半径按外侧长边本身的长度算，不再
    像两个独立拐角那样被中间这截短边限制），中间两个顶点变成一串连续的 off-curve
    控制点（不额外插 on-curve 落地锚点）——这是"了"字续十一手工做出来的"一笔到底"
    结构在通用拐角算法里的推广，详见下面 `_merge_drop()`/`_merge_self_crosses()` 和
    `plan_safety()`/`apply_all()` 里 `merge_plan` 相关代码，以及 `TODO.md` 2026-10-17
    条目。转向不一致（真正的 Z 字形）不合并，保留原来的"两个都不圆"保守行为，
    跟本仓库"不确定就不碰"一致。

    返回 (safe, merge_pairs)：safe 跟以前一样是{anchor 原始点序号}；merge_pairs 是
    {(i, j)} 一对相邻拐角原始点序号的集合，i 是对里先出现的那个（按 anchors 顺序）。
    """
    force_corners = force_corners or set()
    if len(anchors) < 4:
        return set(), set()
    winding = _contour_winding(contour, anchors)
    corners = set()
    turn_sign_of = {}
    for k, i in enumerate(anchors):
        if i in cap_anchor_set or i in tip_set:
            continue
        h = anchors[(k - 1) % len(anchors)]
        j = anchors[(k + 1) % len(anchors)]
        if not (straight.get((h, i)) and straight.get((i, j))):
            continue
        if not (_collinear_enough(contour, h, i, n) and _collinear_enough(contour, i, j, n)):
            continue  # straight[] 只看"中间没有 on-curve 点"，没查真共线，这里补一道
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
        is_concave = turn_sign != winding
        if is_concave:
            # 凹角：往缺口里填材料有风险，削圆前探一下缺口够不够宽，不够宽就不碰。
            r_probe = min(len_in, len_out) * CORNER_R_RATIO
            r_probe = min(r_probe, CORNER_R_MAX)
            vx, vy = contour[i][0], contour[i][1]
            p1 = (vx - d_in[0] * r_probe, vy - d_in[1] * r_probe)
            p2 = (vx + d_out[0] * r_probe, vy + d_out[1] * r_probe)
            apex = (0.25 * p1[0] + 0.5 * vx + 0.25 * p2[0],
                    0.25 * p1[1] + 0.5 * vy + 0.25 * p2[1])
            if all_polys is not None and _point_covered(apex[0], apex[1], all_polys):
                continue  # 缺口比半径窄，探测点已经撞进材料里，不碰这个凹角
        # 半径按 min(len_in, len_out)*CORNER_R_RATIO（<0.5）取，天然不会吃穿任何一边，
        # 这里不需要再叠一层"边长须是半径几倍"的门槛（之前写的那层在两边长度接近时
        # 数学上永远不可能满足，等于把所有正常方角都滤掉了）。
        corners.add(i)
        turn_sign_of[i] = turn_sign
    if not corners:
        return corners, set()
    # 两个拐角紧挨着同一截"短"连接段（比如钩笔的钩尖，两头各是一个 ~90°拐角、
    # 中间就隔几十到一百多单位）：各自削一刀圆出来的两段弧在中间碰头，哪怕各自
    # 半径都收得很小也会在接缝处留一个方向不连续的小凹痕（Heavy 字重"电"的钩尖
    # 实测复现过，不是靠调半径比例能根治的）。但像"国/回"外框那种两个拐角隔着
    # 一整条长边(几百单位)的情况完全没有这个风险，不能只按"是不是相邻拐角"一刀
    # 切——要看中间这截连接段本身短不短。
    anchor_pos = {a: k for k, a in enumerate(anchors)}
    safe = set()
    risky_set = set()
    for i in corners:
        if i in force_corners:
            safe.add(i)  # 外部已判定安全（贴靠背景的细墙两端），不走下面的保守否决
            continue
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
        else:
            risky_set.add(i)
    # 合并候选：risky_set 里相邻（anchors 顺序上紧挨着）、转向一致、且不是 force_corners
    # 的一对，合并成一条连续弧。额外要求两端的"外侧"锚点（pair 之前/之后那个点）
    # 不是任何一种拐角/端头/尖锋——这个 Phase 1 版本先只处理"孤立的一对拐角"这种
    # 最简单、跟"了"字钩尾结构最接近的情况，不处理三个及以上拐角连续串在一起的链，
    # 范围扩大留给验证通过之后的后续工作（TODO.md 2026-10-17）。
    merge_pairs = set()
    for i in risky_set:
        k = anchor_pos[i]
        j = anchors[(k + 1) % len(anchors)]
        if j not in risky_set or j in force_corners:
            continue
        # 2026-10-17 补充（真实回归，"暖"字实测复现）：anchors 只收 on-curve 点，straight[]/
        # _collinear_enough() 判断的是"i、j 之间有没有 on-curve 点"及"是否共线在容差内"——
        # 对单独一个拐角的两条邻边够用（容差是给"浅弧看成直线也没关系"的半径计算松的口子），
        # 但合并要求 i-j 之间是一段真正什么都没有的直线短边（像"了"钩尾那样两个 on-curve
        # 点直接相邻），不能是"中间隔着 off-curve 控制点、只是凑巧没超共线容差"的浅弧——
        # 后者本身已经是设计好的圆润笔锋/小尖(比如"暖"字里的点/撇末端)，把它当直线短边
        # 处理、拆掉原有 off-curve 点换成合并圆弧，会跟原弧线的真实弯曲方向对不上，在
        # Heavy 字重复现过自交。这里直接按原始点序号（不只是 anchors 里的 on-curve 序号）
        # 要求 i、j 中间一个点都没有（含 off-curve），才当"货真价实的短直线共享边"处理。
        if (j - i) % n != 1:
            continue
        _, shared_len = _unit(contour[i], contour[j])
        if shared_len >= CORNER_SHORT_SHARED:
            continue
        if turn_sign_of.get(i) != turn_sign_of.get(j):
            continue  # 转向不一致（Z 字形），合并会产生新的扭曲，保持尖角不碰
        k_j = anchor_pos[j]
        outer_prev = anchors[(k - 1) % len(anchors)]
        outer_next = anchors[(k_j + 1) % len(anchors)]
        if outer_prev == j or outer_next == i:
            continue  # 锚点太少，首尾绕回自己，几何退化
        if (outer_prev in corners or outer_next in corners
                or outer_prev in cap_anchor_set or outer_next in cap_anchor_set
                or outer_prev in tip_set or outer_next in tip_set):
            continue  # 外侧紧挨着另一个拐角/端头/尖锋，属于三连及以上的链，这版不处理
        merge_pairs.add((i, j))
    return safe, merge_pairs


def detect(glyph, glyf_table, skip_caps=None):
    """只做结构判断，不涉及"切多大才安全"——那部分跟每个字重自己的绝对坐标
    尺度有关（同一个比例，Heavy 的绝对半径比 Regular 大很多），不能只用参照
    字重的坐标去判，必须在所有字重上都验证过才安全（见 plan_safety()）。
    这里只回答"这个点结构上算不算尖锋/端头/拐角"，返回 (cap_plan, tip_plan,
    corner_plan, merge_plan)：
    cap_plan[contour_idx] = {k 值集合}（k 是该轮廓 anchors 列表里的序号）
    tip_plan[contour_idx] = {anchor 原始点序号集合}
    corner_plan[contour_idx] = {anchor 原始点序号集合}
    merge_plan[contour_idx] = {(i, j) 原始点序号二元组集合}——一对该合并成一条连续
    弧的相邻拐角（见 detect_corners 末尾新增的合并候选逻辑），i、j 都不出现在同一
    contour 的 corner_plan 里（互斥，各走各的应用路径）。

    skip_caps: 可选，{contour_idx: {原始点序号集合}}——外部（比如 foot_trim.py）
    已经确认"这个端头其实贴着/本该贴着同字形里另一条笔画，不是真正暴露在背景里
    的自由端头"的点，强制排除在 caps 之外，不管下面这套结构判断本身认不认同。
    这是给"贴平"那类修复用的收尾步骤——贴平只改坐标，不会让这里的"是否已被盖住"
    探测自动认出来（贴平/本来就贴平的笔画，如果它本身比被贴的那条笔画更往外凸出
    一截，探测点会落在凸出来的那段缝隙里，判定"没被盖住"，照样独立鼓一个包）。
    """
    cap_plan, tip_plan, corner_plan, merge_plan = {}, {}, {}, {}
    skip_caps = skip_caps or {}
    if glyph.isComposite() or glyph.numberOfContours <= 0:
        return cap_plan, tip_plan, corner_plan, merge_plan
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
            if i in skip_caps.get(c, ()) or j in skip_caps.get(c, ()):
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
        force_corners = skip_caps.get(c, set()) - cap_anchor_points
        corners, merge_pairs = detect_corners(contour, n, anchors, straight, cap_anchor_points, tips,
                                               all_polys, force_corners=force_corners)
        if corners:
            corner_plan[c] = corners
        if merge_pairs:
            merge_plan[c] = merge_pairs
    return cap_plan, tip_plan, corner_plan, merge_plan


def _flatten_quad(p0, c, p1, steps=8):
    pts = []
    for k in range(steps + 1):
        t = k / steps
        mt = 1 - t
        pts.append((mt * mt * p0[0] + 2 * mt * t * c[0] + t * t * p1[0],
                    mt * mt * p0[1] + 2 * mt * t * c[1] + t * t * p1[1]))
    return pts


def _seg_cross(p1, p2, p3, p4):
    """两条直线段 p1-p2、p3-p4 是不是真的交叉（不含端点重合/共线贴边这种
    擦边情况，只认"穿过去了"）。"""
    def _cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _tip_self_crosses(p1, q1, apex, q2, nxt, prev=None):
    """尖锋削完之后会生成两段首尾相接于 apex 的弧（p1-q1-apex 和
    apex-q2-nxt）。当 q2 把曲线往回拉的时候，第二段会贴着共享点 apex 附近
    就立刻绕回去再切第一段一刀——折返点离 apex 可能很近，不能简单掐掉两头
    贴着 apex 的那一小段再比（会把真正出问题的地方一起扔掉），这里按细分
    的每一段逐一比对，只跳过"A 最后一段 vs B 第一段"这一对——它们本来就
    共享 apex 这一个端点，不算交叉；其余所有组合（哪怕紧挨着 apex）都要
    比。"""
    A = _flatten_quad(p1, q1, apex, steps=24)
    B = _flatten_quad(apex, q2, nxt, steps=24)
    nA, nB = len(A) - 1, len(B) - 1
    for i in range(nA):
        for j in range(nB):
            if i == nA - 1 and j == 0:
                continue  # 共享 apex 这一个端点，跳过
            if _seg_cross(A[i], A[i + 1], B[j], B[j + 1]):
                return True
    if prev is not None:
        # 第三种折返：q1 把 A 拉弯以后，A 自己可能在快到 p1 的地方就绕回去，
        # 切穿了"从上一个锚点直线走进 p1"这一段原本笔直的来路——这段来路
        # 跟 A 共享 p1 这一个端点，要跳过"来路最后一段 vs A 第一段"这一对，
        # 其余逐段比对（u25D43 实测复现过：交叉点几乎正好落在来路的延长线
        # 上，离 p1 很近，不能只看 A 跟 B 两段自己）。
        for k in range(nA):
            if k == 0:
                continue  # 共享 p1 这一个端点，跳过
            if _seg_cross(prev, p1, A[k], A[k + 1]):
                return True
    return False


def _compute_drop_set(contour, n, anchors, corner_idx, tip_idx):
    """算出"被削进拐角/尖锋范围内、该整体丢弃的共线中间点"，返回一个按原始
    点序号记的集合。只在参照字重上调用一次（detect() 里），所有字重原样
    套用这个集合——不能让每个字重按自己的坐标距离各自决定丢几个点，不然
    字重之间点数会对不上，没法再喂给 varLib.build 插值（实测 uni31E1 等
    5618+ 个字形复现过这个问题）。"""
    if not (corner_idx or tip_idx):
        return set()
    anchor_pos = {a: k for k, a in enumerate(anchors)}

    def _corner_radius(i):
        k = anchor_pos[i]
        h = anchors[(k - 1) % len(anchors)]
        j = anchors[(k + 1) % len(anchors)]
        d_in, len_in = _unit(contour[h], contour[i])
        d_out, len_out = _unit(contour[i], contour[j])
        ratio_in = CORNER_SHARED_RATIO if h in corner_idx else CORNER_R_RATIO
        ratio_out = CORNER_SHARED_RATIO if j in corner_idx else CORNER_R_RATIO
        return min(len_in * ratio_in, len_out * ratio_out, CORNER_R_MAX)

    def _tip_radius(i):
        k = anchor_pos[i]
        h = anchors[(k - 1) % len(anchors)]
        j = anchors[(k + 1) % len(anchors)]
        _, len_in = _unit(contour[h], contour[i])
        _, len_out = _unit(contour[i], contour[j])
        return min(TIP_R, len_in * 0.3, len_out * 0.3) * tip_idx[i]

    corner_r = {i: _corner_radius(i) for i in corner_idx}
    vertex_r = dict(corner_r)
    for i in tip_idx:
        vertex_r[i] = _tip_radius(i)

    drop = set()
    for k in range(len(anchors)):
        i = anchors[k]
        j = anchors[(k + 1) % len(anchors)]
        interior = (list(range(i + 1, j)) if i < j
                    else list(range(i + 1, n)) + list(range(0, j)))
        if i in vertex_r and interior:
            r_i = vertex_r[i]
            vx, vy = contour[i][0], contour[i][1]
            while interior and _unit((vx, vy), contour[interior[0]])[1] < r_i:
                drop.add(interior.pop(0))
        if j in vertex_r and interior:
            r_j = vertex_r[j]
            vx, vy = contour[j][0], contour[j][1]
            while interior and _unit((vx, vy), contour[interior[-1]])[1] < r_j:
                drop.add(interior.pop())
    return drop


def _merge_pair_geometry(contour, anchors, anchor_pos, h, i):
    """合并对 (h, i) 的几何基础量：外侧前驱 outer_prev（h 之前那个锚点）、外侧
    后继 outer_next（i 之后那个锚点）、进入方向 d_in（outer_prev→h）、离开方向
    d_out（i→outer_next）、对应的外侧边长 len_in/len_out。半径只用这两条外侧边，
    不用 h-i 之间的短连接段本身——这是合并方案跟旧版"两个独立拐角各退一步"的
    核心区别：短连接段不再是限制半径的瓶颈，而是被整条合并曲线直接吃掉（跟
    "了"字续十一手工做法同一个原理：外侧的真实笔画边界决定弯多大，不是中间
    那一小截衔接段）。"""
    k_h = anchor_pos[h]
    k_i = anchor_pos[i]
    outer_prev = anchors[(k_h - 1) % len(anchors)]
    outer_next = anchors[(k_i + 1) % len(anchors)]
    d_in, len_in = _unit(contour[outer_prev], contour[h])
    d_out, len_out = _unit(contour[i], contour[outer_next])
    return outer_prev, outer_next, d_in, len_in, d_out, len_out


def _merge_radii(contour, anchors, anchor_pos, h, i, shrink=1.0):
    _, _, d_in, len_in, d_out, len_out = _merge_pair_geometry(contour, anchors, anchor_pos, h, i)
    r1 = min(len_in * CORNER_R_RATIO, CORNER_R_MAX) * shrink
    r2 = min(len_out * CORNER_R_RATIO, CORNER_R_MAX) * shrink
    return r1, r2


def _merge_drop(contour, n, anchors, anchor_pos, h, i, r1, r2):
    """合并对 (h, i) 吃掉的共线中间点：outer_prev→h 边上贴着 h 的一截（r1 以内，
    对应 P1 的退让）、h→i 整截（短连接段，无条件全丢——这一截不再是独立的边，
    已经被合并曲线整体替换）、i→outer_next 边上贴着 i 的一截（r2 以内，对应 P2
    的进占）。跟 `_compute_drop_set` 单个顶点两侧各退一次的逻辑同构，只是换成
    两个顶点各退/进一次、中间再整体清空一次。"""
    drop = set()
    k_h = anchor_pos[h]
    outer_prev = anchors[(k_h - 1) % len(anchors)]
    interior_before = (list(range(outer_prev + 1, h)) if outer_prev < h
                        else list(range(outer_prev + 1, n)) + list(range(0, h)))
    vx, vy = contour[h][0], contour[h][1]
    while interior_before and _unit((vx, vy), contour[interior_before[-1]])[1] < r1:
        drop.add(interior_before.pop())

    interior_mid = (list(range(h + 1, i)) if h < i
                     else list(range(h + 1, n)) + list(range(0, i)))
    drop.update(interior_mid)

    k_i = anchor_pos[i]
    outer_next = anchors[(k_i + 1) % len(anchors)]
    interior_after = (list(range(i + 1, outer_next)) if i < outer_next
                       else list(range(i + 1, n)) + list(range(0, outer_next)))
    vx2, vy2 = contour[i][0], contour[i][1]
    while interior_after and _unit((vx2, vy2), contour[interior_after[0]])[1] < r2:
        drop.add(interior_after.pop(0))
    return drop


def _merge_self_crosses(prev_pt, p1, off_a, off_b, p2, nxt_pt):
    """合并曲线自交检测：p1→off_a→M→off_b→p2（M 是 off_a/off_b 的隐式中点，
    TrueType 二次样条的基本性质——参见 `tools/le_slant.py` 续十一的同款证明）
    拆成两段抛物线分别 flatten 后逐段比对，跟 `_tip_self_crosses` 同一个套路：
    共享端点那一对跳过，其余全比；并且要跟前面来路（prev_pt→p1）和后面去路
    （p2→nxt_pt）分别比一次，防止合并后的弧线把原来笔直的来路/去路线段切穿。"""
    mid = ((off_a[0] + off_b[0]) / 2.0, (off_a[1] + off_b[1]) / 2.0)
    A = _flatten_quad(p1, off_a, mid, steps=16)
    B = _flatten_quad(mid, off_b, p2, steps=16)
    nA, nB = len(A) - 1, len(B) - 1
    for a in range(nA):
        for b in range(nB):
            if a == nA - 1 and b == 0:
                continue  # 共享 mid 这一个隐式端点
            if _seg_cross(A[a], A[a + 1], B[b], B[b + 1]):
                return True
    for a in range(nA):
        if a == 0:
            continue  # 共享 p1 这一个端点
        if _seg_cross(prev_pt, p1, A[a], A[a + 1]):
            return True
    for b in range(nB):
        if _seg_cross(prev_pt, p1, B[b], B[b + 1]):
            return True
    for a in range(nA):
        if _seg_cross(p2, nxt_pt, A[a], A[a + 1]):
            return True
    for b in range(nB):
        if b == nB - 1:
            continue  # 共享 p2 这一个端点
        if _seg_cross(p2, nxt_pt, B[b], B[b + 1]):
            return True
    return False


def _flatten_contour_tagged(contour, n, anchors):
    """把整条轮廓按 anchors 展平成 (p_a, p_b, 来源锚点序号) 线段列表——来源锚点
    序号是这一小段曲线起点那个 on-curve 点的原始序号，用来在合并全局自交检查
    里把"即将被合并曲线整体替换掉"的那一段从背景线段里摘出去（这一段马上就
    不存在了，不该再拿它当背景比）。"""
    segs = []
    for k in range(len(anchors)):
        a = anchors[k]
        b = anchors[(k + 1) % len(anchors)]
        chain_idx = (list(range(a + 1, b)) if a < b
                     else list(range(a + 1, n)) + list(range(0, b)))
        pts = [contour[a]] + [contour[t] for t in chain_idx] + [contour[b]]
        cur = pts[0]
        i = 1
        while i < len(pts):
            p = pts[i]
            if p[2]:
                segs.append(((cur[0], cur[1]), (p[0], p[1]), a))
                cur = p
                i += 1
            else:
                nxt = pts[i + 1] if i + 1 < len(pts) else pts[0]
                if nxt[2]:
                    end = (nxt[0], nxt[1])
                    consumed = 2
                else:
                    end = ((p[0] + nxt[0]) / 2.0, (p[1] + nxt[1]) / 2.0)
                    consumed = 1
                flat = _flatten_quad((cur[0], cur[1]), (p[0], p[1]), end, steps=12)
                for z in range(len(flat) - 1):
                    segs.append((flat[z], flat[z + 1], a))
                cur = (end[0], end[1], True)
                i += consumed
    return segs


def _merge_vs_background(bg_segs, exclude_tags, p1, off_a, off_b, p2):
    """检查一对合并候选削出来的弧线（p1→offA→隐式中点→offB→p2）是不是撞上了
    同一轮廓里跟这对合并毫不相关的其它部分——`_merge_self_crosses` 只跟弧线
    自己的直接前后邻边比，比不出"弧线鼓出去以后绕回来撞上轮廓里老远一块
    （比如带内圈的假名字形，鼓包正好扫过自己的内圈）"这种全局交叉（随机抽样
    全字形扫描在平假名"る"等字上复现过）。bg_segs 是 `_flatten_contour_tagged`
    的输出，exclude_tags 是这次要排除的来源锚点序号集合（这对合并自己的短
    连接段——它马上会被这条弧线整体替换，不再是背景的一部分）。"""
    mid = ((off_a[0] + off_b[0]) / 2.0, (off_a[1] + off_b[1]) / 2.0)
    A = _flatten_quad(p1, off_a, mid, steps=16)
    B = _flatten_quad(mid, off_b, p2, steps=16)
    arc = A + B[1:]
    for k in range(len(arc) - 1):
        a0, a1 = arc[k], arc[k + 1]
        for s0, s1, tag in bg_segs:
            if tag in exclude_tags:
                continue
            if _seg_cross(a0, a1, s0, s1):
                return True
    return False


def plan_safety(glyphs_by_weight, glyf_tables_by_weight, tip_plan, corner_plan, merge_plan=None):
    """detect() 判完"结构上哪些点算尖锋/拐角"之后，"切多大才不会自己切出
    自交"必须在每个字重自己的绝对坐标上分别验证——同一个比例，粗字重笔画
    绝对尺寸大，削出来的半径/控制点间距也大，参照字重（通常是 Regular）
    觉得安全的半径，套到 Heavy 上可能已经自交了（反过来，共线中间点该丢
    几个也是同理：参照字重算出来的半径够不着的点，粗字重可能已经够得着，
    不丢就会在粗字重上自交——uni31E1/glyph01063 等实测都复现过）。

    这里对每个字重各自算一遍"尖锋缩水到多少才安全""该丢哪些共线点"，尖锋
    缩水比例取所有字重里最保守（最小）的一个，共线点丢弃集合取所有字重的
    并集（多丢几个冗余共线点不影响形状，只会更安全）——这样保证这一份决定
    套到任何一个字重都安全，而且所有字重用的是同一份决定，削完点数/点序
    不会对不上，能继续喂给 varLib.build 插值。

    合并对（merge_plan）的安全验证跟尖锋同一个思路：每个字重各自算一遍"合并
    半径缩到多少、两端退让/进占的坐标会不会让合并曲线自交"，取所有字重里最
    保守（最小）的缩水比例；缩到最小还自交就整体放弃这一对合并（既不进
    merge_shrink_plan，也不留在 corner_plan 里——退回最初的"两个都不圆"，
    维持"不确定就不碰"的最终后果）。

    返回 (tip_shrink_plan, drop_plan, merge_shrink_plan)，前两者按 contour_idx
    分组、结构跟 tip_plan/corner_plan 一致；merge_shrink_plan[c] = {(h, i): 缩水
    比例}，只包含验证通过的合并对。
    """
    merge_plan = merge_plan or {}
    tip_shrink_plan, drop_plan, merge_shrink_plan = {}, {}, {}
    contour_lists = {}
    for wname, g in glyphs_by_weight.items():
        glyf_table = glyf_tables_by_weight[wname]
        if g.isComposite() or g.numberOfContours is None or g.numberOfContours <= 0:
            return tip_shrink_plan, drop_plan, merge_shrink_plan
        contour_lists[wname] = list(_split_contours(g, glyf_table))
    contours_count = {len(v) for v in contour_lists.values()}
    if len(contours_count) != 1:
        return tip_shrink_plan, drop_plan, merge_shrink_plan  # 字重之间轮廓数对不上，不碰，交给上层原样跳过
    n_contours = contours_count.pop()
    for c in range(n_contours):
        tip_idx = tip_plan.get(c, set())
        corner_idx = corner_plan.get(c, set())
        merge_pairs = merge_plan.get(c, set())
        if not (tip_idx or corner_idx or merge_pairs):
            continue
        contours = [contour_lists[w][c] for w in contour_lists]
        n = len(contours[0])
        anchors = [i for i in range(n) if contours[0][i][2]]
        anchor_pos = {a: k for k, a in enumerate(anchors)}

        shrink_per_vertex = {}
        for i in tip_idx:
            k = anchors.index(i)
            h = anchors[(k - 1) % len(anchors)]
            j = anchors[(k + 1) % len(anchors)]
            worst_shrink = 1.0
            for contour in contours:
                d_in, len_in = _unit(contour[h], contour[i])
                d_out, len_out = _unit(contour[i], contour[j])
                r_tip = min(TIP_R, len_in * 0.3, len_out * 0.3)
                vx, vy = contour[i][0], contour[i][1]
                probe = (list(range(i + 1, j)) if i < j
                         else list(range(i + 1, n)) + list(range(0, j)))
                while probe and _unit((vx, vy), contour[probe[0]])[1] < r_tip:
                    probe.pop(0)
                shrink = 1.0
                ok = False
                for _ in range(6):
                    rr = r_tip * shrink
                    p1 = (vx + d_in[0] * rr, vy + d_in[1] * rr)
                    p2 = (vx + d_out[0] * rr, vy + d_out[1] * rr)
                    bis, _ = _unit(p1, p2)
                    dist = rr * 0.9
                    apex = ((p1[0] + p2[0]) / 2 + bis[0] * dist, (p1[1] + p2[1]) / 2 + bis[1] * dist)
                    q1 = (vx + d_in[0] * rr * 0.2, vy + d_in[1] * rr * 0.2)
                    q2 = (vx + d_out[0] * rr * 0.2, vy + d_out[1] * rr * 0.2)
                    # q2 后面紧跟的那条曲线真正在哪里收尾：probe[0]（如果还剩）
                    # 永远是 off-curve 控制点，不是曲线端点——q2 自己也是
                    # off-curve，q2 跟 probe[0] 连续两个 off-curve 之间要插一个
                    # 虚拟 on-curve 中点（TrueType 二次曲线规则），这才是 q2
                    # 这条曲线真正的终点；probe 空的话端点就是下一个锚点 j。
                    # q2 随 shrink 变化，这个中点也要跟着每次重算，不能在循环
                    # 外算一次就固定（用错端点会让校验的曲线比实际画出来的长/
                    # 短，可能漏判出一个真会自交的尖锋，u25D43 实测复现过）。
                    if probe:
                        pb = contour[probe[0]]
                        nxt = ((q2[0] + pb[0]) / 2, (q2[1] + pb[1]) / 2)
                    else:
                        nxt = (contour[j][0], contour[j][1])
                    # 字形最终落盘时坐标会取整（_write_back 里 round 成 int）——
                    # 用浮点精度判"会不会自交"可能刚好把真正造成折返的那一点点
                    # 取整误差漏掉（uni4D84 实测复现过：浮点算出来不自交，取整
                    # 以后反而自交），这里按最终真正会写进字体的取整坐标来判。
                    rp1, rq1, rapex, rq2, rnxt = (
                        (round(p1[0]), round(p1[1])), (round(q1[0]), round(q1[1])),
                        (round(apex[0]), round(apex[1])), (round(q2[0]), round(q2[1])),
                        (round(nxt[0]), round(nxt[1])))
                    rprev = (round(contour[h][0]), round(contour[h][1]))
                    if not _tip_self_crosses(rp1, rq1, rapex, rq2, rnxt, prev=rprev):
                        ok = True
                        break
                    shrink *= 0.5
                worst_shrink = min(worst_shrink, shrink if ok else 0.0)
            if worst_shrink > 0:
                shrink_per_vertex[i] = worst_shrink
            # 所有字重缩到最小都还会自交，放弃削这个尖锋——不收进
            # shrink_per_vertex，apply_all 会把它当成普通锚点原样保留。

        shrink_per_merge = {}
        # 这个轮廓里全部合并候选共享的"背景排除标签"——每一对的短连接段用起点
        # 锚点序号(h)当标签（见 _flatten_contour_tagged），这些段马上会被各自
        # 的合并曲线整体替换，背景检查时统一摘掉，不管当前正在验证哪一对。
        merge_h_tags = {h for h, _ in merge_pairs}
        for h, i in merge_pairs:
            worst_shrink = 1.0
            for contour in contours:
                outer_prev, outer_next, d_in, len_in, d_out, len_out = _merge_pair_geometry(
                    contour, anchors, anchor_pos, h, i)
                hx, hy = contour[h][0], contour[h][1]
                ix, iy = contour[i][0], contour[i][1]
                bg_segs = _flatten_contour_tagged(contour, n, anchors)
                shrink = 1.0
                ok = False
                for _ in range(6):
                    r1 = min(len_in * CORNER_R_RATIO, CORNER_R_MAX) * shrink
                    r2 = min(len_out * CORNER_R_RATIO, CORNER_R_MAX) * shrink
                    p1 = (hx - d_in[0] * r1, hy - d_in[1] * r1)
                    p2 = (ix + d_out[0] * r2, iy + d_out[1] * r2)
                    off_a, off_b = (hx, hy), (ix, iy)
                    rp1, roffa, roffb, rp2 = (
                        (round(p1[0]), round(p1[1])), (round(off_a[0]), round(off_a[1])),
                        (round(off_b[0]), round(off_b[1])), (round(p2[0]), round(p2[1])))
                    rprev = (round(contour[outer_prev][0]), round(contour[outer_prev][1]))
                    rnext = (round(contour[outer_next][0]), round(contour[outer_next][1]))
                    crosses = _merge_self_crosses(rprev, rp1, roffa, roffb, rp2, rnext)
                    if not crosses:
                        # 局部邻边不交叉，还要跟同一轮廓里跟这对合并无关的其它
                        # 部分比一遍——弧线鼓出去以后可能绕回去撞上轮廓里老远
                        # 一块（比如带内圈的假名字形扫到自己的内圈），局部检查
                        # 看不出这种全局交叉（随机抽样全字形扫描在"る"等字上
                        # 复现过），必须额外比这一遍才算真正安全。
                        crosses = _merge_vs_background(bg_segs, merge_h_tags, rp1, roffa, roffb, rp2)
                    # shortcut: bg_segs 用的是这个轮廓没削之前的原始几何，不包含同一
                    # 轮廓里其它 tip/corner 各自削完以后的真实新形状——如果合并弧线
                    # 恰好跟旁边一个独立拐角削出来的小圆弧在极窄空间里碰头，这一步
                    # 测不出来（已知极罕见个例：uni4910，全字形随机抽样 1230 个候选里
                    # 1 个）。要补全须把 tip/corner/merge 一起套用 apply_all 出真实
                    # 形状再核，这里先不做；真出问题时自交检测仍会在最终产物里可见，
                    # 不会悄悄产出错误但测不出的字形。
                    if not crosses:
                        ok = True
                        break
                    shrink *= 0.5
                worst_shrink = min(worst_shrink, shrink if ok else 0.0)
            if worst_shrink > 0:
                shrink_per_merge[(h, i)] = worst_shrink
            # 所有字重缩到最小都还会自交（局部或全局任意一种），放弃合并这一对——不收进 shrink_per_merge，
            # 也不回退去走独立拐角路径（那条路径是给 force_corners 场景准备的，不是
            # 给"合并失败"兜底的），apply_all 会把 h、i 都当成普通锚点原样保留（尖角）。

        drops = set()
        for contour in contours:
            drops |= _compute_drop_set(contour, n, anchors, corner_idx, shrink_per_vertex)
            for (h, i), shrink in shrink_per_merge.items():
                r1, r2 = _merge_radii(contour, anchors, anchor_pos, h, i, shrink)
                drops |= _merge_drop(contour, n, anchors, anchor_pos, h, i, r1, r2)
        if shrink_per_vertex:
            tip_shrink_plan[c] = shrink_per_vertex
        if drops:
            drop_plan[c] = drops
        if shrink_per_merge:
            merge_shrink_plan[c] = shrink_per_merge
    return tip_shrink_plan, drop_plan, merge_shrink_plan


def apply_all(glyph, glyf_table, tip_plan, cap_plan, corner_plan, drop_plan, merge_plan=None):
    """单趟组合应用：尖锋/端头/拐角/合并对四种变换在同一份原始锚点快照上一次性
    算完，不再分开调用、不再在两次调用之间重新扫描锚点——避免前一遍改了点数后，
    后一遍按老的"第 k 个锚点"编号去套会对错位置（tip/cap/merge 都会让锚点数变多）。

    merge_plan[contour_idx] = {(h, i): 缩水比例}——plan_safety() 验证通过的合并对，
    h、i 都不会出现在同一 contour 的 corner_plan/tip_plan/cap_plan 里（互斥）。
    """
    merge_plan = merge_plan or {}
    if glyph.isComposite() or glyph.numberOfContours <= 0:
        return 0
    if not (tip_plan or cap_plan or corner_plan or merge_plan):
        return 0
    made = 0
    new_all = []
    for c, contour in enumerate(_split_contours(glyph, glyf_table)):
        n = len(contour)
        tip_idx = tip_plan.get(c, {})
        cap_ks = cap_plan.get(c, set())
        corner_idx = corner_plan.get(c, set())
        merge_pairs = merge_plan.get(c, {})
        if not (tip_idx or cap_ks or corner_idx or merge_pairs):
            new_all.append(contour)
            continue
        anchors = [i for i in range(n) if contour[i][2]]
        if not anchors:
            new_all.append(contour)
            continue
        anchor_pos = {a: k for k, a in enumerate(anchors)}
        merge_start = {h: (i, shrink) for (h, i), shrink in merge_pairs.items()}
        drops = drop_plan.get(c, set())
        # 每个顶点自己用当前字重坐标重算方向向量/半径（下面 tip/corner 分支里
        # 做），但"该不该把某个共线中间点整体丢掉"这件事不能按当前字重的坐标
        # 距离现场判——不同字重同一处的绝对间距不一样，会导致有的字重判定
        # "在范围内该丢"、另一些字重判定"不在范围内不丢"，削完两个字重点数
        # 对不上，没法再喂给 varLib.build 插值（实测 uni31E1 等 5618+ 个字形
        # 复现过）。drops 是 detect() 在参照字重上一次性判好、所有字重原样
        # 套用的丢弃点集合。
        segs = []
        for k in range(len(anchors)):
            i = anchors[k]
            j = anchors[(k + 1) % len(anchors)]
            interior = (list(range(i + 1, j)) if i < j
                        else list(range(i + 1, n)) + list(range(0, j)))
            if drops:
                interior = [t for t in interior if t not in drops]
            segs.append({"a": i, "interior": interior, "cap": k in cap_ks})
        # 2026-10-17 补充（真实回归，随机抽样全字形扫描复现）：下面这个循环靠"skip_anchor
        # 在相邻两次迭代之间原样传下去"识别合并对的第二个拐角（i2）该不该重复落点——这个
        # 假设要求 h 在 segs 里排在 i2 前面一格。绝大多数合并对确实如此（detect_corners()
        # 按 anchors 顺序找"紧挨着的下一个"），但当 h 恰好是整个轮廓锚点序列的最后一个、
        # i2 是第一个时（合并对跨越了 segs 列表首尾这个人为分界，不是轮廓本身的分界——
        # 轮廓是闭合的，首尾分界只是这个列表恰好从哪个点开始数），i2 在列表里排在 h**前面**
        # （k=0 vs k=len-1），会在 h 还没被处理、skip_anchor 还是初始值 False 时就被当成
        # 普通锚点先落一次点，h 处理到时又把 i2 的坐标当 off-curve 控制点再落一次——同一个
        # 点坐标写了两遍，多出来的点把合并弧线撕开一个口子，造成自交（随机抽样实测在
        # uni3080 等复现）。轮廓闭合、从哪个锚点开始数都是等价的同一个圈，这里整体转一格，
        # 把 i2 挪到 h 后面，跟其余（不跨首尾分界的）合并对处理方式保持一致，不改变轮廓
        # 本身代表的形状。
        if segs and segs[-1]["a"] in merge_start and merge_start[segs[-1]["a"]][0] == segs[0]["a"]:
            segs = segs[1:] + segs[:1]
        out = []
        skip_anchor = False
        for k, seg in enumerate(segs):
            i = seg["a"]
            if i in merge_start:
                # 合并对：h=i（本次循环的锚点）、i2=配对的第二个拐角，必然是 anchors
                # 里紧挨着的下一个（detect_corners 里按这个前提收的合并候选）。整条
                # h→i2 之间的短连接段被一条连续曲线替换：P1（退让进 outer_prev→h 边）
                # →offA=h→offB=i2（两个连续 off-curve，中间隐式中点，天然切线连续）
                # →P2（进占 i2→outer_next 边）。跟单个拐角的处理手法一致，只是把"顶点
                # 本身"从一个换成两个连续的 off-curve 控制点，不再依赖中间那截短边
                # 本身的长度来限制半径。
                i2, shrink = merge_start[i]
                r1, r2 = _merge_radii(contour, anchors, anchor_pos, i, i2, shrink)
                outer_prev, outer_next, d_in, _, d_out, _ = _merge_pair_geometry(
                    contour, anchors, anchor_pos, i, i2)
                hx, hy = contour[i][0], contour[i][1]
                ix, iy = contour[i2][0], contour[i2][1]
                p1 = (hx - d_in[0] * r1, hy - d_in[1] * r1)
                p2 = (ix + d_out[0] * r2, iy + d_out[1] * r2)
                if not skip_anchor:
                    out.append(p1 + (True,))
                out.append((hx, hy, False))
                out.append((ix, iy, False))
                out.append(p2 + (True,))
                skip_anchor = True
                made += 1
                # 注意：这里不重置 skip_anchor——下一次循环处理的是配对的第二个
                # 拐角 i2，它自己的锚点坐标已经作为 offB 原样写进上面的曲线里，
                # 不能再被 else 分支重复 append 一次（否则会在 offB 和 P2 之间多
                # 出一个落在旧直线位置的点，破坏刚合并出来的连续曲线）。seg["interior"]
                # （h→i2 之间的共线点）按 _merge_drop() 的约定应当已经被整体丢弃，
                # 这里仍然原样 extend 一次，保证即使丢弃不完整也不会静默漏点。
                out.extend(contour[t] for t in seg["interior"])
                continue
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
                # 注意：这里不再把 seg["interior"] 原样接到弧线后面。这段 interior
                # 是"削平头"之前那条直线 i→b 自己的共线冗余点（跨字重点数对齐用，
                # 不是真弯）——平头弧把 i→b 整段都换成了一条新的鼓包弧线，这些老
                # 直线上的点现在完全对不上弧线的新形状，原样接上去会在弧线末尾
                # 后面再折回旧直线位置，形成自相交（"乱"等含共线端头的字实测
                # 复现过）。丢掉它们，端头前后两段分别正常相连，形状不受影响。
                continue
            if i in tip_idx:
                h = anchors[(k - 1) % len(anchors)]
                j = anchors[(k + 1) % len(anchors)]
                d_in, len_in = _unit(contour[h], contour[i])
                d_out, len_out = _unit(contour[i], contour[j])
                # 哪些点是尖锋、以及"切多大会自交所以要缩多少"，都是在参照字重上
                # 一次性判好的（detect() 里算的 shrink 比例，tip_idx[i]）——这里
                # 不能让每个字重各自临场再判一遍要不要缩/缩多少，否则字重之间切
                # 出来的点数可能对不上，没法再喂给 varLib.build 插值。每个字重
                # 只用自己的坐标重新算方向向量/半径，缩水比例原样套用参照字重的
                # 决定。
                r_tip = min(TIP_R, len_in * 0.3, len_out * 0.3) * tip_idx[i]
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
                # 注意：这里不补 p2——p2 只是用来算 apex 朝哪个方向鼓出去的
                # 几何辅助点，不是真正要落在轮廓上的点（试过把它接到 q2 后面，
                # apex 跟 p2 几乎是贴在一起的两个点，中间硬插一段往回绕的弧，
                # 反而在尖锋自己身上多切一刀自交，实测在非 GB2312 范围内新增
                # 了 178 个自交字形，回滚）。q2 之后直接跟上面过滤剩下的
                # interior/下一个锚点正常相连即可。
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
                         help="仿筑紫逢角必圆：凸角（国/回/田外框角）和凹角（内框角、横竖相交内侧角）都圆，默认关闭")
    parser.add_argument("--skip-caps-json", default=None,
                         help="可选，foot_trim.py 产出的排除名单：{字形名: [[contour_idx, point_idx], ...]}，"
                              "列在里面的端头不当自由端头圆化（贴平后仍会独立鼓包的收尾修复）")
    args = parser.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    skip_caps_by_glyph = {}
    if args.skip_caps_json:
        import json
        with open(args.skip_caps_json) as fp:
            raw = json.load(fp)
        for gname, pairs in raw.items():
            d = {}
            for ci, pi in pairs:
                d.setdefault(ci, set()).add(pi)
            skip_caps_by_glyph[gname] = d

    ref_font = TTFont(args.ref)
    ref_glyf = ref_font["glyf"]
    cap_plans, tip_plans, corner_plans, merge_plans = {}, {}, {}, {}
    for name in ref_font.getGlyphOrder():
        g = ref_glyf[name]
        cap_plan, tip_plan, corner_plan, merge_plan = detect(g, ref_glyf, skip_caps_by_glyph.get(name))
        if cap_plan:
            cap_plans[name] = cap_plan
        if tip_plan:
            tip_plans[name] = tip_plan
        if corner_plan:
            corner_plans[name] = corner_plan
        if merge_plan:
            merge_plans[name] = merge_plan
    n_merge_pairs = sum(len(pairs) for plan in merge_plans.values() for pairs in plan.values())
    print(f"参照字重检测出 {len(cap_plans)} 个字形有端头、{len(tip_plans)} 个字形有尖锋、"
          f"{len(corner_plans)} 个字形有直角拐角、{len(merge_plans)} 个字形有 {n_merge_pairs} 对"
          f"可合并的紧邻拐角（钩笔一笔到底）"
          + ("（本次已套用）" if args.corners else "（本次未套用，加 --corners 打开）"))

    # "切多大才安全"跟每个字重自己的绝对坐标尺度有关，必须在全部要出的字重
    # 上都验证过才作数（见 plan_safety() 的注释）——这里先把所有实例字重都
    # 加载进内存，再按字形逐个算一份"所有字重共用、对所有字重都安全"的
    # 尖锋缩水比例/共线点丢弃集合，最后才真正落笔改坐标、分别存盘。
    fonts, glyfs = {}, {}
    for spec in args.instances:
        name, path = spec.split("=", 1)
        font = TTFont(path)
        fonts[name] = font
        glyfs[name] = font["glyf"]

    tip_shrink_plans, drop_plans, merge_shrink_plans = {}, {}, {}
    corner_plans_eff = corner_plans if args.corners else {}
    merge_plans_eff = merge_plans if args.corners else {}
    for gname in ref_font.getGlyphOrder():
        tip_idx_any = tip_plans.get(gname)
        corner_idx_any = corner_plans_eff.get(gname)
        merge_pairs_any = merge_plans_eff.get(gname)
        if not (tip_idx_any or corner_idx_any or merge_pairs_any):
            continue
        glyphs_by_weight = {w: glyfs[w][gname] for w in fonts}
        tip_shrink_plan, drop_plan, merge_shrink_plan = plan_safety(
            glyphs_by_weight, glyfs, tip_idx_any or {}, corner_idx_any or {}, merge_pairs_any or {})
        if tip_shrink_plan:
            tip_shrink_plans[gname] = tip_shrink_plan
        if drop_plan:
            drop_plans[gname] = drop_plan
        if merge_shrink_plan:
            merge_shrink_plans[gname] = merge_shrink_plan

    for name, font in fonts.items():
        glyf = glyfs[name]
        total = rounded = 0
        for gname in font.getGlyphOrder():
            g = glyf[gname]
            made = apply_all(g, glyf, tip_shrink_plans.get(gname, {}), cap_plans.get(gname, {}),
                              corner_plans_eff.get(gname, {}),
                              drop_plans.get(gname, {}),
                              merge_shrink_plans.get(gname, {}))
            if made:
                rounded += 1
                total += made
        out_path = os.path.join(args.outdir, f"Selfrounds-{name}.ttf")
        R.rename_family(font, "Selfrounds")
        font.save(out_path)
        print(f"{name}: rounded {total} caps in {rounded} glyphs -> {out_path}")


if __name__ == "__main__":
    main()
