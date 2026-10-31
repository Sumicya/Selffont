"""自研汉字字库 → 一份 **可变字体**（wght 300–500，glyf + gvar）。

为什么用 glyf 而不是 CFF2：轮廓是「每笔一环、点数与粗细无关」的折线（见
`design_cjk.stroke_contours`），三档点数一一对应，正好可以用 `gvar` 存三个主节点的
坐标增量。CFF2 也能做，但 charstring 的插值要自己拼 blend 操作符，出错难查；
glyf 的 gvar 是 fontTools 直接支持的格式，肉眼可核。

可变字体对形状的要求（2026-10-28 定）：
  · 三档点数必须完全相同 → 由 `contours_at()` 保证，构建期逐字断言；
  · 端点用二次曲线圆头 → 这里用折线近似后仍保持每环点数一致；
  · 只开放一个轴：wght 300–500，默认 400。
"""
from __future__ import annotations

import io
from pathlib import Path

WEIGHT_MIN, WEIGHT_DEFAULT, WEIGHT_MAX = 300, 400, 500

# 字身框（设计原则 2026-10-28）：越界就不是字，是数据错——统一在一个 em 的 1000 单位里，
# 汉字墨迹不该跑到 900 以上或 −160 以下，否则行框再准也会顶到上一行。
FRAME = (-40, 1040, -160, 900)

# 字宽自算（不搬任何人的 advance 表）：
#  · 全角类占满一个 em —— 这是汉字排版的栅格约定，不是某个字体的偏好；
#  · 半角类按本字实际墨宽 + 两侧固定侧距，侧距取 0.06 em；
#  · 没有墨的空白字符取四分之一 em（全角空白由上面的全角类接走）。
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


def _body_index():
    """字身带落在 48 条横带里的下标区间（含两端）。"""
    y0, y1 = BAND_Y
    lo = max(0, int((BODY_BAND[0] - y0) / (y1 - y0) * 48))
    hi = min(47, int((BODY_BAND[1] - y0) / (y1 - y0) * 48))
    return lo, hi


def _body_edges(edges):
    """只保留字身那几带的最左/最右 x（其余填 None，形状不变）。"""
    lo, hi = _body_index()
    left, right = list(edges[0]), list(edges[1])
    for k in range(len(left)):
        if k < lo or k > hi:
            left[k] = None
            right[k] = None
    return left, right



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


def _coverage(edges, side):
    """贴边覆盖率：这一侧有墨的带里，有多少比例的带贴在极值 `BEARING_COV_TOL` 以内。

    竖笔处处贴边 → 1.0；圆弧只有中段贴边 → 0.3 上下；斜边只有一端贴边 → 0.2 上下。
    只数**有墨**的带：字腔里的空带不参与，否则 `o` 会按孔洞的高度被摊薄。
    """
    edge = [v for v in (edges[0] if side == "left" else edges[1]) if v is not None]
    if not edge:
        return 1.0
    ext = min(edge) if side == "left" else max(edge)
    return sum(1 for v in edge if abs(v - ext) < BEARING_COV_TOL) / len(edge)


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
        elif op == "lineTo":
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


def pair_white(advance: int, a, b) -> float | None:
    """a 后接 b 的最小墨迹白（两字都有墨的行）。两个 profile 都是行法。"""
    import numpy as np
    left_a, right_a = a
    left_b, _ = b
    whites = advance + left_b - right_a
    whites = whites[~np.isnan(whites)]
    return float(whites.min()) if len(whites) >= 20 else None


def outline_edges(glyph):
    """一个字形**画出来之后**的逐行左右缘（1 单位一行）。

    不能拿 `rings`（描边出来的理想中线）去量：字形还要过 `curve_fit` 拟合与整数网格，
    拟合完 `o` 的墨宽会比描边时窄 16 单位——拿理想轮廓量字偶距，压下去的是不存在的那点墨。
    """
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    glyph.draw(pen, None)
    return row_profile(rings_from_pen(pen.value))


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
REJECTS: list[tuple[int, str]] = []      # 每次 build_vf 重置，构建期报出来


class _StreamGvar:
    """gvar 表，逐字的编译结果已经存成字节，这里只拼偏移与表头。

    为什么不用 fontTools 的 gvar：它的 compile() 要求把所有字的 TupleVariation
    都放在内存里，33,944 字峰值超过 3 GB，本机只有 3.9 GB，构建中途被 OOM 杀掉。
    """

    def __init__(self):
        from fontTools.ttLib.tables import _g_v_a_r as _g
        self._base = _g.table__g_v_a_r()
        self.blobs = {}

    def compile(self, ttFont):
        self._base.version = self.version
        self._base.reserved = self.reserved
        self._base.variations = {}
        blobs = self.blobs

        def compileGlyphs_(ttFont_, axisTags, sharedCoordIndices):
            return [blobs.get(name, b"") for name in ttFont_.getGlyphOrder()]

        self._base.compileGlyphs_ = compileGlyphs_
        return self._base.compile(ttFont)

    def toXML(self, writer, ttFont):
        pass

    def fromXML(self, name, attrs, content, ttFont):
        pass


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



# ── 字偶距 ──────────────────────────────────────────────────────────────
# 目标不是「一个绝对间隙」，而是母版**真排**出来的每一对的墨迹白（`tools/kern_targets.bin`，
# 由 `tools/kern_measure.py` 量）。上一版失败就失败在用同一个目标值对所有组合：`HH`、`oo`
# 这种本来该留 168/96 的组合也被压到 −30。这一版目标逐对取自母版渲染，母版自己压过的对
# （`Ay` 44、`AT` −3）才压，没压过的对（`HH` 168、`oo` 96）不动。
#
# 构建期只用本字自己的轮廓算同一个「最小墨迹白」，与目标相减就是这一对该给的 `pos` 值：
# 轮廓本身已经和母版差着 ±1%，字宽也是自算的，所以字偶距必须**逐对反解**，
# 抄母版表里的 −180 只会既不够也不对。
KERN_LOW, KERN_HIGH = 0x20, 0x7E     # 只给 ASCII 可打印区做字偶距
KERN_NONE = -32768
KERN_MIN = 5                         # 小于 5 单位的差不写（0.5% em，16 px 下 0.08 px）。
                                     # 原来是 12：`te` 差 9 单位就落在门槛里没写，
                                     # 于是「te 太宽」在字对层面没被修（2026-10-31 实测）。
KERN_FLOOR, KERN_CEIL = -320, 60     # 挡掉母版里几个坏对的离谱值（`W` + `` ` `` 是 −529）

_KERN_GRID: list | None = None


def _kern_grid() -> list:
    """读 `tools/kern_targets.bin`：4 字节 magic + 95×95 个 int16 目标白（小端）。"""
    global _KERN_GRID
    if _KERN_GRID is None:
        import array
        import sys as _sys
        raw = Path(__file__).with_name("kern_targets.bin").read_bytes()
        if raw[:4] != b"SFK1":
            raise ValueError("kern_targets.bin 头不对，重跑 tools/kern_measure.py")
        cells = array.array("h")
        cells.frombytes(raw[4:])
        if _sys.byteorder != "little":
            cells.byteswap()
        _KERN_GRID = cells
    return _KERN_GRID


def kern_target(a: int, b: int) -> int | None:
    """母版真排时这一对的最小墨迹白；没有数据（空格、母版缺字）返回 None。"""
    if not (KERN_LOW <= a <= KERN_HIGH and KERN_LOW <= b <= KERN_HIGH):
        return None
    span = KERN_HIGH - KERN_LOW + 1
    value = _kern_grid()[(a - KERN_LOW) * span + (b - KERN_LOW)]
    return None if value == KERN_NONE else int(value)


def kern_features(profiles: dict) -> str:
    """`profiles`: {码位: (字宽, 逐行最左 x, 逐行最右 x)}（轮廓已平移到侧距上）。

    逐对反解：目标白 − 本字最小白 = 该给的 `pos`。两边的白都由 `row_profile`（1 单位一行）
    量，与 `tools/kern_measure.py` 同一把尺；少于 20 行共同墨的组合不量。
    """
    import numpy as np
    rules = []
    for a, (adv, _, right) in profiles.items():
        for b, (_, left, _) in profiles.items():
            target = kern_target(a, b)
            if target is None:
                continue
            whites = adv + left - right
            whites = whites[~np.isnan(whites)]
            if len(whites) < 20:
                continue
            value = int(min(KERN_CEIL, max(KERN_FLOOR, target - int(round(float(whites.min()))))))
            if abs(value) < KERN_MIN:
                continue
            rules.append(f"    pos uni{a:04X} uni{b:04X} {value};")
    if not rules:
        return ""
    return ("languagesystem DFLT dflt;\n"
            "languagesystem latn dflt;\n"
            "feature kern {\n" + "\n".join(rules) + "\n} kern;\n")


def kern_value(font, a: int, b: int) -> int:
    """从 GPOS 里读一对字的字偶距（给自己加的自检用，不进构建路径）。"""
    from fontTools.ttLib.tables import otTables as ot
    if "GPOS" not in font:
        return 0
    name_a = font.getBestCmap().get(a)
    name_b = font.getBestCmap().get(b)
    if name_a is None or name_b is None:
        return 0
    total = 0
    for lookup in font["GPOS"].table.LookupList.Lookup:
        subs = []
        for sub in lookup.SubTable:
            subs.extend(sub.ExtSubTable if isinstance(sub, ot.ExtensionSubst) else [sub])
        for sub in subs:
            if not isinstance(sub, ot.PairPos) or name_a not in sub.Coverage.glyphs:
                continue
            i = sub.Coverage.glyphs.index(name_a)
            if sub.Format == 1:
                for record in sub.PairSet[i].PairValueRecord:
                    if record.SecondGlyph == name_b and record.Value1:
                        total += getattr(record.Value1, "XAdvance", 0) or 0
            else:
                klass1 = sub.ClassDef1.classDefs.get(name_a, 0)
                klass2 = sub.ClassDef2.classDefs.get(name_b, 0)
                value = sub.Class1Record[klass1].Class2Record[klass2].Value1
                if value:
                    total += getattr(value, "XAdvance", 0) or 0
    return total


def is_han(codepoint: int) -> bool:
    return any(low <= codepoint <= high for low, high in CJK_RANGES)


def align_face_height(rings: dict, weights=(300, 400, 500)) -> dict:
    """同一码位在三档下的**墨迹上下沿必须一致**：字重只改笔画粗细，不改字面高度。

    实测（2026-10-28，构建产物 static-300/400/500，30,385 个汉字逐字比墨迹高）：
    高 400/300 的中位比值 1.024、500/400 的中位比值 1.025，上沿 400−300 中位 +11、
    500−400 中位 +12，下沿同量下沉——每加一档字面就长大 2.5%，两档合计 5%。
    后果是同一行里混排 300 与 500 时，粗的那几个字看着「字号被调大了」，不是「变粗了」；
    500 档的 `Ȭ`（yMax 981）甚至顶穿了 `usWinAscent` 969 被裁掉上沿。

    做法只动竖直方向：以 400 档的墨迹框上沿/下沿为目标，把 300/500 的轮廓沿 y 以框中心
    缩放对齐。**x 一个数都不动**（字宽、侧距、墨迹左右位置属于另两项授权外的事）。
    代价：500 档横画笔宽在竖直方向被压 2.5%（62 单位里 1.5 单位），肉眼不可见；
    换来的是三档同一副字面高度，VF 插值过程中字面框不再随轴滑动。
    """
    if not rings:
        return rings
    base = rings.get(400)
    if not base:
        return rings
    points = [pt for ring in base for pt in ring]
    if not points:
        return rings
    low, high = min(pt[1] for pt in points), max(pt[1] for pt in points)
    if high - low < 1.0:
        return rings
    centre = (low + high) / 2.0
    out = {}
    for weight, weight_rings in rings.items():
        if weight == 400:
            out[weight] = weight_rings
            continue
        own = [pt for ring in weight_rings for pt in ring]
        if not own:
            out[weight] = weight_rings
            continue
        own_low, own_high = min(pt[1] for pt in own), max(pt[1] for pt in own)
        if own_high - own_low < 1.0:
            out[weight] = weight_rings
            continue
        scale = (high - low) / (own_high - own_low)
        own_centre = (own_low + own_high) / 2.0
        out[weight] = [[(x, centre + (y - own_centre) * scale) for x, y in ring]
                       for ring in weight_rings]
    return out


def settle_junction_widths(glyph: dict, weights=(300, 400, 500)) -> None:
    """把交叉口量胖的短笔半宽收回整字中位（就地改 `glyph["strokes"]` 的三档 hw）。

    为什么要有这一步：取笔时每笔的半宽是从母版墨迹的距离变换上量的，量点落在交叉口
    就会被邻笔的墨撑大——那里是两条笔画的并集，半径天然是笔宽的好几倍。实测
    `棘`（U+68D8）右半交叉口那笔短笔量到半宽 77（母版该点实际 32.6、整字中位 27.8），
    画出来是一坨黑斑；`荆`（U+8346）同样。这类短笔只是补路口圆角用的圆盘，半径应当
    等于穿过路口的笔宽，也就是整字中位，绝不是交叉口并集的半径。

    实测分布（2026-10-28，30,519 个汉字逐笔比「该笔半宽 ÷ 整字中位」）：中位 1.00，
    5% 分位 0.87、95% 分位 1.09，超过 1.25 的只占 0.39%——正常笔画的偏差远小于此，
    所以以「短于自身直径」判圆盘、「1.25 倍中位」判量胖，只碰异常笔。

    只对汉字执行：非汉字里的实心符号（面填）本来就由长度不一的胶囊拼成，宽窄是设计，
    按中位收回会把符号挖空。
    """
    strokes = glyph.get("strokes") or []
    if len(strokes) < 2:
        return
    medians = {}
    for weight in weights:
        values = [(stroke.get("hw") or {}).get(weight) for stroke in strokes]
        values = sorted(v for v in values if v)
        if not values:
            continue
        mid = len(values) // 2
        medians[weight] = (values[mid] if len(values) % 2
                           else (values[mid - 1] + values[mid]) / 2.0)
    if not medians:
        return
    for stroke in strokes:
        hw = stroke.get("hw")
        if not isinstance(hw, dict):
            continue
        length = 0.0
        for seg in stroke.get("segs") or []:
            for a, b in zip(seg, seg[1:]):
                length += ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        own = hw.get(400) or 0.0
        disc = length < 2.0 * own if own else True
        for weight, median in medians.items():
            value = hw.get(weight)
            if not value:
                continue
            if disc:
                hw[weight] = median
            else:
                hw[weight] = min(max(value, median * 0.7), median * 1.25)


def _outside_frame(rings) -> str:
    """三档轮廓里有没有跑出字身框；返回原因（空串 = 没越界）。

    只管汉字：字母 `g` `(` 这类本来就有下伸部，拿汉字的框去卡它只会把 ASCII 全删掉。
    """
    x0, x1, y0, y1 = FRAME
    for weight, glyph_rings in rings.items():
        for ring in glyph_rings:
            for x, y in ring:
                if x < x0 or x > x1 or y < y0 or y > y1:
                    return f"{weight} 档 ({x:.0f},{y:.0f}) 越出 {FRAME}"
    return ""


def _glyph_rings_all(glyph: dict):
    """三档轮廓（真二次曲线），三档点数与 on/off 标志逐一对应。"""
    import design_cjk
    return design_cjk.outline_curves(glyph)


def _glyph_from_rings(rings, flags):
    """按 TrueType 的点序直接造字形：on/off 标志与 gvar 的增量必须逐点对齐。

    为什么不用 TTGlyphPen：它只会 lineTo，输出的是折线（设计原则 2026-10-24
    「全是直线的输出无论 IoU 多高都是多边形字体」）。手写 Glyph 才能把二次曲线的
    控制点放进去，而且点序与 `base` 完全一致，gvar 的增量不会错位。
    """
    from array import array

    from fontTools.ttLib.tables import ttProgram
    from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates, flagOnCurve

    coords, values, ends = [], [], []
    for ring, f in zip(rings, flags):
        for (x, y), on in zip(ring, f):
            coords.append((x, y))
            values.append(flagOnCurve if on else 0)
        ends.append(len(coords) - 1)
    glyph = Glyph()
    glyph.numberOfContours = len(rings)
    glyph.coordinates = GlyphCoordinates(coords)
    glyph.flags = array("B", values)
    glyph.endPtsOfContours = ends
    glyph.program = ttProgram.Program()
    glyph.program.fromBytecode(b"")
    return glyph


def build_vf(glyphs: dict[int, dict], family: str = "Selfrounds CJK",
             style: str = "Regular", ps_name: str = "SelfroundsCJK",
             version: str | None = None) -> bytes:
    """码位 → 可变 OTF（TrueType 轮廓 + gvar），单一 wght 轴 300–500。

    **会消费传入的字典**：每建一个字就 pop 掉，三万字全摊成 Python 对象要 500 MB 以上，
    机器只有 3.9 GB，不边建边丢会 OOM。调用方要先记字数、要复用就传副本。
    """
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables.TupleVariation import TupleVariation
    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    from fontTools.ttLib.tables._g_v_a_r import compileGlyph_ as _compile_gvar_glyph
    

    order = [".notdef"]
    cmap: dict[int, str] = {}
    advance_by_name: dict[str, int] = {}
    kern_profiles: dict[int, tuple] = {}
    REJECTS.clear()

    def draw(rings, flags):
        return _glyph_from_rings(rings, flags)

    default_glyphs, variation_blobs = {}, {}
    empty = TTGlyphPen(None).glyph()
    default_glyphs[".notdef"] = empty
    for codepoint in sorted(glyphs):
        data = glyphs.pop(codepoint)
        if is_han(codepoint):
            settle_junction_widths(data)
        rings, flags = _glyph_rings_all(data)
        rings = align_face_height(rings)
        # 非全角字形（拉丁、数字、标点）的侧距按边缘形状给，并把轮廓平移到该侧距上。
        # 汉字不动：它自带全角框，墨迹位置属于字面的一部分（2026-10-28 主人定）。
        if not any(low <= codepoint <= high for low, high in FULL_WIDTH) and rings.get(WEIGHT_DEFAULT):
            ink_left = min(pt[0] for ring in rings[WEIGHT_DEFAULT] for pt in ring)
            ink_right = max(pt[0] for ring in rings[WEIGHT_DEFAULT] for pt in ring)
            target = None if _is_letter(codepoint) else side_target(codepoint)
            if target is not None:
                # 非字母：前进量与墨心照母版（母版这一类逐个手调，没有可拟合的公式）。
                # 本字的墨宽与母版差着几个单位，按墨心摆，两侧留白随本字自己分。
                shift = target[1] - (ink_left + ink_right) / 2
                fixed_advance = target[0]
            else:
                left, right = sides_of(rings, codepoint)
                # 字母只把**字身**对齐到侧距；钩、尾这些伸到字身之外的墨按母版的做法
                # 留在原点左边（母版 `j` 的 lsb 是 −63：钩本来就该挂到前一个字下面）。
                anchor = _body_ink(rings, "left", ink_left) if _is_letter(codepoint) else ink_left
                shift = left - anchor
                fixed_advance = None
            if abs(shift) > 0.5:
                rings = {w: [[(x + shift, y) for x, y in ring] for ring in rr]
                         for w, rr in rings.items()}
        else:
            fixed_advance = None
        advance = fixed_advance if fixed_advance is not None else advance_of(codepoint, rings)
        # 字身框闸门：越界的汉字不进字体（宁可缺字也不发顶行的字）。越界不是靠平移
        # 糊过去——`align_face_height` 把三档压到同一副字面之后，全库 0 个汉字越框；
        # 真出现越界，说明取笔或校准有一处错了，要修那处，不是把字挪进框里。
        outside = _outside_frame(rings) if is_han(codepoint) else ""
        if outside:
            REJECTS.append((codepoint, outside))
            continue
        name = f"uni{codepoint:04X}"
        order.append(name)
        cmap[codepoint] = name
        advance_by_name[name] = advance
        counts = {w: [len(r) for r in rings[w]] for w in rings}
        if not (counts[WEIGHT_MIN] == counts[WEIGHT_DEFAULT] == counts[WEIGHT_MAX]):
            raise ValueError(f"U+{codepoint:04X} 三档轮廓点数不一致，无法做可变：{counts}")
        default_glyphs[name] = draw(rings[WEIGHT_DEFAULT], flags[WEIGHT_DEFAULT])
        if KERN_LOW <= codepoint <= KERN_HIGH:
            # 量的是**画出来之后**的那个字形：拟合与整数网格都会改墨宽，拿描边的理想轮廓
            # 去量，压下去的是不存在的那点墨（实测 `o` 差 16 单位）。
            edges = outline_edges(default_glyphs[name])
            if edges is not None:
                kern_profiles[codepoint] = (advance, edges[0], edges[1])
        base = [pt for ring in rings[WEIGHT_DEFAULT] for pt in ring]
        if len(base) < 2:
            continue
        built = []
        # 两个主节点的坐标增量（坐标是整数，字体单位本来就是整数网格）
        # gvar 的坐标是**归一化值**（F2Dot14，[-1,1]），不是 wght 原值。
        # 默认 400，所以 -1 = 300、+1 = 500。
        for weight, location in ((WEIGHT_MIN, {"wght": (WEIGHT_MIN - WEIGHT_DEFAULT)
                                               / (WEIGHT_DEFAULT - WEIGHT_MIN)}),
                                 (WEIGHT_MAX, {"wght": (WEIGHT_MAX - WEIGHT_DEFAULT)
                                               / (WEIGHT_MAX - WEIGHT_DEFAULT)})):
            flat = [pt for ring in rings[weight] for pt in ring]
            # gvar 的增量必须是整数：轮廓本身就在整数网格上，四舍五入即可。
            deltas = [(int(round(x2 - x1)), int(round(y2 - y1)))
                      for (x1, y1), (x2, y2) in zip(base, flat)]
            # gvar 的增量数组必须带 4 个 phantom points（左/右 side bearing、上/下边距），
            # 少 4 个的话编译能过、读回时断言失败——不解包一次根本发现不了。
            deltas += [(0, 0)] * 4
            if all(dx == 0 and dy == 0 for dx, dy in deltas):
                continue
            # 位置必须是 (start, peak, end) 三元组；只写峰值会被当成标量而炸在编译期。
            variation = TupleVariation({tag: (value, value, value)
                                        for tag, value in location.items()}, deltas)
            built.append(variation)
        if built:
            # 立刻编译成字节：33,944 字的 TupleVariation 全攒着要 3 GB 以上，
            # 机器只有 3.9 GB，攒到一半就被 OOM 杀掉。编译后只留 ~2 KB/字。
            variation_blobs[name] = _compile_gvar_glyph(
                2, built, 0, ["wght"], {}, optimizeSize=True)

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(cmap)
    builder.setupGlyf(default_glyphs)
    # 字宽必须逐字取母版量的值：CJK 是 1000，但 `a` 535、`A` 653、`1` 383。
    # 一律写 1000 的话，这个字件（排在主字体之前）会把拉丁和数字摊成一个个方块。
    metrics = {".notdef": (1000, 0)}
    for name in order[1:]:
        glyph = default_glyphs[name]
        glyph.recalcBounds(builder.font["glyf"])
        # hmtx 的左边距必须写字形真实的 xMin：TrueType 的约定就是 lsb == xMin，写 0 是
        # 「数据里说左边距为零、轮廓却从 200 开始」。FreeType 会按这个差值平移轮廓——
        # 实测同一份 `日`（xMin 198）在 lsb=0 时比 lsb=xMin 时整体左移 198 单位，
        # 满字库就是每个字按自己的 xMin 左移（`，` 偏 404 单位），行内空隙忽大忽小。
        # 这个值**不改轮廓、不改字宽**，只让 hmtx 与 glyf 自洽。
        metrics[name] = (advance_by_name.get(name, 1000), int(getattr(glyph, "xMin", 0)))
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=880, descent=-120)
    builder.setupNameTable({
        "familyName": family, "styleName": style,
        "uniqueFontIdentifier": f"{family} {style} 1.000",
        "fullName": f"{family} {style}", "psName": ps_name,
        # nameID 5 也跟版本号同一套：正式发布写 yy.m.d.当日序号.总序号，迭代版只写 1.000。
        "version": f"Version {version}" if version else "Version 1.000",
        "copyright": "Derived from Maruko Gothic (max32002/maruko-gothic, SIL OFL 1.1).",
        "licenseDescription": "SIL Open Font License 1.1",
    })
    builder.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=880, usWinDescent=120,
                     sxHeight=500, sCapHeight=700, achVendID="SLFF",
                     usWeightClass=WEIGHT_DEFAULT)
    builder.setupPost()
    builder.addOpenTypeFeatures(kern_features(kern_profiles))

    font = builder.font
    axis = newTable("fvar")
    from fontTools.ttLib.tables._f_v_a_r import Axis
    fvar_axis = Axis()
    fvar_axis.axisTag = "wght"
    fvar_axis.minValue, fvar_axis.defaultValue, fvar_axis.maxValue = (
        WEIGHT_MIN, WEIGHT_DEFAULT, WEIGHT_MAX)
    fvar_axis.axisNameID = font["name"].addName("Weight")
    fvar_axis.flags = 0
    axis.axes = [fvar_axis]
    # 命名实例：三档各一条，方便系统按字重枚举
    from fontTools.ttLib.tables._f_v_a_r import NamedInstance
    axis.instances = []
    for weight, label in ((WEIGHT_MIN, "Light"), (WEIGHT_DEFAULT, "Regular"), (WEIGHT_MAX, "Medium")):
        instance = NamedInstance()
        instance.coordinates = {"wght": weight}
        instance.subfamilyNameID = font["name"].addName(label)
        instance.postscriptNameID = 0xFFFF
        axis.instances.append(instance)
    font["fvar"] = axis

    gvar = _StreamGvar()
    gvar.version = 1
    gvar.reserved = 0
    gvar.blobs = variation_blobs
    font["gvar"] = gvar

    buffer = io.BytesIO()
    font.save(buffer)
    return buffer.getvalue()
