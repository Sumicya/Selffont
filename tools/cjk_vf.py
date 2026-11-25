"""侧距与字偶距度量库（文件名沿用旧名，自研汉字 VF 已于 2026-11-22 下线）。

现在只服务拉丁区：`side_target()` 读 `side_targets.bin`（非字母逐字侧距），
`BAND_Y`／`rings_from_pen`／`row_profile` 是量字偶距时展开字形的公共底座，
`tools/kern_measure.py`／`side_measure.py`／`master_box.py` 都从这里取。

度量单位：upm 1000；字形用「每笔一环」展开后按横带网格取最左/最右 x，
网格上下界 `BAND_Y = (-260, 960)`。
"""
from __future__ import annotations


WEIGHT_MIN, WEIGHT_DEFAULT, WEIGHT_MAX = 300, 400, 500



FULL_WIDTH = ((0x2E80, 0x303F), (0x3040, 0x9FFF), (0xF900, 0xFAFF),
              (0xFE30, 0xFE4F), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6),
              (0x20000, 0x2FA1F))
EM = 1000
BLANK_WIDTH = 250

# 侧距不是常数（主人 2026-10-30「t 和 e 疑似有点远」「全部间距优化」「y 怎么没插进 A 里面」）。
# 一刀切 0.06 em 的后果是：竖笔（`l` `H`）嫌松、斜边（`A` `V` `W`）和圆底（`o` `e`）嫌紧，
# 因为斜边与圆弧在视觉上已经自带空白，不需要再给同样宽的物理空隙。
#
# **字母**：一个连续量就够了——「贴边覆盖率」cov（这一侧有墨的带里，有多少比例的带贴在
# 极值 30 单位以内）。竖笔 cov≈1（整条边都贴着 xMin）、圆弧 cov≈0.2（只有中段贴边）、
# 斜边 cov≈0.2 但后退快。母版 52 个字 104 个侧面最小二乘：侧距 = 24 + 58·cov，
# 中位误差 5.5 单位、87% 的侧面落在 ±10 内（旧的「平/圆/斜」三档：中位 9.0、77% 在 ±12 内，
# 且把 `h` 的肩、`C` 的开口、`U` 的竖笔全判错）。学的是母版的**规则**，不是抄某一组字宽。
BEARING_COV_BASE, BEARING_COV_GAIN = 21, 60
BEARING_COV_TOL = 30      # 「贴着极值」的容差：字体的笔画本身就是整数网格，±30 是半个 x-height 的 6%
BEARING_MIN, BEARING_MAX = 16, 88

# **非字母**（数字、标点、符号）仍按边缘形状分三类：母版给数字与标点的是另一套手调的
# 数值（`1` 的左距 11、右距 140；括号两侧 85；句点 66），连续式套上去中位误差 37 单位，
# 不能一把尺用到底。三档取母版自己聚出来的三个簇（母版 84 组拉丁字形：平边 84、圆边 47、斜边 26）。
BEARING_FLAT, BEARING_ROUND, BEARING_DIAG = 84, 47, 26



BAND_Y = (-260, 960)      # 横带网格的上下界（字体单位）：汉字墨迹包络之外，留足余量


def _band_edges(rings, bands=48):
    """把一圈轮廓按水平带切，取每一带墨迹的最左/最右 x。

    只读 400 档：侧距是排版节奏，三档共用一套，字重不该改变字距。
    """
    # 一笔一环：一个字的轮廓是好几个环，只看第一个环会把整字量成一条笔画。
    # 环与环之间**不能连成一条边**：首尾相连会凭空多出一条穿过字心的假边
    # （`i` 的点与竖笔连起来、`A` 的三角孔连到外框），每带的极值就被这条假边带跑，
    # 侧距会按不存在的那半边墨算——实测 `i` 的贴边覆盖率因此从 0.86 掉到 0.07。
    allrings = rings.get(400) or (next(iter(rings.values())) if rings else [])
    allrings = [ring for ring in allrings if len(ring) >= 2]
    if sum(len(ring) for ring in allrings) < 3:
        return None
    # 带必须切在**全字库共用的 y 网格**上：字与字之间的「第 k 带」要对得齐，
    # 否则算出来的字偶距比的是两个不同高度（实测会把 S+t 算成 -80 的撞墨值）。
    y0, y1 = BAND_Y
    left, right = [], []
    for k in range(bands):
        lo = y0 + (y1 - y0) * k / bands
        hi = y0 + (y1 - y0) * (k + 1) / bands
        xs = []
        for ring in allrings:
            n = len(ring)
            for i in range(n):
                a, b = ring[i], ring[(i + 1) % n]
                for yy in (lo, hi):
                    if (a[1] - yy) * (b[1] - yy) <= 0 and abs(a[1] - b[1]) > 1e-9:
                        t = (yy - a[1]) / (b[1] - a[1])
                        xs.append(a[0] + t * (b[0] - a[0]))
        if xs:
            xs.sort()
            left.append(xs[0])
            right.append(xs[-1])
        else:
            # 空带必须占位（None），否则第 k 个元素对不上「全字库第 k 带」
            left.append(None)
            right.append(None)
    return left, right



# 字身带：baseline 到 cap-height 之间（y ∈ [-20, 700]）。侧距要按**字身**的边算，
# 不能按整字墨迹的边算——`j` 的钩、`y` 的尾、`Q` 的尾都伸到字身之外，把它们算进
# 「贴边覆盖率」会把侧距判成 0，再把整字平移过去，`j` 就整个右移 100 单位（实测）。
BODY_BAND = (-20, 700)






# 非字母（数字、标点、符号）的前进量与墨心：母版对这一类是**逐个手调**的，三档模型
# 量不准（中位差 48 单位、`+` 差 194、`[` 被 200 的下限夹住）。表由
# `tools/side_measure.py` 从母版量出：目标前进量 + 墨心，构建期把本字的墨按墨心摆好、
# 前进量照表——两边留白随本字墨宽自己分（母版自己也有两侧都负的，`—` 的 lsb/rsb 都是 −20）。
SIDE_MAGIC = b"SFS2"
_SIDE: dict[int, tuple[int, int]] | None = None


def side_target(codepoint: int) -> tuple[int, int] | None:
    """母版给这个非字母的前进量与墨心；没有数据返回 None（字母、全角、母版缺字）。"""
    global _SIDE
    if _SIDE is None:
        import struct
        raw = Path(__file__).with_name("side_targets.bin").read_bytes()
        if raw[:4] != SIDE_MAGIC:
            raise ValueError("side_targets.bin 头不对，重跑 tools/side_measure.py")
        _SIDE = {}
        for off in range(4, len(raw), 8):
            cp, advance, center = struct.unpack_from("<IHh", raw, off)
            _SIDE[cp] = (advance, center)
    return _SIDE.get(codepoint)



def _bearing_letter(profile, side):
    """字母的侧距：`21 + 60·cov`，夹在 [16, 88]。

    系数在母版 104 个字母侧面上按**逐行**覆盖率重拟合（旧常数 24/58 是用 48 条粗带拟的，
    而那条尺在曲线字上是错的）：中位误差 5.6 → 4.3 单位。
    """
    raw = BEARING_COV_BASE + BEARING_COV_GAIN * row_coverage(profile, side)
    return int(min(BEARING_MAX, max(BEARING_MIN, round(raw))))


def _is_letter(codepoint: int) -> bool:
    import unicodedata
    return unicodedata.category(chr(codepoint))[0] == "L"



def rings_from_pen(value) -> list:
    """把一条 RecordingPen 的点列拆成若干环，曲线按 10/12 段折线展开（只用标准库）。

    构建期与 `tools/kern_measure.py` 必须走**同一个**展开器：字偶距是两边各自量同一个
    「最小墨迹白」再相减，两边展开方式只要差一点，量出来的就不是同一个高度上的白。
    """
    rings, ring, cur, start = [], None, None, None
    for op, args in value:
        if op == "moveTo":
            cur = start = (float(args[0][0]), float(args[0][1]))
            ring = [cur]
            rings.append(ring)
            continue
        # 真字库里存在「没有 moveTo 就直接开段」的环：TrueType 允许一整条环全是 off 点，
        # fontTools 的 draw 遇到这种环会从 qCurveTo 起手。此前这里直接 ring.append 会炸
        # （2026-11-05 全量构建在 33,808 字里的某一个上 AttributeError: NoneType.append）。
        # 补一个起点继续走：首点就是本段第一个非空点，环的形状与闭合方式不变。
        if ring is None:
            first = next((p for p in args if p is not None), None)
            if first is None:
                continue
            cur = start = (float(first[0]), float(first[1]))
            ring = [cur]
            rings.append(ring)
        if op == "lineTo":
            cur = (float(args[0][0]), float(args[0][1]))
            ring.append(cur)
        elif op in ("qCurveTo", "curveTo"):
            pts = [None if q is None else (float(q[0]), float(q[1])) for q in args]
            if op == "qCurveTo":
                # TrueType 允许多个连续的 off 控制点：**相邻两个控制点的中点隐含为 on 点**。
                # 旧实现把每个控制点都当成「从 cur 直接连到 end」的一段，一条光滑弧被拆成
                # 几段挤在同一对端点之间——`e` `o` `S` 这些曲线字展开出来的是乱环，于是
                # 「每带最左/最右 x」全错、字偶距的目标白跟着错（母版 35 点的 `e` 有 7 段
                # 连续 off）。展开器一旦错，量出来的白就不是屏幕上那个白。
                finish = pts[-1] if pts[-1] is not None else (start if start is not None else cur)
                seq = [(True, cur)]                       # [(是否 on, 点)]
                ctrls = [q for q in pts[:-1] if q is not None]
                for i, c in enumerate(ctrls):
                    seq.append((False, c))
                    if i + 1 < len(ctrls):
                        nxt = ctrls[i + 1]
                        seq.append((True, ((c[0] + nxt[0]) / 2, (c[1] + nxt[1]) / 2)))
                seq.append((True, finish))
                i = 0
                while i < len(seq) - 1:
                    (on_a, a), (on_b, b) = seq[i], seq[i + 1]
                    if on_a and not on_b:
                        on_c, c = seq[i + 2]
                        for j in range(1, 11):
                            t = j / 10.0
                            u = 1 - t
                            ring.append((u * u * a[0] + 2 * u * t * b[0] + t * t * c[0],
                                         u * u * a[1] + 2 * u * t * b[1] + t * t * c[1]))
                        i += 2
                    else:
                        ring.append(b)
                        i += 1
                end = finish
            else:
                c1, c2, end = pts
                for i in range(12):
                    t = i / 12.0
                    u = 1 - t
                    x = (u ** 3 * cur[0] + 3 * u ** 2 * t * c1[0]
                         + 3 * u * t ** 2 * c2[0] + t ** 3 * end[0])
                    y = (u ** 3 * cur[1] + 3 * u ** 2 * t * c1[1]
                         + 3 * u * t ** 2 * c2[1] + t ** 3 * end[1])
                    ring.append((x, y))
            cur = end
            ring.append(end)
        elif op in ("closePath", "endPath"):
            cur = start
    return [r for r in rings if len(r) >= 3]



# ── 逐行墨迹轮廓（1 单位一行）──────────────────────────────────────────────
# 为什么不用 48 条粗带：带高 27 单位，`t` 的横臂与 `e` 的碗在带内一错，量出来的白能差
# 40 单位（实测母版 `te`：带法 188、真实 164.7）。字偶距的目标与实现必须用**同一把**、
# 且这把尺要能看见屏幕上那个白——所以按 1 单位一行取左右缘，曲线先按 10 段展开。
ROW_LO, ROW_HI = -320, 1010


def row_profile(rings):
    """每个整数 y 一行的 (最左 x, 最右 x)，缺行是 nan。"""
    import numpy as np
    n = ROW_HI - ROW_LO + 1
    left = np.full(n, np.inf)
    right = np.full(n, -np.inf)
    for ring in rings:
        pts = np.asarray(ring, dtype=float)
        if len(pts) < 3:
            continue
        nxt = np.roll(pts, -1, axis=0)
        for (x0, y0), (x1, y1) in zip(pts, nxt):
            if y0 == y1:
                continue
            lo, hi = (y0, y1) if y0 < y1 else (y1, y0)
            rows = np.arange(max(ROW_LO, int(np.ceil(lo))), min(ROW_HI, int(np.floor(hi))) + 1)
            if not len(rows):
                continue
            xs = x0 + (rows - y0) * (x1 - x0) / (y1 - y0)
            idx = (rows - ROW_LO).astype(int)
            np.minimum.at(left, idx, xs)
            np.maximum.at(right, idx, xs)
    left[~np.isfinite(left)] = np.nan
    right[~np.isfinite(right)] = np.nan
    return left, right


def row_coverage(profile, side: str) -> float:
    """贴边覆盖率：有墨的行里，有多少比例贴在这一侧极值 `BEARING_COV_TOL` 以内。"""
    import numpy as np
    left, right = profile
    edge = left if side == "left" else right
    vals = edge[~np.isnan(edge)]
    if not len(vals):
        return 0.0
    ext = vals.min() if side == "left" else vals.max()
    return float(np.mean(np.abs(vals - ext) < BEARING_COV_TOL))





def _side_class(edges, side):
    """一侧的形状类别：`flat` 竖边、`round` 圆弧、`diag` 斜边（只给非字母用）。

    判据是**边缘随高度后退多少**（悬空量）：竖边处处贴着 xMin，悬空约 0；圆弧只在
    中间贴边、两端后退，悬空中等；斜边整条斜着走，悬空最大。W/V 这类字悬空不大但
    斜率很陡，额外用「边缘与高度是否单调」补判，否则会被误判成圆边。
    """
    if not edges:
        return "round"
    edge = [v for v in (edges[0] if side == "left" else edges[1]) if v is not None]
    if len(edge) < 3:
        return "round"
    lo, hi = (min(edge), max(edge)) if side == "left" else (max(edge), min(edge))
    span = abs(edge[int(len(edge) * 0.9) - 1] - edge[int(len(edge) * 0.1)]) if len(edge) > 5 else 0.0
    overhang = float(sum(abs(v - (min(edge) if side == "left" else max(edge))) for v in edge)) / len(edge)
    # 两个阈值是**在母版自己的 52 个拉丁字母上拟合**出来的（最小化逐侧侧距误差）：
    # 平均每侧 10.5 单位，52 个字母里 46 个落在同一类。换字库要重拟，不是普适常数。
    if overhang < 20:
        return "flat"
    if overhang > 160 or span > 120:
        return "diag"
    return "round"


def _bearing(cls):
    return {"flat": BEARING_FLAT, "round": BEARING_ROUND, "diag": BEARING_DIAG}[cls]




CJK_RANGES = ((0x2E80, 0x2FDF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
              (0xF900, 0xFAFF), (0x20000, 0x2FA1F))


def advance_of(codepoint: int, rings: dict) -> int:
    """这一笔字该占多宽：全角一个 em，半角按墨宽加两侧**按边缘形状**给的侧距，空白四分之一 em。"""
    if any(low <= codepoint <= high for low, high in FULL_WIDTH):
        return EM
    # 字宽按 **400 档**算：侧距是 400 档的设计量，三档共用同一个字宽，
    # 500 档变粗时自己吃掉一点侧距（这是排版里的常态），不靠加宽字身来让位。
    base = rings.get(WEIGHT_DEFAULT)
    if not base:
        return BLANK_WIDTH
    xs = [pt[0] for ring in base for pt in ring]
    if not xs:
        return BLANK_WIDTH
    left, right = sides_of(rings, codepoint)
    ink_left, ink_right = min(xs), max(xs)
    if codepoint is not None and _is_letter(codepoint):
        # 字母的宽度按**字身**算：伸到字身外的钩、尾是「借用邻居的空间」（母版 `j` 的钩
        # 伸到 xMin −63，字宽仍然只有 235），算进字宽会让 `j` 宽出 100 单位。
        body_left = _body_ink(rings, "left", ink_left)
        body_right = _body_ink(rings, "right", ink_right)
        width = body_right - body_left
    else:
        # 标点、符号的「字身」不在 band 里（`[` `{` 的横臂在 baseline 下与 cap 上），
        # 按字身带取会把 78 单位的横臂判成「伸出去的东西」，整字左移 130（实测 `]`
        # 的 xMin 变成 −85）。这一类按整字墨宽算。
        width = ink_right - ink_left
    return max(120, int(round(width)) + left + right)



def _body_profile(rings: dict):
    """只留字身带（y ∈ [BODY_BAND]）的那些行，其余行变 nan。"""
    import numpy as np
    left, right = row_profile(rings[WEIGHT_DEFAULT])
    rows = np.arange(ROW_LO, ROW_HI + 1)
    outside = (rows < BODY_BAND[0]) | (rows > BODY_BAND[1])
    left = left.copy(); right = right.copy()
    left[outside] = np.nan; right[outside] = np.nan
    return left, right


def _body_ink(rings: dict, side: str, fallback: float) -> float:
    """字身带内这一侧最外的那条墨（没有就退回整字的边）。"""
    import numpy as np
    edge = _body_profile(rings)[0 if side == "left" else 1]
    vals = edge[~np.isnan(edge)]
    if not len(vals):
        return fallback
    return float(vals.min()) if side == "left" else float(vals.max())


def sides_of(rings: dict, codepoint: int | None = None) -> tuple[int, int]:
    """左右侧距（字体单位）。汉字与非汉字的区别只在这里：汉字留 0（字面自带全角框）。

    字母走连续式（`_bearing_letter`），数字/标点/符号走三档（`_side_class`）——两套不是
    为了好看，是母版自己就分两套给：字母的侧距随贴边覆盖率单调走，标点却是逐个手调的。
    """
    edges = _band_edges(rings)
    if edges is None:
        return 0, 0
    if codepoint is not None and _is_letter(codepoint):
        body = _body_profile(rings)
        return _bearing_letter(body, "left"), _bearing_letter(body, "right")
    return _bearing(_side_class(edges, "left")), _bearing(_side_class(edges, "right"))














def is_han(codepoint: int) -> bool:
    return any(low <= codepoint <= high for low, high in CJK_RANGES)












