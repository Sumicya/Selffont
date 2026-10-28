"""实验：检测并切掉"钩"（竖弯钩/竖钩/斜钩等末端的小钩尖），只留转折（横/弯）本身。

签名：轮廓上有两个"闸门"点，彼此空间距离很近（钩根部，笔画粗细量级），但沿轮廓走
中间隔着一长串点——这串点往外探出一截（钩尖伸出的距离），探出的距离明显比闸门间距
大很多。这正是"钩"的几何特征：出去一截、再绕回来，不是正常轮廓该有的走法。

找到之后：删掉两个闸门之间的所有点，直接用一段圆弧（跟 round_tips 的端头处理同一套
手法）把两个闸门连起来，形成一个干净的圆头收尾——钩没了，笔画在转折后就平整结束。

2026-10-15 续（重大教训，务必不要再犯）：`find_hooks()` 的判据全部是绝对单位数值
（`gate_max=90`、`max_path=700`、`min_path=150`、`min_excursion_abs=50`）——这些阈值
只对"某一个字重自己的绝对坐标尺度"合理，可变字体里同一个字在不同字重下笔画粗细、
钩子绝对尺寸完全不同（重字重的钩比细字重的钩在绝对坐标上大得多），同一组阈值在不同
字重上可能判出不同结论：实测"乙/围/九"等 11 个带钩字，Light/Regular/Heavy 三档
独立跑 `find_hooks()`，"切不切""切多宽"的结论互相对不上——这是可变字体的致命伤：
所有字重必须共享完全相同的点拓扑才能插值，点数一对不上，`vf_round.py` 的跨字重安全
校验 `plan_safety()` 当场 `KeyError` 崩溃（本仓库另两个工具 `foot_trim.py` 的
`find_cap_skip_points()`、`vf_round.py` 的 `detect()`/`plan_safety()` 都已经是"只在
参照字重上判一次结构，所有字重套用同一个结构决定"这个模式，`hook_cut.py` 当初没跟上，
是这次新发现的遗留缺口）。

改法：拆成"检测"（`find_hooks()`，只在参照字重上跑一次，决定切哪个轮廓的哪两个闸门
点序号）和"应用"（`apply_hook_cuts()`，把参照字重定下来的"切哪对点序号"原样套到每个
字重自己的坐标上去算真正的圆头收尾坐标）两步，`detect_hook_plan()`/`apply_hook_plan_to_font()`
是新的多字重入口；`__main__` 的 CLI 也跟着改成跟 `vf_round.py` 一样的
`--ref REF.ttf NAME=PATH.ttf [NAME=PATH.ttf ...]` 形状，保证所有字重用同一份决定，
点数、点序不会在字重之间对不上。
"""
import math
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates


def split_contours(coords, ends, flags):
    contours = []
    start = 0
    for end in ends:
        pts = [(float(coords[k][0]), float(coords[k][1]), bool(flags[k])) for k in range(start, end + 1)]
        contours.append(pts)
        start = end + 1
    return contours


def path_len(contour, i, j, n):
    """沿轮廓方向从 i 走到 j（跨过中间的 off-curve 点，用折线长度近似）的路径长度。"""
    total = 0.0
    k = i
    rng = list(range(i, j)) if i < j else list(range(i, n)) + list(range(0, j))
    for k in rng:
        x1, y1 = contour[k][0], contour[k][1]
        x2, y2 = contour[(k + 1) % n][0], contour[(k + 1) % n][1]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def max_excursion(contour, i, j, n, gate_a, gate_b):
    """i..j 这段路径里，离"闸门连线"最远的点有多远（近似"钩尖探出多远"）。"""
    ax, ay = gate_a
    bx, by = gate_b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-6:
        length = 1e-6
    rng = list(range(i, j)) if i < j else list(range(i, n)) + list(range(0, j))
    best = 0.0
    for k in rng:
        px, py = contour[k][0], contour[k][1]
        cross = abs(dx * (py - ay) - dy * (px - ax)) / length
        best = max(best, cross)
    return best


def _approach_direction(contour, i, n, lookback_min_len=40):
    """从 i 往回走，找最近一段"走向基本不变"的直线方向——不是只看紧挨着 i 的那一个
    点（那一个点可能已经在转弯/出钩的曲线上了），而是找一段有一定长度、方向稳定的
    直线，近似这一段笔画"主体"原本的走向。用来判断某个候选闸门是不是一刀切在
    "垂直于笔画主体"的位置（正常收笔该有的样子），还是切在歪斜的位置（闸门连线
    几乎跟笔画主体平行，切出来的结果会又短又斜，"了"字钩尖实测复现过）。
    """
    h = (i - 1) % n
    dx, dy = contour[i][0] - contour[h][0], contour[i][1] - contour[h][1]
    length = math.hypot(dx, dy)
    steps = 0
    while length < lookback_min_len and steps < 6:
        h2 = (h - 1) % n
        dx2, dy2 = contour[h][0] - contour[h2][0], contour[h][1] - contour[h2][1]
        dx, dy = dx + dx2, dy + dy2
        h = h2
        length = math.hypot(dx, dy)
        steps += 1
    if length < 1e-6:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def find_hooks(contours, gate_max=90, max_path=700, min_path=150, min_excursion_abs=50,
                min_excursion_ratio=1.15):
    """返回 [(contour_idx, gate_i, gate_j)]：gate_i/gate_j 是"闸门"锚点序号(on-curve)，
    之间的所有点都要被替换成圆头收尾。

    光"闸门距离近"不够——沿一条等宽笔画走，对面边缘上随便一点跟这边距离都约等于笔画
    粗细（76 单位量级），到处都满足"闸门近"，不是钩的专属特征。真正区分钩的是：钩
    出去又绕回来的这段路径本身很短（局部的一个小环，不是绕回笔画另一头那种长路径），
    且探出闸门连线的距离相对闸门间距明显偏大。这里加一个路径长度上限，并且在多个
    候选之间按"探出比例最大"取最像钩的那个，而不是"路径最长"的那个（之前那版正好
    选反了，挑到绕一整圈笔画另一侧的假阳性）。

    2026-10-19（"了"字真钩被假阳性顶掉，补一道 excursion/gate_dist 比例门槛）：
    `le_slant.py` 续十一给"了"顶部横转竖做的单样条连续曲线，在 contour0 收尾处留下
    一个衔接鼓包（闸门 i=23/j=2，gate_dist=79、excursion=79，探出比例恰好 1.00——
    本质上就是个普通的端头鼓包，不是钩），这个鼓包的 `perp_score` 恰好算出 0.000（闸门
    连线跟笔画走向严格垂直），比真正钩尾候选（i=7/j=17，探出比例 1.99，`perp_score`
    0.027）还要小一点点，在"同一轮廓只留 perp_score 最小的那个"这条选择规则下以微弱
    优势胜出，把假的当成了真钩去处理——"了"字真正的钩尾因此从未被这个工具碰过，之前
    看到的"扁平"收尾其实是 `le_slant.py` 产出的原始曲线，没有走过这里的裁切流程，不是
    裁切本身把它切扁的。真钩必然是"探出去一截、明显超过闸门本身的宽度"，普通鼓包的探出
    距离只跟闸门宽度同量级（比例≈1.0）——加一道比例门槛（取 1.15，真钩实测比例落在
    1.31~2.32 之间，假阳性是 1.00，中间留了足够间隔）能干净分开这两类，不影响其余已经
    验证过的 8 个带钩字形的既有选择结果（抽查过也/包/子三字的全部候选，门槛前后选中的
    闸门对完全一致）。
    """
    hooks = []
    for ci, c in enumerate(contours):
        n = len(c)
        anchors = [i for i in range(n) if c[i][2]]
        if len(anchors) < 6:
            continue
        for a_idx, i in enumerate(anchors):
            for span in (2, 3, 4, 5, 6):
                j = anchors[(a_idx + span) % len(anchors)]
                if i == j:
                    continue
                gate_dist = math.hypot(c[i][0] - c[j][0], c[i][1] - c[j][1])
                if gate_dist > gate_max:
                    continue
                plen = path_len(c, i, j, n)
                if not (min_path <= plen <= max_path):
                    continue
                excursion = max_excursion(c, i, j, n, (c[i][0], c[i][1]), (c[j][0], c[j][1]))
                if excursion < min_excursion_abs:
                    continue
                if excursion < gate_dist * min_excursion_ratio:
                    continue  # 探出比例太小，是普通端头鼓包不是钩，见上面 2026-10-19 说明
                # 闸门连线是否垂直于笔画主体走向——这是"切在哪"的主要判据，不是"探出
                # 比例"。切点选在跟笔画主体近乎平行的位置，削出来的收尾又短又斜
                # （"了"字实测复现：选中部分明明探出比例更高，但闸门连线几乎跟竖笔
                # 平行，切完只剩一小截歪的残端）；选在垂直于主体的位置，才是正常收笔
                # 该有的"干净切面"。
                adx, ady = _approach_direction(c, i, n)
                gdx, gdy = c[j][0] - c[i][0], c[j][1] - c[i][1]
                glen = math.hypot(gdx, gdy) or 1.0
                perp_score = abs(adx * (gdx / glen) + ady * (gdy / glen))  # 越接近 0 越垂直
                hooks.append((ci, i, j, gate_dist, plen, excursion, perp_score))
    # 2026-10-15 四续："围"字实测复现过这样一个假阳性：同一对闸门点 (10,22)，沿轮廓
    # 顺着走有两个方向——从 10 到 22 只经过中间 12 个点（267 单位，真正的钩环，里面
    # 包着钩尖）；反过来从 22 绕回 10 要经过另外 14 个点、几乎是轮廓的另外一大半
    # （491 单位，根本不是"钩"，是笔画主体本身）。这个反方向的候选恰好因为"从 22
    # 往回走"落在钩环自己的曲线上，量出来的 perp_score 反而更小，被误选——切完等于
    # 把钩尖完整保留、却削掉了笔画主体的一截，渲染出来是个飘在外面的碎块。
    # 真正的钩环在几何上必然是"短"的那一边（钩是探出去又绕回来的一小截，不可能是
    # 轮廓的大半），所以同一对闸门点只保留路径更短的那个方向，再在剩下的候选里按
    # perp_score 选——不能让"哪个方向 perp_score 更小"凌驾于"哪个方向才是真的钩环"
    # 之上。
    by_gate_pair = {}
    for h in hooks:
        ci, i, j, gate_dist, plen, excursion, perp_score = h
        key = (ci, frozenset((i, j)))
        if key not in by_gate_pair or plen < by_gate_pair[key][4]:
            by_gate_pair[key] = h
    # 同一轮廓可能被多个（不同闸门点对的）候选命中，优先选"闸门连线垂直于笔画主体
    # 走向"的那个（最像正常收笔该有的切面），perp_score 越小越好；不是探出比例最大的那个。
    best_by_contour = {}
    for ci, i, j, gate_dist, plen, excursion, perp_score in by_gate_pair.values():
        key = ci
        if key not in best_by_contour or perp_score < best_by_contour[key][-1]:
            best_by_contour[key] = (ci, i, j, plen, gate_dist, excursion, perp_score)
    return [(ci, i, j, plen, gate_dist, excursion) for ci, i, j, plen, gate_dist, excursion, _ in best_by_contour.values()]


def cut_hook(contour, n, i, j, cap_bulge=0.5):
    """用一段圆头（跟端头削圆同一手法：两个闸门中点往外鼓一点）替换 i..j 之间的点。"""
    ax, ay = contour[i][0], contour[i][1]
    bx, by = contour[j][0], contour[j][1]
    # 鼓出方向：取"闸门连线"的法线，朝背离轮廓内部的一侧（用 i 前一点近似轮廓走向）
    prev = contour[(i - 1) % n]
    din = (ax - prev[0], ay - prev[1])
    dlen = math.hypot(*din) or 1.0
    din = (din[0] / dlen, din[1] / dlen)
    gate_dx, gate_dy = bx - ax, by - ay
    glen = math.hypot(gate_dx, gate_dy) or 1.0
    gate_u = (gate_dx / glen, gate_dy / glen)
    normal = (-gate_u[1], gate_u[0])
    # 法线取跟"进入方向"更顺的那一侧（往外鼓而不是往里凹）
    if din[0] * normal[0] + din[1] * normal[1] < 0:
        normal = (-normal[0], -normal[1])
    mx, my = (ax + bx) / 2, (ay + by) / 2
    r = glen * cap_bulge
    apex = (mx + normal[0] * r, my + normal[1] * r)
    q1 = (ax + normal[0] * r * 0.55, ay + normal[1] * r * 0.55)
    q2 = (bx + normal[0] * r * 0.55, by + normal[1] * r * 0.55)
    return [(ax, ay, True), (q1[0], q1[1], False), (apex[0], apex[1], True),
            (q2[0], q2[1], False), (bx, by, True)]


def apply_hook_cuts(glyph, glyf_table, hooks):
    if not hooks:
        return 0
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    contours = split_contours(coords, ends, flags)
    by_contour = {h[0]: h for h in hooks}
    new_all = []
    made = 0
    for ci, c in enumerate(contours):
        if ci not in by_contour:
            new_all.append(c)
            continue
        _, i, j, *_ = by_contour[ci]
        n = len(c)
        replacement = cut_hook(c, n, i, j)
        rng_after = list(range(j, n)) if j <= n else []
        out = [c[i]]
        out.extend(replacement[1:])
        k = j
        while k != i:
            out.append(c[k])
            k = (k + 1) % n
        new_all.append(out)
        made += 1
    flat, new_ends = [], []
    for c in new_all:
        flat.extend(c)
        new_ends.append(len(flat) - 1)
    glyph.coordinates = GlyphCoordinates([(int(round(x)), int(round(y))) for x, y, on in flat])
    glyph.flags = [bool(on) for _, _, on in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf_table)
    return made


def detect_hook_plan(ref_glyf, glyph_order):
    """只在参照字重上跑一次 find_hooks()，产出 {字形名: [(contour_idx, gate_i, gate_j), ...]}。

    这份"决定"只含点序号、不含任何字重相关的绝对坐标数值——其他字重要用的时候，
    各自拿自己在这几个点序号上的坐标去重新算圆头收尾的具体位置（`cut_hook()` 本来
    就是这么写的，直接传别的字重自己的 contour 进去也一样能用），但"切不切、切哪个
    轮廓的哪两个点"这件结构性决定，全体字重统一套用参照字重的结果，不再各自独立判断。
    """
    plan = {}
    for gname in glyph_order:
        g = ref_glyf[gname]
        coords, ends, flags = g.getCoordinates(ref_glyf)
        contours = split_contours(coords, ends, flags)
        hooks = find_hooks(contours)
        if hooks:
            plan[gname] = [(h[0], h[1], h[2]) for h in hooks]
    return plan


def apply_hook_plan_to_font(font, plan):
    """把 detect_hook_plan() 算出来的结构决定套到这一个字重自己的字体上：对计划里提到
    的每个字形，仍然用这个字重自己的坐标重新算圆头收尾（`apply_hook_cuts` 内部本来就是
    读 `glyph.getCoordinates()` 现算的），但切哪个轮廓的哪两个点序号完全照抄参照字重的
    决定，不再调用 `find_hooks()` 重新判断——这样不管这个字重自己的钩子绝对尺寸多大/多小，
    切出来的点数、点序都跟其他字重完全一致，可变字体各主控之间的拓扑才对得上。
    """
    glyf = font["glyf"]
    report = {}
    for gname, hooks in plan.items():
        if gname not in glyf.glyphs and gname not in font.getGlyphOrder():
            continue
        g = glyf[gname]
        made = apply_hook_cuts(g, glyf, hooks)
        if made:
            report[gname] = made
    return report


def main():
    import argparse
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="参照字重 TTF（用来做结构判断：切哪个轮廓的哪两个点）")
    parser.add_argument("instances", nargs="+", help="NAME=PATH.ttf，所有要同步切钩的字重实例")
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    ref_font = TTFont(args.ref)
    ref_glyf = ref_font["glyf"]
    plan = detect_hook_plan(ref_glyf, ref_font.getGlyphOrder())
    n_hooks = sum(len(v) for v in plan.values())
    print(f"参照字重检测出 {len(plan)} 个字形、共 {n_hooks} 处钩（本结构决定将原样套用到全部字重）")

    for spec in args.instances:
        name, path = spec.split("=", 1)
        font = TTFont(path)
        report = apply_hook_plan_to_font(font, plan)
        out_path = os.path.join(args.outdir, f"{name}.ttf")
        font.save(out_path)
        total = sum(report.values())
        print(f"{name}: cut {total} hook(s) in {len(report)} glyph(s) -> {out_path}")


if __name__ == "__main__":
    import sys
    # 兼容旧的一次性单字重调试用法：hook_cut.py IN.ttf OUT.ttf 字符串
    # （只看某几个字、不走多字重一致性流程，仅供手工排查用，正式流水线请用
    # --ref/--outdir 的多字重入口，见 main()）。
    if len(sys.argv) >= 4 and not sys.argv[1].startswith("--"):
        f = TTFont(sys.argv[1])
        glyf = f["glyf"]
        cmap = f.getBestCmap()
        for ch in sys.argv[3]:
            if ord(ch) not in cmap:
                continue
            gname = cmap[ord(ch)]
            g = glyf[gname]
            coords, ends, flags = g.getCoordinates(glyf)
            contours = split_contours(coords, ends, flags)
            hooks = find_hooks(contours)
            if hooks:
                made = apply_hook_cuts(g, glyf, hooks)
                print(f"{ch} ({gname}): cut {made} hook(s): {[(h[0],h[1],h[2]) for h in hooks]}")
            else:
                print(f"{ch} ({gname}): no hook found")
        f.save(sys.argv[2])
    else:
        main()
