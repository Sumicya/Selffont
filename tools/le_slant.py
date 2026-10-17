"""了的竖钩笔位置不和谐——竖笔从横折的转角处直上直下垂下来，跟上面那段横折（横+
捺状转折）衔接处是个生硬的死角，不像手写笔锋那样带一点自然的倾斜延续感。

2026-10-15 第一版方案：转斜（shear）——把竖笔整体剪切，锚点顶边不动。用户看过
效果后反馈：不做倾斜了，改成直接挪动竖笔的（横向）位置——于是改成整体平移
（translate），竖笔顶边跟着移走，同步挪动了横折转角曲线上跟它重合的那个衔接点，
缝合处不留缝。

2026-10-16 续：用户直接甩出了参照图（方正FW筑紫A丸，一款以"逢角必圆、转折连续"
著称的日系丸ゴシック字体）：筑紫的"了"整个顶部转折是一条连续弯曲的弧线，横笔到
竖笔之间没有任何直线段或直角，是一笔流畅画下来的；反观我们这版，不管是剪切还是
平移，骨架仍然是"一段水平直线+一个死角拐角+一段垂直直线"，无论怎么调参数，骨架
本身跟筑紫的流畅感没有关系——用户原话"我说照着筑紫做"，要求的是结构性改动，不是
参数微调。

分析我们字体"了"的轮廓拓扑：顶部横折转角是一条独立的弧线轮廓（contour2），它的
终点跟竖笔轮廓（contour0）的起点坐标完全重合（衔接点）；从衔接点开始，contour0
先走一小段**纯水平直线**（到竖笔右上角），再走一段**纯垂直直线**（往下，带出竖笔
主干）——这两段直线夹出的那个 90° 直角，就是视觉上"死角"的根源：衔接点本身只有
一个小小的方向突变（可以接受，筑紫自己的曲线上也有类似的转折点，只是用连续弧线
表达），但紧接着这个方向突变之后，马上又在很短的距离内（一小段水平直线的长度）
来一个 90° 急转，两个转折挤在一小段距离里，叠加起来才是"生硬""机械"的真正原因。

方案：把这一小段水平直线 + 90° 直角，换成**一条圆弧**（用的是 `vf_round.py` 本仓库
现成的"拐角削圆"公式：圆弧控制点取原拐角顶点，两端锚点各退/进 r），但半径刻意取
**整段水平边的全长**——不是像 vf_round.py 平时削边角那样只啃一小口，而是把整条
水平边都吃进弧线里，让原本"平着走再折下去"的两段折线，变成一条从衔接点直接平滑
弯下去的弧线。这样跟上面 contour2 衔接的地方只剩一个转折点（跟筑紫一样：转折点
存在，但两侧都是连续弯曲的线条，不会在极短距离内接连出现第二个直角）。

半径用比例算（不写死绝对坐标）：同一个道理，可变字体不同字重下竖笔顶边自己的
长度不同，所有运算从当前字重自己的坐标现场取，公式本身跟字重无关。

只改坐标形状，不额外增删锚点（原来 2 个锚点 [顶边两端] 变成 1 个锚点+1 个新锚点，
净点数不变），不影响跨字重点数/点序一致性，不需要"参照字重判一次、全字重套用"
那一套。

用法：
    python3 tools/le_slant.py <in.ttf> <out.ttf>
"""
from fontTools.ttLib import TTFont
import sys

# 圆弧半径相对竖笔顶边自身长度的比例。1.0 = 把整条顶边都吃进弧线（完全消灭原来
# 的直角），>1.0 会让弧线探出顶边以外到竖笔左侧去（不合理，不用）；<1.0 会在弧线
# 末尾跟竖笔右边之间留一小截残留直线（退化回部分直角）。取 1.0：彻底消灭顶边。
CORNER_R_RATIO = 1.0


import math

# 2026-10-16～17：曾经试过把筑紫 A 丸"了"的真实轮廓坐标直接搬过来用（效果确实
# 好），但筑紫是方正的商业字体、没有开源协议，把它的字形坐标数据抄进这个 OFL
# 字体模块分发有真实的版权风险。后续所有版本（含现在这版续十一）都只借鉴它
# "转折连续、无死角"这个设计原则，坐标全部从本字形自身的现有锚点比例现场算
# 出来，不借用筑紫的任何数值。


def _unit(p0, p1):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy) or 1.0
    return (dx / d, dy / d), d


# ---- 点序号角色表（对所有字重通用）----
# contour0（竖笔+钩尾，19 点）：[0] 是竖笔左上角（衔接点，跟 contour2 的终点坐标
# 重合）、[1] 是竖笔右上角（原来的直角拐角顶点）、[2] 是竖笔右边往下走的第一个点。


# 2026-10-16～17：竖笔+钩尾这段曲线试过好几版构造方式——"对称弓形"（两条边各自
# 独立或在公共高度区间内同步往一侧鼓一下，`_bow_points()`）、"单调漂移但两端
# 各自独立构造 3 控制点 B 样条、再在落地点数值核验/搜索修正曲率符号和量级"
# （`_sweep_points()` + `_best_sweep_lead_and_bias()`）——每一版都是先把竖笔
# 和钩尾当成两条独立曲线、再想办法在衔接点让它们"看起来"连续，本质上都是
# 拼接（缝），不是真正的单条曲线，用解析几何核验也确认了拼接处要么切线突变、
# 要么曲率符号/量级对不上。具体每一版的构造公式和失败数值见 git log
# （本文件 2026-10-16/17 的历史提交）和 `docs/evidence/README.md` 第 7 节，
# 这里不重复贴、也不留着废弃代码。

# 2026-10-17 续十一：改成直接把新漂移段的 off-curve 控制点接到钩尾自己原有的
# off-curve 控制点上、中间不插入任何 on-curve 锚点——TrueType 二次样条的规则是
# "任意一串连续 off-curve 控制点，相邻两点间会自动补一个隐式 on-curve 中点，
# 该中点两侧的切线各自正比于 (下一控制点-当前控制点)/2，在隐式中点处必然
# 相等"（证明见 `slant_le()` 里对应位置的注释），也就是说只要是同一串连续
# off-curve 点，不需要额外构造就天然处处切线连续——是真正的一条曲线，不是
# 两条曲线在某点凑出同样的切线/曲率。因此不再需要 `_best_sweep_lead_and_bias()`
# 那套曲率匹配二分查找，相关辅助函数全部删除。


# 竖笔+钩尾整体往左漂移的幅度，相对"公共高度区间长度/水平边长度两者取小值"的
# 比例——纯原创参数，现场从本字形自身比例算，不是从筑紫哪个数字换算来的。
# 取值比历史上失败的对称弓方案（0.16）大得多，因为这次不是"弓一下再弓回去"，
# 是整条边单调漂移到一个新位置，要让效果跟筑紫那种"整条腿明显斜甩出去"的观感
# 对得上，幅度必须足够大、不能是容易被看成瑕疵的小幅度。
SWEEP_RATIO = 0.42


def slant_le(glyph, glyf_table):
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    n0 = ends[0] + 1  # contour0 的点数（竖笔+钩尾那条轮廓，永远是第一条）

    A = coords[0]   # 衔接点（不动，跟 contour2 保持缝合）
    V = coords[1]   # 原直角拐角顶点（水平边→垂直边的转折点）
    C = coords[2]   # 垂直边上的下一个点

    assert abs(A[1] - V[1]) < 1, "unexpected point order: [0]->[1] 应为水平边"
    assert abs(V[0] - C[0]) < 1, "unexpected point order: [1]->[2] 应为垂直边"

    d_in, len_in = _unit(A, V)    # 水平边方向（通常是 +x）
    d_out, len_out = _unit(V, C)  # 垂直边方向（通常是 -y）

    r = min(len_in * CORNER_R_RATIO, len_out * 0.5)

    p1 = (V[0] - d_in[0] * r, V[1] - d_in[1] * r)   # 水平边上往回退 r（取 r=len_in 时等于 A 本身）
    p2 = (V[0] + d_out[0] * r, V[1] + d_out[1] * r)  # 垂直边上往前进 r 的新锚点

    new_coords = list(coords)
    new_flags = list(flags)

    # 新序列：[A(锚点,不动), V(控制点,off-curve), p2(锚点,新)] 替换原来的 [A(锚点), V(锚点)]，
    # 其余点（含 C 及之后）原样保留，点数净不变（2 个锚点 -> 1 锚点 1 控制点 1 新锚点 = 仍是 3 个槽位里 2 个 on + 1 off，
    # 相比原来 2 个 on，多了 1 个点——用插入而不是等量替换，所有字重统一多这一个点，不破坏跨字重一致性）。
    new_pts = [
        (int(round(A[0])), int(round(A[1])), True),
        (int(round(V[0])), int(round(V[1])), False),
        (int(round(p2[0])), int(round(p2[1])), True),
    ]

    rest_after_c = [(int(coords[k][0]), int(coords[k][1]), bool(flags[k])) for k in range(3, n0)]
    hook_end = rest_after_c[-1]  # 钩尾终点（= 原来的最后一个点）

    # 2026-10-16 七续：主人实测放大图后反馈竖笔中段仍然"不平滑"/"有瘪陷"，先退回
    # 竖笔主干为纯直线（只保留转角去尖角）。八续：主人看过筑紫真实轮廓放大图后，
    # 明确要求按筑紫那种"整条竖笔+钩尾是一条连续大弯弧、钩尾位置整体跟着偏移"的
    # 结构重做，并确认愿意承担这个结构性改动范围更大、风险更高（见 `_sweep_points()`
    # 文档字符串）。
    #
    # 做法：竖笔右边（p2->C）、左边（hook_end->A）在"双方都存在"的公共高度区间
    # （y_lo..y_hi，算法跟历史上弓形方案的公共区间完全一样，保证两边在重叠区间内
    # 用同一个漂移量、笔画粗细不变）内，用同一个单调递增的漂移量（从顶部 0 到底部
    # max_shift）让两条边一起往左漂移；公共区间以下的整条钩尾（c_pt 本身以及它
    # 之后的所有钩尾点）做刚体整体平移（只平移 x，y 不变），钩尾自己的形状、比例
    # 完全不变，只是作为一个整体挪到新的衔接位置，不会因为平移产生新的自相交。
    right_x, left_x = C[0], A[0]
    y_hi = min(p2[1], A[1])
    y_lo = max(C[1], hook_end[1])
    assert y_hi > y_lo, "unexpected geometry: 公共高度区间为空，几何假设不成立（用于 max_shift 定比例）"
    shared_len = y_hi - y_lo
    max_shift = min(shared_len, len_in) * SWEEP_RATIO

    rp_hi = (right_x, y_hi)
    lp_hi = (left_x, y_hi)

    # 钩尾刚体整体左移 max_shift（只挪 x）：钩尾自己的形状、比例完全不变，只是
    # 作为一个整体挪到新的衔接位置。
    rest_after_c_shifted = [(p[0] - max_shift, p[1], p[2]) for p in rest_after_c]
    rest_after_c_shifted = [(int(round(p[0])), int(round(p[1])), p[2]) for p in rest_after_c_shifted]

    # 2026-10-17 续十一：主人反馈"你做的是 S 不是一条曲线"、"不提炼筑紫的统一/
    # 圆润思想、只照抄肯定没法做出好效果"——复查认同：续十（曲率反号/量级匹配）
    # 本质上仍然是"建两条独立曲线，在衔接点上让数值尽量对上"，哪怕符号、量级都
    # 对上了，依然是**拼接**，不是一条曲线，残留的"腰身"正是这个结构性问题的
    # 外在表现，不是参数没调够——这也正是筑紫"逢角必圆、一笔到底"背后的原则：
    # 不是"转折处弧度要够大"，是"根本不应该存在两段独立拼起来的曲线"。
    #
    # 真正的做法：不再发明 rp_lo/lp_lo 这两个人为的"落地锚点"，把新增的控制点
    # 直接续接到钩尾本来就有的 off-curve 控制点上，变成**同一条**连续的 TrueType
    # off-curve 点串（中间全部是隐式中点，不额外插 on-curve 锚点）。这是 TrueType
    # 样条的基本性质，不是经验手法：任意一串连续 off-curve 控制点，相邻两段在
    # 隐式中点处的切线严格相等（可以解析证明：对隐式中点 M=(P_i+P_{i+1})/2，
    # 前一段终点切线正比于 M-P_i=(P_{i+1}-P_i)/2，后一段起点切线正比于
    # P_{i+1}-M=(P_{i+1}-P_i)/2，两者恒等），不管控制点怎么摆都成立——也就不存在
    # "新曲线"和"钩尾原有曲线"之间需要另外验算、另外凑数值的独立拼接点了。
    #
    # 之前当作"衔接点"的 rp_lo/lp_lo，核实过在原始（未改造前）字形里根本不是什么
    # 真实设计转折：hook_end 前后切线严格一致、曲率为零（算出来就是一条直线中间
    # 顺带经过的一个点），只是笔画宽度在这个高度上恰好被两条直线各自途经，才被
    # 历史上几版方案借用来当"落地点"——这个点本身没有需要保留的设计意图，可以
    # 放心地并进连续 off-curve 串里，不会丢笔画本来的造型。钩尾自己真正有意义的
    # 转折点（下面的 `rest_after_c_shifted[2]`、`rest_after_c_shifted[-3]` 之前
    # 那些锚点）完全不碰，原样保留、整体左移。
    assert len(rest_after_c_shifted) >= 4, "unexpected geometry: 钩尾点数太少，并不进连续曲线"
    assert not rest_after_c_shifted[0][2] and not rest_after_c_shifted[1][2], \
        "unexpected point order: 钩尾开头应是两个连续 off-curve 控制点"
    assert not rest_after_c_shifted[-3][2] and not rest_after_c_shifted[-2][2] and rest_after_c_shifted[-1][2], \
        "unexpected point order: 钩尾结尾应是两个连续 off-curve 控制点 + 一个 on-curve 锚点（hook_end）"

    # 右边：p2 -> near0（off，沿 p2 的竖直切线探出，保证跟上面转角圆弧衔接处
    # 切线不变）-> far（off，自由控制点，形状由"跟钩尾第一个 off-curve 控制点
    # 取中点"现算，不是另凑的经验值）-> 直接续接钩尾自己的 off-curve 串，一路
    # 隐式中点连下去，中途不再出现任何额外的 on-curve 锚点。
    right_foot_off0 = rest_after_c_shifted[0][:2]
    right_span = max(p2[1] - right_foot_off0[1], 1.0)
    right_lead = right_span * 0.3
    right_near0 = (p2[0], p2[1] - right_lead)
    right_far = ((right_near0[0] + right_foot_off0[0]) / 2, (right_near0[1] + right_foot_off0[1]) / 2)
    right_mid = [
        (int(round(right_near0[0])), int(round(right_near0[1])), False),
        (int(round(right_far[0])), int(round(right_far[1])), False),
    ]

    # 左边：钩尾自己的 off-curve 串末尾（倒数第二、第三个点，仍然原样保留）->
    # far（off，自由控制点，同样现算中点）-> near1（off，沿 lp_hi 的竖直切线
    # 探出，保证跟上面"残段直线接 A"衔接处切线不变）-> lp_hi。
    left_foot_off1 = rest_after_c_shifted[-2][:2]
    left_span = max(lp_hi[1] - left_foot_off1[1], 1.0)
    left_lead = left_span * 0.3
    left_near1 = (lp_hi[0], lp_hi[1] - left_lead)
    left_far = ((left_foot_off1[0] + left_near1[0]) / 2, (left_foot_off1[1] + left_near1[1]) / 2)
    left_mid = [
        (int(round(left_far[0])), int(round(left_far[1])), False),
        (int(round(left_near1[0])), int(round(left_near1[1])), False),
    ]

    lp_hi_pt = (int(round(lp_hi[0])), int(round(lp_hi[1])), True)

    # 右边：p2 -> 新曲线（near0,far）直接续接钩尾自己的 off-curve 串（已整体
    # 左移）-> 钩尾本体（锚点、形状完全不变）-> 钩尾末尾的 off-curve 串直接续接
    # 新曲线（far,near1）-> lp_hi -> A（残段直线，可能长度为 0）。全程只有一条
    # 连续的 off-curve 点串，中间没有任何额外插入的 on-curve 落地锚点。
    contour0_new = (
        new_pts
        + right_mid
        + rest_after_c_shifted
        + left_mid
        + [lp_hi_pt]
    )

    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    other = [(int(coords[k][0]), int(coords[k][1]), bool(flags[k])) for k in range(n0, len(coords))]
    all_pts = contour0_new + other
    glyph.coordinates = GlyphCoordinates([(p[0], p[1]) for p in all_pts])
    glyph.flags = bytearray([1 if p[2] else 0 for p in all_pts])
    delta = len(contour0_new) - n0
    glyph.endPtsOfContours = [e + delta for e in glyph.endPtsOfContours]
    glyph.recalcBounds(glyf_table)
    return True



# 2026-10-16 再续二：主人确认维持本仓库既有裁决（了字沿用全部 11 个带钩字共用的
# "钩尾一律切、换干净圆头收尾"惯例，不为了字单独破例留钩），追加反馈"现在的转角
# 还有个死尖角"——横笔右端转去斜笔（contour2，独立轮廓）那一段，顶上是 4 个连续
# on-curve 点首尾相接的纯折线（量出来是个"探出横笔右墙之外的小尖角/小旗子"形状，
# 不是曲线），要求去掉，换成跟筑紫一样"转折点两侧都是连续弧线"的平滑过渡——这跟
# 上面竖笔的死角是同一个病根，只是长在横笔转角这一侧，病根手法也一样：找到横笔
# 自己的右上角坐标（活读 contour1，不写死），把这段直线尖角换成一条从横笔边缘
# 直接平滑弯进原有斜笔弧线的曲线，不再探出横笔边缘以外。
FOLD_ROUND_RATIO = 0.6   # 新起点相对横笔自身粗细（thickness）回缩的比例，纯几何
                         # 比例、现场从 contour1 自己的宽度算，不是筑紫的数字。
                         # 2026-10-16 三续：0.4 太保守——新起点离横笔右墙（contour1
                         # 自己的直角拐角）太近，曲线还没来得及往下弯，横笔自己那段
                         # 垂直墙皮就先露出来一截，变成"一小截直墙+再转弧线"的两段式
                         # 死角。四续：改用 vf_round.py 同款"拐角削圆"公式（新控制点
                         # 直接取原拐角顶点本身，不是跟 first_off 取中点）之后，中点
                         # 取法试过 1.1 比例会让曲线在新起点处越过横笔顶边往外鼓出去
                         # 一点再绕回来，形成自交小豁口（细小三角形缺口，实测出的
                         # bug，不是猜的）——换成"新控制点=原拐角顶点"这个单控制点
                         # 削圆写法后不再自交，比例回调到 0.6，退让距离够、也不越界。


def smooth_fold_nib(glyph, glyf_table):
    """去掉 contour2（横转斜的折角轮廓）开头那个探出横笔边缘的尖角/小旗子形状，
    换成从横笔自己的右上角直接平滑弯进既有斜笔弧线的过渡，不碰斜笔弧线本身
    （contour2 从第 1 个 off-curve 点开始的既有弧线原样保留，只换开头那一段纯折线）。
    """
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    c0_n = ends[0] + 1
    c1_start, c1_end = c0_n, ends[1]
    c2_start, c2_end = c1_end + 1, ends[2]

    # contour1（横笔主干，轴对齐矩形）：按点序号角色表，[1] 是横笔右上角、[2] 是
    # 横笔右下角——用这两点现场算横笔自身粗细（厚度），不猜、不写死。
    bar_tr = coords[c1_start + 1]
    bar_br = coords[c1_start + 2]
    assert abs(bar_tr[0] - bar_br[0]) < 1, "unexpected point order: 横笔右上/右下角应在同一条竖边上"
    bar_thick = abs(bar_tr[1] - bar_br[1])

    # contour2 开头那一串纯折线（探出横笔边缘的尖角）：从本地第 0 点起，数连续
    # on-curve 点的个数（本仓库三档字重实测均为 4 个），直到遇到第一个 off-curve
    # 点为止——那个 off-curve 点以及之后的既有弧线原样不动。
    local_flags = [bool(flags[c2_start + i]) for i in range(c2_end - c2_start + 1)]
    n_beak = 0
    while n_beak < len(local_flags) and local_flags[n_beak]:
        n_beak += 1
    assert n_beak >= 2, "unexpected point order: contour2 开头应有一串 on-curve 尖角折线"

    first_off_idx = c2_start + n_beak  # 既有弧线的第一个 off-curve 控制点，原样保留
    first_off = coords[first_off_idx]

    # 跟 `vf_round.py`/`slant_le()` 同一个削圆公式：新起点 = 横笔右上角沿顶边往回退
    # r（r = 横笔自身厚度 * FOLD_ROUND_RATIO），新控制点直接取横笔右上角原地坐标
    # （不是跟 first_off 取中点——取中点试过会在新起点附近鼓出横笔顶边之外再绕回来，
    # 形成自交小豁口，已实测确认），曲线从新起点出发，一开始切线方向正好延续横笔
    # 顶边本身（因为新起点、新控制点、原拐角三者 y 坐标相同），不会越界鼓出去。
    r = bar_thick * FOLD_ROUND_RATIO
    new_start = (bar_tr[0] - r, bar_tr[1])
    new_ctrl = (bar_tr[0], bar_tr[1])

    new_beak = [
        (int(round(new_start[0])), int(round(new_start[1])), True),
        (int(round(new_ctrl[0])), int(round(new_ctrl[1])), False),
    ]
    rest_c2 = [(int(coords[k][0]), int(coords[k][1]), bool(flags[k])) for k in range(first_off_idx, c2_end + 1)]
    contour2_new = new_beak + rest_c2

    before_c2 = [(int(coords[k][0]), int(coords[k][1]), bool(flags[k])) for k in range(0, c2_start)]

    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    all_pts = before_c2 + contour2_new
    glyph.coordinates = GlyphCoordinates([(p[0], p[1]) for p in all_pts])
    glyph.flags = bytearray([1 if p[2] else 0 for p in all_pts])
    delta = len(contour2_new) - (c2_end - c2_start + 1)
    new_ends = list(glyph.endPtsOfContours)
    new_ends[2] = new_ends[2] + delta
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf_table)
    return True


if __name__ == "__main__":
    f = TTFont(sys.argv[1])
    glyf = f["glyf"]
    cmap = f.getBestCmap()
    gname = cmap[ord("了")]
    g = glyf[gname]
    before = g.getCoordinates(glyf)[0][:6]
    slant_le(g, glyf)
    smooth_fold_nib(g, glyf)
    after = g.getCoordinates(glyf)[0][:6]
    print("了 before:", list(before))
    print("了 after :", list(after))
    f.save(sys.argv[2])
    print("saved ->", sys.argv[2])
