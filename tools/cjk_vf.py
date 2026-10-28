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
SIDE_BEARING = 60
BLANK_WIDTH = 250
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
    """这一笔字该占多宽：全角一个 em，半角按墨宽加侧距，空白四分之一 em。"""
    if any(low <= codepoint <= high for low, high in FULL_WIDTH):
        return EM
    points = [pt for weight_rings in rings.values() for ring in weight_rings for pt in ring]
    if not points:
        return BLANK_WIDTH
    width = max(pt[0] for pt in points) - min(pt[0] for pt in points)
    return max(200, int(round(width)) + 2 * SIDE_BEARING)


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
    """三档轮廓，共用一套已合并共线点的点集。"""
    import design_cjk
    return design_cjk.outline_points_all(glyph)


def build_vf(glyphs: dict[int, dict], family: str = "Selfrounds CJK",
             style: str = "Regular", ps_name: str = "SelfroundsCJK") -> bytes:
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
    REJECTS.clear()

    def draw(rings, pen):
        for ring in rings:
            pen.moveTo(ring[0])
            for point in ring[1:]:
                pen.lineTo(point)
            pen.closePath()
        return pen

    default_glyphs, variation_blobs = {}, {}
    empty = TTGlyphPen(None).glyph()
    default_glyphs[".notdef"] = empty
    for codepoint in sorted(glyphs):
        data = glyphs.pop(codepoint)
        if is_han(codepoint):
            settle_junction_widths(data)
        rings = _glyph_rings_all(data)
        rings = align_face_height(rings)
        advance = advance_of(codepoint, rings)
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
        pen = TTGlyphPen(None)
        draw(rings[WEIGHT_DEFAULT], pen)
        default_glyphs[name] = pen.glyph()
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
        "version": "Version 1.000",
        "copyright": "Derived from Maruko Gothic (max32002/maruko-gothic, SIL OFL 1.1).",
        "licenseDescription": "SIL Open Font License 1.1",
    })
    builder.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=880, usWinDescent=120,
                     sxHeight=500, sCapHeight=700, achVendID="SLFF",
                     usWeightClass=WEIGHT_DEFAULT)
    builder.setupPost()
    builder.addOpenTypeFeatures("")

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
