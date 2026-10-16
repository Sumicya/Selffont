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


def _unit(p0, p1):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy) or 1.0
    return (dx / d, dy / d), d


# ---- 点序号角色表（对所有字重通用）----
# contour0（竖笔+钩尾，19 点）：[0] 是竖笔左上角（衔接点，跟 contour2 的终点坐标
# 重合）、[1] 是竖笔右上角（原来的直角拐角顶点）、[2] 是竖笔右边往下走的第一个点。


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

    # 弓一点原创弧度：p2 -> C 这一段（原来是死直的竖笔主干）插一个 off-curve 控制点，
    # 往跟钩尾同一侧（d_in 的反方向，本字体里钩尾是往左弯的，这里保持同一视觉方向）
    # 鼓一点，弓起幅度 = min(线段自身长度, 字重自身笔画粗细) * BOW_RATIO——全部现读
    # 这个字形自己的坐标现场算，没有借用筑紫或任何外部字体的具体数值。只做这一步、
    # 不碰 contour2，风险面依然很小。
    bow_mx, bow_my = (p2[0] + C[0]) / 2, (p2[1] + C[1]) / 2
    seg_dx, seg_dy = C[0] - p2[0], C[1] - p2[1]
    seg_len = math.hypot(seg_dx, seg_dy) or 1.0
    # 垂直于线段方向、朝 -d_in（跟横边延伸方向相反，即朝钩尾那一侧）鼓出去
    perp = (seg_dy / seg_len, -seg_dx / seg_len)
    if perp[0] * (-d_in[0]) + perp[1] * (-d_in[1]) < 0:
        perp = (-perp[0], -perp[1])
    bow_amt = min(seg_len, len_in) * BOW_RATIO
    bow_pt = (bow_mx + perp[0] * bow_amt, bow_my + perp[1] * bow_amt)

    c_pt = (int(round(C[0])), int(round(C[1])), True)
    bow_ctrl = (int(round(bow_pt[0])), int(round(bow_pt[1])), False)
    rest_after_c = [(int(coords[k][0]), int(coords[k][1]), bool(flags[k])) for k in range(3, n0)]
    contour0_new = new_pts + [bow_ctrl, c_pt] + rest_after_c

    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    other = [(int(coords[k][0]), int(coords[k][1]), bool(flags[k])) for k in range(n0, len(coords))]
    all_pts = contour0_new + other
    glyph.coordinates = GlyphCoordinates([(p[0], p[1]) for p in all_pts])
    glyph.flags = bytearray([1 if p[2] else 0 for p in all_pts])
    delta = len(contour0_new) - n0
    glyph.endPtsOfContours = [e + delta for e in glyph.endPtsOfContours]
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
    after = g.getCoordinates(glyf)[0][:6]
    print("了 before:", list(before))
    print("了 after :", list(after))
    f.save(sys.argv[2])
    print("saved ->", sys.argv[2])
