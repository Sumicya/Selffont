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
# 方案：竖笔左边也用同样手法（同一个 BOW_RATIO、同样现场取值、不抄筑紫坐标）弓一下，
# 且让两条边往同一个绝对方向（朝左，钩尾那一侧）弓，弓出来的位移量取两边各自线段/
# 笔画粗细现场算出的值——这样两条边平行地一起弯，中间夹的笔画宽度基本不变，视觉上
# 竖笔变成一条有自然张力的弧线，而不是"一侧鼓包、一侧死直"的不对称怪样。
LEFT_BOW_RATIO = 0.16


def _unit(p0, p1):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy) or 1.0
    return (dx / d, dy / d), d


# ---- 点序号角色表（对所有字重通用）----
# contour0（竖笔+钩尾，19 点）：[0] 是竖笔左上角（衔接点，跟 contour2 的终点坐标
# 重合）、[1] 是竖笔右上角（原来的直角拐角顶点）、[2] 是竖笔右边往下走的第一个点。


def _bow_points(p0, p1, away_dir, bow_ratio, ref_len):
    """把 p0->p1 这一段直线换成一条两端都跟原方向相切（不扰动端点切线方向）、
    中间往 away_dir 一侧鼓一下的对称弧线，返回中间要插入的 3 个新点
    [ctrl1(off), peak(on), ctrl2(off)]（p0、p1 本身不动、不用重复返回）。

    两端切线方向不变这一点很重要：下游 hook_cut.py 的钩尾裁切、圆弧拟合是按
    端点局部切线方向算的，如果端点切线被鼓弧带偏，裁切出来的收尾弧线会跟着歪
    （实测过：只插一个偏向一侧的 off-curve 控制点会让 p1 端的切线整体旋转，下游
    hook_cut 在这个新切线方向上拟合出的收尾弧线变成不对称的两段鼓包，而不是
    干净的单段圆弧）。两端各用一个沿原方向（不带侧向分量）的控制点，鼓起的
    弧线中间再插一个鼓向 away_dir 的锚点，两头切线原样保留，鼓度只体现在中段。
    """
    d, seg_len = _unit(p0, p1)
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    perp = (d[1], -d[0])
    if perp[0] * away_dir[0] + perp[1] * away_dir[1] < 0:
        perp = (-perp[0], -perp[1])
    bow_amt = min(seg_len, ref_len) * bow_ratio
    peak = (mx + perp[0] * bow_amt, my + perp[1] * bow_amt)
    k = seg_len * 0.3  # 控制点沿原方向探出的距离，纯几何比例，跟字重粗细/弓起幅度无关
    ctrl1 = (p0[0] + d[0] * k, p0[1] + d[1] * k)
    ctrl2 = (p1[0] - d[0] * k, p1[1] - d[1] * k)
    return [
        (int(round(ctrl1[0])), int(round(ctrl1[1])), False),
        (int(round(peak[0])), int(round(peak[1])), True),
        (int(round(ctrl2[0])), int(round(ctrl2[1])), False),
    ]


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

    # 弓一点原创弧度：p2 -> C 这一段（原来是死直的竖笔主干）鼓一下，往跟钩尾同一侧
    # （d_in 的反方向，本字体里钩尾是往左弯的，这里保持同一视觉方向）鼓出去，鼓起幅度 =
    # min(线段自身长度, 字重自身笔画粗细) * BOW_RATIO——全部现读这个字形自己的坐标现场算，
    # 没有借用筑紫或任何外部字体的具体数值。两端切线方向保持跟原直线一致（见 `_bow_points`
    # 的函数说明），不扰动 C 点的局部切线——C 是下游 `hook_cut.py` 判断钩尾的"闸门"点之一，
    # 切线被带偏会导致裁切出来的收尾弧线不对称（鼓包），已实测确认、不是猜测。
    c_pt = (int(round(C[0])), int(round(C[1])), True)
    right_bow = _bow_points(p2, C, (-d_in[0], -d_in[1]), BOW_RATIO, len_in)
    rest_after_c = [(int(coords[k][0]), int(coords[k][1]), bool(flags[k])) for k in range(3, n0)]

    # 竖笔左边（钩尾终点 -> 衔接点 A，闭合边，contour0 里首尾相接、不显式存在中间点）
    # 同样弓一下，方向跟右边保持一致（同一个绝对方向，朝钩尾那一侧），让两条边平行弯曲；
    # 同样用两端切线不变的对称弧线，不扰动钩尾终点（也是 hook_cut 的闸门点之一）的切线。
    hook_end = rest_after_c[-1]  # 钩尾终点（= 原来的最后一个点）
    left_bow = _bow_points(hook_end[:2], A, (-d_in[0], -d_in[1]), LEFT_BOW_RATIO, len_in)

    contour0_new = new_pts + right_bow + [c_pt] + rest_after_c + left_bow

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
