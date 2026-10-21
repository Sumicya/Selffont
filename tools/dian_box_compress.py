"""电的箱体太宽——保持每面墙"粗细"(stroke thickness)不变，只压缩墙的"位置"（往中心
靠拢），不能直接把所有 x 坐标统一按比例缩放——统一缩放会把墙的厚度也跟着缩掉（厚度
是两条平行边的 x 差，整体缩放时这个差值也被同比例缩小），导致压缩后箱体竖墙比横墙、
比电字其它笔画都细一截（"粗细不统一"）。

2026-10-15 续（重大教训，务必不要再犯）：第一版直接把 865.0/788.0/126.0/204.0/171.0
这几个具体坐标数字写死在代码里——这些数字全部来自 wght=400（Regular）这一个字重的
实例化结果。本项目是可变字体（wght 100~900 七档），"电"在不同字重下的绝对坐标完全
不同（实测 wght=100 时左墙厚度只有 32 单位，wght=900 时有 150 单位，跟 Regular 的 78
差好几倍），这版写死数字的脚本只要换一个字重就会直接用不上（坐标对不上，当场报
ValueError），等于这个修复只在 Regular 一个字重上生效——如果不小心真的拿这版去处理
全部字重，要么直接崩在非 Regular 字重上，要么（更危险）悄悄只修好一部分字重，字重
之间箱体宽窄、墙厚细不一致，就是用户说的"粗细不统一"在跨字重维度上的翻版。

改法：不写死任何坐标数字，改成按"点在轮廓里的原始序号"取值——可变字体要求所有字重
共享完全相同的轮廓拓扑（点数、on/off-curve 顺序都必须一致，否则没法跨字重插值），
所以同一个点序号在任何字重下都对应同一个"角色"（比如 contour3 的 0 号点永远是左墙
的外沿、1 号点永远是内沿），只是坐标值随字重变化。把这几个"角色"按点序号固定下来，
坐标在函数里现场从传入的 glyph 读，不取任何硬编码字面量——这样同一份代码不用改一个
字就能在任意字重上正确工作。pivot（压缩中心）也改成从 contour1（笔画主干）自己的左右
边界现场算中点，不用写死的 491.5（那也是 Regular 专属的数字，碰巧等于它那个字重下
主干的中点，换个字重就不对了）。
"""
from fontTools.ttLib import TTFont
import sys

SCALE = 0.75  # 压缩比例：墙的位置绕 pivot 收拢到原距离的 75%，所有字重共用同一个比例
              # （比例是跟字重无关的相对值，不像绝对坐标那样需要按字重现查）。

# ---- 点序号角色表（对所有字重通用，靠可变字体拓扑一致这条硬约束保证）----
# contour2（箱体主轮廓，8 点）：
C2_LEFT_REF_IDXS = (0, 3, 4, 7)     # 箱体自己认为的左边参考值（实际被 contour3 盖住，不影响渲染）
C2_RIGHT_OUTER_IDXS = (1, 2)        # 右墙外沿
C2_RIGHT_INNER_IDXS = (5, 6)        # 右墙内沿（窗口右边界）
# contour3（左墙，4 点）：
C3_OUTER_IDXS = (0, 3)              # 左墙外沿（背景一侧）
C3_INNER_IDXS = (1, 2)              # 左墙内沿（窗口一侧）


def compress_dian(glyph, glyf_table):
    coords, ends, flags = glyph.getCoordinates(glyf_table)
    contours = []
    start = 0
    for e in ends:
        contours.append([list(coords[i]) + [flags[i]] for i in range(start, e + 1)])
        start = e + 1

    if len(contours) < 4:
        raise ValueError(f"电这个字形只有 {len(contours)} 条轮廓，结构跟预期的 4 条不符，"
                          f"大概率是源字体换了版本，先别硬套这份按点序号写死角色的脚本")

    c1 = contours[1]  # 笔画主干（竖笔+钩），拿它顶部那条横截边的左右端点算压缩中心点
    # 注意：不能取 contour1 全部点的 min/max（那是整条"竖笔+钩"的包围盒，钩尾会甩到
    # x~960+，中点被拉偏到 700+，完全不是"主干宽度中心"的意思）——0/1 号点固定是主干
    # 顶端那条横截边的左右端点（对所有字重都一样，可变字体拓扑一致保证的），用这两个
    # 点算中点才是真正跟字重无关、稳定在主干中心附近（实测跨 7 档字重中点在 489~495
    # 之间浮动，足够稳定）。
    pivot = (c1[0][0] + c1[1][0]) / 2.0

    def pos_scale(x):
        return pivot + (x - pivot) * SCALE

    # ---- contour0: 横短杠，整体位置压缩，厚度(y)不受影响，直接整体缩放 x 即可 ----
    c0 = contours[0]
    for p in c0:
        p[0] = pos_scale(p[0])

    # ---- contour2 的右墙 + contour3 的左墙：各自保持厚度不变，只压缩中线位置 ----
    c2, c3 = contours[2], contours[3]

    right_outer_old = c2[C2_RIGHT_OUTER_IDXS[0]][0]
    right_inner_old = c2[C2_RIGHT_INNER_IDXS[0]][0]
    right_thick = right_outer_old - right_inner_old
    right_mid_new = pos_scale((right_outer_old + right_inner_old) / 2.0)
    new_right_outer = right_mid_new + right_thick / 2.0
    new_right_inner = right_mid_new - right_thick / 2.0

    left_outer_old = c3[C3_OUTER_IDXS[0]][0]
    left_inner_old = c3[C3_INNER_IDXS[0]][0]
    left_thick = left_inner_old - left_outer_old
    left_mid_new = pos_scale((left_outer_old + left_inner_old) / 2.0)
    new_left_outer = left_mid_new - left_thick / 2.0
    new_left_inner = left_mid_new + left_thick / 2.0

    # contour2 自己的左边参考值，相对 contour3 外沿的固定偏移原样保留（这段完全不可见，
    # 只要留在 contour3 的厚度范围内、不破坏拓扑有效性即可）
    left_ref_old = c2[C2_LEFT_REF_IDXS[0]][0]
    left_ref_offset = left_ref_old - left_outer_old
    new_left_ref = new_left_outer + left_ref_offset

    for idx in C2_RIGHT_OUTER_IDXS:
        c2[idx][0] = new_right_outer
    for idx in C2_RIGHT_INNER_IDXS:
        c2[idx][0] = new_right_inner
    for idx in C2_LEFT_REF_IDXS:
        c2[idx][0] = new_left_ref
    for idx in C3_OUTER_IDXS:
        c3[idx][0] = new_left_outer
    for idx in C3_INNER_IDXS:
        c3[idx][0] = new_left_inner

    print(f"  pivot={pivot:.1f}  右墙厚度 {right_thick:.1f}(不变) 新位置 outer={new_right_outer:.1f} inner={new_right_inner:.1f}")
    print(f"  左墙厚度 {left_thick:.1f}(不变) 新位置 outer={new_left_outer:.1f} inner={new_left_inner:.1f}")
    print(f"  箱体可见外宽: {new_right_outer - new_left_outer:.1f} (压缩前 {right_outer_old - left_outer_old:.1f})")

    flat = [pt for c in contours for pt in c]
    new_ends = []
    acc = -1
    for c in contours:
        acc += len(c)
        new_ends.append(acc)
    glyph.coordinates = type(glyph.coordinates)([(round(x), round(y)) for x, y, _ in flat])
    glyph.flags = [bool(f) for _, _, f in flat]
    glyph.endPtsOfContours = new_ends
    glyph.recalcBounds(glyf_table)


if __name__ == "__main__":
    f = TTFont(sys.argv[1])
    glyf = f["glyf"]
    cmap = f.getBestCmap()
    gname = cmap[ord("电")]
    g = glyf[gname]
    print(f"compressing {gname}")
    compress_dian(g, glyf)
    f.save(sys.argv[2])
    print("saved ->", sys.argv[2])
