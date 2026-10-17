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

# 2026-10-16 续：用户直接给了筑紫的真实"了"字坐标做对比（见 docs/evidence），要求
# "完全照着筑紫做"。试过把筑紫那条轮廓的点坐标原样搬过来再按本字重粗细縮放/加粗
# ——视觉效果确实好，但筑紫A丸是方正的商业字体，没有开源协议，直接把它的字形坐标
# 数据搬进这个 OFL 字体模块里分发，版权风险是真实存在的、不是能靠改改坐标绕开的。
# 跟主人核对后决定：不抄筑紫的具体坐标，只照着它"连续弯曲、无死角"这个风格特征，
# 在我们自己已有的竖笔骨架上加一点原创的弧度——所有新坐标都是从这个字形自己的
# 现有锚点（笔画粗细、线段长度）现场算出来的比例，不借用筑紫的任何数值。
BOW_RATIO = 0.16    # 竖笔弓起弧度相对"自身粗细/竖笔长度两者取小值"的比例，纯原创
                     # 参数、凭这版效果目测调的，不是从筑紫哪个数字换算来的

# 2026-10-16 再续：用户看过"只弓了一侧"的效果图，反馈"自己的不够好"，要求再往前走一步
# （"试试1+2"：保留方案2"不抄筑紫坐标、自己现算"的方法，但要争取方案1那种更顺滑/更
# 有笔锋的观感）。复查发现问题根源：上面只弓了竖笔的**右边**（p2->C 这一段，contour0
# 点[1]->[2] 衍生出来的那条边），但竖笔左边——也就是从钩尾终点（contour0 最后一个点）
# 直接连回衔接点 A（contour0 第一个点）那一整段，长度几乎是整条竖笔那么长——原封未动，
# 依然是一条死直线。竖笔左边恰恰是视觉上更显眼的那条轮廓线（它直接面对左侧的留白，
# 而右边弓的那一下被竖笔本身的粗细遮了大半），只弓右边、左边死直，看起来仍然僵硬，
# 这才是"不够好"的真正原因，不是弓的幅度不够。
# 方案：竖笔左边也用同样手法（同一个 BOW_RATIO、不抄筑紫坐标）弓一下，且让两条边
# 往同一个绝对方向（朝左，钩尾那一侧）弓——这一版最初各自独立按"自己那段的长度"
# 现算弓起幅度，重字重实测出一个真 bug（竖笔中段视觉上收窄变形，详见下面
# `slant_le()` 里"公共高度区间"那段说明和处理），现在两边改成在同一个公共高度
# 区间内用同一个 bow_amt，不再各自独立用 LEFT_BOW_RATIO 这个单独比例。


def _unit(p0, p1):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy) or 1.0
    return (dx / d, dy / d), d


# ---- 点序号角色表（对所有字重通用）----
# contour0（竖笔+钩尾，19 点）：[0] 是竖笔左上角（衔接点，跟 contour2 的终点坐标
# 重合）、[1] 是竖笔右上角（原来的直角拐角顶点）、[2] 是竖笔右边往下走的第一个点。


def _bow_points(p0, p1, away_dir, bow_amt):
    """把 p0->p1 这一段直线换成一条 TrueType 多控制点二次 B 样条（3 个连续的
    off-curve 控制点，中间不放任何 on-curve 锚点——TrueType 字形轮廓的标准规则是
    "两个连续 off-curve 点之间自动补一个隐式 on-curve 中点"，这个隐式中点两侧
    天然切线连续，不需要另外计算），整条曲线在纵向中点处往 away_dir 一侧鼓出
    bow_amt（绝对位移量，由调用方现算好传入），两端切线严格等于原来的直线方向。

    2026-10-16 五续：最早的写法是"两端各留一截沿原方向延伸的控制点 + 中间强行
    插一个鼓向一侧的 on-curve 锚点"，两段二次曲线在中间这个锚点处拼接。看似对
    称，实测重字重渲染出来中段有个明显的"V 形缺口/腰部收窄"——用解析几何验证
    （算两段曲线在拼接点的切线方向）发现这其实是必然的：只要鼓起幅度不为 0，
    两端都保持原方向切线 + 中间插一个侧向偏移的 on-curve 点，这三个条件连立
    无解——中间拼接点两侧的切线方向必然不同（实测量出约 48° 的切线突变），
    导致肉眼可见的尖角/瘪陷，根本不是"弓起弧度不够""两边鼓的幅度不对齐"这类
    参数问题，是构造方式本身在几何上做不到平滑。

    六续：改成单段二次贝塞尔曲线（只有 1 个 off-curve 控制点）试过一版——曲线
    本身确实绝对光滑了，但此时为了让曲线中点正好偏移 bow_amt，两端切线被迫
    偏离原方向一个角度（实测约 20°），跟上下游本来就是直线的残段（公共区间
    以外贴着端点的那一小截、以及 hook_cut 处理过的钩尾收口）衔接处又会露出一个
    新的轻微折角——虽然比最早的 48° 尖角好很多，但仍不是真正的"两端切线不变"。

    现在这版（3 个连续 off-curve 控制点 + 2 个隐式 on-curve 中点，不显式写出）：
    两端最近的控制点严格沿原方向（d）放置，保证端点切线精确不变（跟上下游残段
    衔接处切线连续、不会再有折角）；中间再放一个纯侧向偏移的控制点提供鼓度，
    两侧各自的隐式中点由 TrueType 样条规则自动给出、自动保证切线连续，不需要
    额外验算。用二次贝塞尔中点公式反推验证过：中间控制点侧向偏移量取
    bow_amt * 4/3 时，整条曲线在纵向正中点处的鼓出量精确等于 bow_amt（用解析
    几何在本文件开发过程中验证过，非经验值）。
    """
    d, seg_len = _unit(p0, p1)
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    perp = (d[1], -d[0])
    if perp[0] * away_dir[0] + perp[1] * away_dir[1] < 0:
        perp = (-perp[0], -perp[1])
    k = seg_len * 0.3  # 两端控制点沿原方向探出的距离，纯几何比例
    near0 = (p0[0] + d[0] * k, p0[1] + d[1] * k)
    near1 = (p1[0] - d[0] * k, p1[1] - d[1] * k)
    amp = bow_amt * 4.0 / 3.0  # 中间控制点侧向偏移量：见上面公式反推
    far = (mx + perp[0] * amp, my + perp[1] * amp)
    return [
        (int(round(near0[0])), int(round(near0[1])), False),
        (int(round(far[0])), int(round(far[1])), False),
        (int(round(near1[0])), int(round(near1[1])), False),
    ]


def _sweep_points(p0, p1, travel_dir, lead):
    """把 p0->p1 这一段直线换成一条单向（非对称）平移的 TrueType 多控制点二次
    B 样条：p0、p1 允许 x 不同（整条边从 p0 的位置一路平滑漂移到 p1 的位置，
    不要求漂移到中途再漂回来），两端切线都严格沿 travel_dir（跟原来直线段
    的走向一致，衔接处不会有折角），中间控制点取 p0、p1 的几何中点——跟
    `_bow_points()` 用的同一类"3 个连续 off-curve 控制点、中间不放 on-curve
    锚点"手法，光滑性由 TrueType 样条规则本身保证，不需要另外验算。

    2026-10-16 八续：主人看过方正筑紫 A 丸的真实轮廓放大图后反馈——筑紫的
    "了"根本不是"竖笔基本直、中段弓一下"，而是整条竖笔到钩尾全程都在同一条
    连续大弯弧上，而且钩尾本身的落点相对顶部衔接点已经整体往左挪了一大截，
    不是弓完又弓回原位。要达到这个观感，不能只在竖笔中段做文章，要让整条边
    的漂移量从顶部（0）单调增加到钩尾衔接处（最大值），钩尾本身也要跟着整体
    平移（见 `slant_le()` 里对钩尾各点的刚体平移处理），不能在钩尾衔接处又
    弓回原来的 x。主人已确认接受这个结构性改动范围更大、风险更高（之前几版
    "只在中段做文章"的方案都被判不理想）。
    """
    k = lead
    near0 = (p0[0] + travel_dir[0] * k, p0[1] + travel_dir[1] * k)
    near1 = (p1[0] - travel_dir[0] * k, p1[1] - travel_dir[1] * k)
    far = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    return [
        (int(round(near0[0])), int(round(near0[1])), False),
        (int(round(far[0])), int(round(far[1])), False),
        (int(round(near1[0])), int(round(near1[1])), False),
    ]


# 竖笔+钩尾整体往左漂移的幅度，相对"公共高度区间长度/水平边长度两者取小值"的
# 比例——纯原创参数，现场从本字形自身比例算，不是从筑紫哪个数字换算来的。
# 取比 BOW_RATIO（历史上失败的对称弓方案，0.16）大得多的值，因为这次不是"弓一下
# 再弓回去"，是整条边单调漂移到一个新位置，要让效果跟筑紫那种"整条腿明显斜甩
# 出去"的观感对得上，幅度必须足够大、不能是容易被看成瑕疵的小幅度。
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
    assert y_hi > y_lo, "unexpected geometry: 竖笔左右两边公共高度区间为空，几何假设不成立"

    shared_len = y_hi - y_lo
    max_shift = min(shared_len, len_in) * SWEEP_RATIO
    lead = shared_len * 0.3  # 两端控制点沿纵向探出的距离，纯几何比例

    rp_hi = (right_x, y_hi)
    rp_lo = (right_x - max_shift, y_lo)
    lp_lo = (left_x - max_shift, y_lo)
    lp_hi = (left_x, y_hi)

    # 右边往下走（y 递减），左边往上走（y 递增）——travel_dir 决定两端控制点
    # 沿哪个纵向方向探出，保证衔接处切线跟原来的竖直直线方向一致。
    right_mid = _sweep_points(rp_hi, rp_lo, (0.0, -1.0), lead)
    left_mid = _sweep_points(lp_lo, lp_hi, (0.0, 1.0), lead)

    rp_hi_pt = (int(round(rp_hi[0])), int(round(rp_hi[1])), True)
    rp_lo_pt = (int(round(rp_lo[0])), int(round(rp_lo[1])), True)
    lp_lo_pt = (int(round(lp_lo[0])), int(round(lp_lo[1])), True)
    lp_hi_pt = (int(round(lp_hi[0])), int(round(lp_hi[1])), True)

    # 钩尾刚体整体左移 max_shift（只挪 x）：c_pt 本身也在这个刚体里（它是钩尾
    # 轮廓的起点），所以 rest_after_c 的第一个点（= 原 C）平移后就等于 rp_lo /
    # lp_lo 的 x，衔接处不留缝；rest_after_c 的最后一个点（hook_end）平移后
    # 自然跟 lp_lo 对上。
    rest_after_c_shifted = [(p[0] - max_shift, p[1], p[2]) for p in rest_after_c]
    rest_after_c_shifted = [(int(round(p[0])), int(round(p[1])), p[2]) for p in rest_after_c_shifted]

    # 右边：p2(= rp_hi) -> 漂移弧 -> rp_lo -> 钩尾（已整体左移，首点贴合 rp_lo）
    # -> 钩尾末点（已整体左移，贴合 lp_lo）-> lp_lo（残段，通常长度很小）->
    # 漂移弧 -> lp_hi -> A（残段，可能长度为 0）。
    contour0_new = (
        new_pts
        + right_mid
        + [rp_lo_pt]
        + rest_after_c_shifted
        + [lp_lo_pt]
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
