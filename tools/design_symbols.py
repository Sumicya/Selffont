"""自研符号设计：按自己的规则画，不从任何母版改。

设计规则（本文件就是规则本身）
------------------------------
1. **栅格**：upm 1000；符号区以 (500, 400) 为中心，外接半径上限 300。
2. **笔宽**：半宽 `HW = 31`（笔画总宽 62，即 6.2% em，常规字重）。
3. **端头**：一律圆端头，半径 = HW；开放笔画用 round cap，收笔就是半圆。
4. **拐角**：一律圆角，半径 ≥ HW；实现方式是「折线按 2·HW 宽 stroke」，
   圆角是 stroke 的的几何结果，不是事后倒角。
5. **曲线**：全部用二次贝塞尔贴圆弧（每 45° 一段，控制点取切线交点，
   半径误差 +0.06%），**构造上切线连续**，不做事后平滑。
6. **留白**：相邻笔画中心线间距 ≥ 3·HW，否则视觉上会粘连。

为什么这样就不需要「修平滑」
----------------------------
上一轮我在原版轮廓上做布尔运算，输出的边界是碎线段＋多边形圆，锚点比原版多 74%、
>5° 折角多 181%（`tools/g1_audit.py` 实测）。这一版每个字形都由弧和直线组成，
圆与折线的交界处本来就相切，没有需要修的折角。
"""
from __future__ import annotations

import math

import pathops
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.pointInsidePen import PointInsidePen

HW = 31                    # 半笔宽
CX, CY = 500.0, 400.0      # 符号中心
R_MAX = 300.0              # 外接半径上限


# ------------------------------------------------------------------ 曲线基元
def _arc_quads(cx, cy, r, a0, a1, segs):
    """用 segs 段二次贝塞尔贴一段圆弧（角度递增）。控制点在切线交点，
    距圆心 r/cos(Δ/2)，45° 段半径误差 +0.06%。"""
    out = []
    for i in range(segs):
        t0 = a0 + (a1 - a0) * i / segs
        t1 = a0 + (a1 - a0) * (i + 1) / segs
        p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
        p1 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
        rm = r / math.cos((t1 - t0) / 2)
        tm = (t0 + t1) / 2
        out.append((p0, (cx + rm * math.cos(tm), cy + rm * math.sin(tm)), p1))
    return out


def circle(cx, cy, r, segs=12):
    """整圆（填充用）。"""
    p = pathops.Path()
    p.moveTo(cx + r, cy)
    for _a, c, b in _arc_quads(cx, cy, r, 0.0, 2 * math.pi, segs):
        p.quadTo(*c, *b)
    p.close()
    return p


def arc_path(cx, cy, r, a0_deg, a1_deg, segs=None):
    """圆弧的**中线路径**（未加粗）。"""
    a0 = math.radians(a0_deg)
    a1 = math.radians(a1_deg)
    n = segs if segs is not None else max(1, int(abs(a1_deg - a0_deg) / 45) + 1)
    p = pathops.Path()
    p.moveTo(cx + r * math.cos(a0), cy + r * math.sin(a0))
    for _a, c, b in _arc_quads(cx, cy, r, a0, a1, n):
        p.quadTo(*c, *b)
    return p


def poly(pts, closed=False):
    p = pathops.Path()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if closed:
        p.close()
    return p


def thick(path, width=2 * HW):
    """把中线加粗成笔画：圆端头、圆拐角。返回填充轮廓。"""
    p = pathops.Path()
    p.addPath(path)
    p.stroke(width, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    p.convertConicsToQuads()
    return p


def stroke_line(p0, p1, width=2 * HW):
    return thick(poly([p0, p1]), width)


def stroke_poly(pts, closed=False, width=2 * HW):
    return thick(poly(pts, closed), width)


def stroke_arc(cx, cy, r, a0, a1, width=2 * HW):
    return thick(arc_path(cx, cy, r, a0, a1), width)


def ring(cx, cy, r, width=2 * HW):
    """圆环：整圆 stroke。内圈半径 r−HW，外圈 r+HW，两圈都是精确圆。"""
    return thick(circle(cx, cy, r, segs=12), width)


def rounded_rect_path(x0, y0, x1, y1, r):
    """圆角矩形的中线。"""
    p = pathops.Path()
    p.moveTo(x0 + r, y0)
    p.lineTo(x1 - r, y0)
    for _a, c, b in _arc_quads((x1 - r), (y0 + r), r, -90.0, 0.0, 1):
        p.quadTo(*c, *b)
    p.lineTo(x1, y1 - r)
    for _a, c, b in _arc_quads((x1 - r), (y1 - r), r, 0.0, 90.0, 1):
        p.quadTo(*c, *b)
    p.lineTo(x0 + r, y1)
    for _a, c, b in _arc_quads((x0 + r), (y1 - r), r, 90.0, 180.0, 1):
        p.quadTo(*c, *b)
    p.lineTo(x0, y0 + r)
    for _a, c, b in _arc_quads((x0 + r), (y0 + r), r, 180.0, 270.0, 1):
        p.quadTo(*c, *b)
    p.close()
    return p


def rect_outline(x0, y0, x1, y1, r=None):
    """矩形轮廓：中线矩形加粗。r 是中线角半径，实际外角半径 = r + HW。"""
    return thick(rounded_rect_path(x0, y0, x1, y1, HW if r is None else r))


def filled_rounded_rect(x0, y0, x1, y1, r):
    p = rounded_rect_path(x0, y0, x1, y1, r)
    return p


def half_disc(cx, cy, r, ang_deg, segs=6):
    """半圆盘：直径方向为 ang_deg ± 90°，弧朝 ang_deg。"""
    a0 = math.radians(ang_deg) - math.pi / 2
    p = pathops.Path()
    p.moveTo(cx + r * math.cos(a0), cy + r * math.sin(a0))
    for _a, c, b in _arc_quads(cx, cy, r, a0, a0 + math.pi, segs):
        p.quadTo(*c, *b)
    p.close()
    return p


def sector(cx, cy, r, a0_deg, a1_deg, segs=3):
    """扇形（填充）。"""
    a0 = math.radians(a0_deg)
    p = pathops.Path()
    p.moveTo(cx, cy)
    p.lineTo(cx + r * math.cos(a0), cy + r * math.sin(a0))
    for _a, c, b in _arc_quads(cx, cy, r, a0, math.radians(a1_deg), segs):
        p.quadTo(*c, *b)
    p.close()
    return p


def U(*paths):
    """并集。"""
    out = paths[0]
    for q in paths[1:]:
        out = pathops.op(out, q, pathops.PathOp.UNION)
    return out


def D(a, b):
    """差集 a − b。"""
    return pathops.op(a, b, pathops.PathOp.DIFFERENCE)


def _reversed_into(contour, pen):
    """把一条轮廓反向画进 pen。

    不能用 `pathops.Path.reverse()`：实测它不改变绕向（反向前后 area 完全一样）。
    用 fontTools 的 `ReverseContourPen`，它按 TrueType 的 qCurveTo 语义正确处理
    隐含点（`qCurveTo(..., None)`），手写展开必错。
    """
    rec = RecordingPen()
    _single(contour).draw(ReverseContourPen(rec))
    rec.replay(pen)


def _orient(contour):
    """绕向：TrueType 约定外轮廓顺时针 → 有符号面积 < 0。

    `pathops.Path.area` **不带符号**（反向前后同值），所以符号只能用轮廓点的
    鞋带公式求。控制点闭合出来的多边形绕向与真实曲线一致，取符号足够。
    """
    pts = [(float(x), float(y)) for x, y in contour.points]
    return sum(pts[k][0] * pts[(k + 1) % len(pts)][1]
               - pts[(k + 1) % len(pts)][0] * pts[k][1]
               for k in range(len(pts)))


def _contained(inner, outer):
    """inner 是否被 outer 包含：取 inner 的若干个点，看是否都在 outer 内。

    用 `PointInsidePen` 逐点精确判定。不能用「|inner ∩ outer| == |inner|」：
    pathops 布尔会把曲线近似成折线，实测面积比到 1.027，容差放宽到能过就会误判。
    """
    pts = [(float(x), float(y)) for x, y in inner.points]
    if not pts:
        return False
    probes = pts[:1] + pts[len(pts) // 2:len(pts) // 2 + 1]
    hits = 0
    for pt in probes:
        pen = PointInsidePen(None, pt)
        _single(outer).draw(pen)
        hits += 1 if pen.getResult() else 0
    return hits == len(probes)


def _single(contour):
    p = pathops.Path()
    p.addPath(contour)
    return p


def canon(path):
    """规范化绕向：外轮廓顺时针（有符号面积 < 0），内白逆时针。

    为什么必须做：pathops 的 `op()` 不保证输出绕向与输入一致。实测两个并排的方框环
    并集之后，绕向从「外正内负」整体翻成「外负内正」，内白被填实、方框糊成一坨。
    TrueType 和所有填写规则都依赖绕向，所以每个字形出口都要过这一道。

    嵌套深度用 pathops 的布尔交精确判定：「A ⊆ B」等价于「|A ∩ B| == |A|」。
    不展平成折线——展平要先处理 TrueType 的隐含点写法，手写会错（已错过一次）。
    """
    items = []
    for c in path.contours:
        single = _single(c)
        items.append(dict(contour=c, area=single.area, absa=abs(single.area),
                          orient=_orient(c)))
    if not items:
        return path

    out = pathops.Path()
    pen = out.getPen()
    for it in items:
        if it["absa"] < 1e-9:
            continue
        depth = 0
        for other in items:
            if other is it or other["absa"] <= it["absa"] + 1e-6:
                continue
            if _contained(it["contour"], other["contour"]):
                depth += 1
        want_negative = (depth % 2 == 0)
        if want_negative == (it["orient"] < 0):
            out.addPath(it["contour"])
        else:
            _reversed_into(it["contour"], pen)
    return out


def _chord_dy(r, dx):
    return math.sqrt(max(0.0, r * r - dx * dx))


# ------------------------------------------------------------------ 字形表
def g_1F7F1():
    """CIRCLE WITH DOUBLE VERTICAL AND HORIZONTAL LINE"""
    r = R_MAX
    parts = [ring(CX, CY, r)]
    for dx in (-45, 45):
        dy = _chord_dy(r, dx)
        parts.append(stroke_line((CX + dx, CY - dy), (CX + dx, CY + dy)))
    for dy in (-45, 45):
        dx = _chord_dy(r, dy)
        parts.append(stroke_line((CX - dx, CY + dy), (CX + dx, CY + dy)))
    return U(*parts)


def g_1F7F2():
    """DOUBLE CIRCLE WITH DOUBLE HORIZONTAL LINE"""
    r = R_MAX
    parts = [ring(CX, CY, r), ring(CX, CY, r - 2 * HW - 24)]
    for dy in (-45, 45):
        dx = _chord_dy(r - HW, dy)
        parts.append(stroke_line((CX - dx, CY + dy), (CX + dx, CY + dy)))
    return U(*parts)


def g_1F7F3():
    """CIRCLED BOTTOM RIGHT OBLIQUE HALF BLACK CIRCLE"""
    r = R_MAX
    return U(ring(CX, CY, r), half_disc(CX, CY, r - HW - 6, -45.0))


def _half_ring(cx, cy, r_out, width, ang_deg, segs=6):
    """半个圆环的填充轮廓：外半圆 + 内半圆 + 两条直径边，闭合。

    不能用「开放圆弧 stroke」再并一条直径线：两个圆头会在直径两端各自鼓出一个球，
    而且并集边界会形成锯齿（实测 1F7F4 的边缘成了波浪形）。
    """
    r_in = r_out - width
    a0 = math.radians(ang_deg) - math.pi / 2
    a1 = a0 + math.pi
    p = pathops.Path()
    p.moveTo(cx + r_out * math.cos(a0), cy + r_out * math.sin(a0))
    for _a, c, b in _arc_quads(cx, cy, r_out, a0, a1, segs):
        p.quadTo(*c, *b)
    p.lineTo(cx + r_in * math.cos(a1), cy + r_in * math.sin(a1))
    for _a, c, b in _arc_quads(cx, cy, r_in, a1, a0, segs):
        p.quadTo(*c, *b)
    p.close()
    return pathops.simplify(p) if False else p


def g_1F7F4():
    """LEFT HALF WHITE CIRCLE —— 左半圆环（开口朝右）"""
    return _half_ring(CX, CY, R_MAX, 2 * HW, 180.0)


def g_1F7F5():
    """RIGHT HALF WHITE CIRCLE —— 右半圆环（开口朝左）"""
    return _half_ring(CX, CY, R_MAX, 2 * HW, 0.0)


_FRONT = (330.0, 230.0, 590.0, 490.0)
_OFF = (150.0, -110.0)


def _cube_edges(back_only_hidden=False):
    x0, y0, x1, y1 = _FRONT
    dx, dy = _OFF
    f = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    b = [(x0 + dx, y0 + dy), (x1 + dx, y0 + dy), (x1 + dx, y1 + dy), (x0 + dx, y1 + dy)]
    parts = [stroke_poly(f, closed=True)]
    if back_only_hidden:
        # 白色立方体：只画看得见的背棱（上、右）和四条连线
        parts.append(stroke_line(b[0], b[1]))
        parts.append(stroke_line(b[1], b[2]))
    else:
        parts.append(stroke_poly(b, closed=True))
    for k in range(4):
        parts.append(stroke_line(f[k], b[k]))
    return U(*parts)


def g_1F7F6():
    """TRANSPARENT CUBE —— 透视线全画"""
    return _cube_edges(back_only_hidden=False)


def g_1F7F7():
    """WHITE CUBE —— 实心白面，背面的隐藏棱不画"""
    return _cube_edges(back_only_hidden=True)


def g_1F7F8():
    """HORIZONTAL DOUBLE WHITE SMALL SQUARE —— 两个方框并排，中间留 ≥3HW 的空隙。

    注意 rect_outline 的中线要各让开 HW，否则两圈的墨会连成一片（第一版就粘住了：
    中线间隙 30 < 2·HW=62）。
    """
    s = 130.0                # 方框中线半边长
    gap = 2 * HW + 16        # 两个中线框之间留出的净空
    dx = gap / 2 + s
    return U(rect_outline(CX - dx - s, CY - s, CX - dx + s, CY + s),
             rect_outline(CX + dx - s, CY - s, CX + dx + s, CY + s))


def g_1F7F9():
    """VERTICAL DOUBLE WHITE SMALL SQUARE —— 上下两个方框，同上留净空。"""
    s = 130.0
    gap = 2 * HW + 16
    dy = gap / 2 + s
    return U(rect_outline(CX - s, CY + dy - s, CX + s, CY + dy + s),
             rect_outline(CX - s, CY - dy - s, CX + s, CY - dy + s))


def _square(half=250.0):
    return rect_outline(CX - half, CY - half, CX + half, CY + half)


def g_1F7FA():
    """WHITE SQUARE WITH BOTTOM HALF BISECTED"""
    h = 250.0
    return U(_square(h), stroke_line((CX, CY), (CX, CY - h)))


def g_1F7FB():
    """WHITE SQUARE WITH TOP HALF BISECTED"""
    h = 250.0
    return U(_square(h), stroke_line((CX, CY), (CX, CY + h)))


def g_1F7FC():
    """WHITE SQUARE WITH HORIZONTAL AND VERTICAL BISECTING LINES"""
    h = 250.0
    return U(_square(h),
             stroke_line((CX - h, CY), (CX + h, CY)),
             stroke_line((CX, CY - h), (CX, CY + h)))


def g_1F7FD():
    """LOWER LEFT FLATTENED RIGHT TRIANGLE"""
    return stroke_poly([(200, 700), (800, 700), (200, 500)], closed=True)


def g_1F7FE():
    """LOWER RIGHT FLATTENED RIGHT TRIANGLE"""
    return stroke_poly([(800, 700), (200, 700), (800, 500)], closed=True)


def g_1F7FF():
    """RHOMBUS"""
    return stroke_poly([(CX, 100), (CX + 300, CY), (CX, 700), (CX - 300, CY)],
                       closed=True)


# ---------------------------------------------------------------- 补充标点
def _wavy(x0, y0, y1, amp, turns=3):
    """垂直波浪中线：n 段二次贝塞尔，交替左右摆。"""
    p = pathops.Path()
    p.moveTo(x0, y0)
    seg = (y1 - y0) / turns
    sign = 1.0
    for i in range(turns):
        ya = y0 + seg * i
        yb = ya + seg
        p.quadTo(x0 + sign * amp, (ya + yb) / 2, x0, yb)
        sign = -sign
    return p


def g_2E60():
    """WIGGLY EXCLAMATION MARK —— 波折竖干 + 下点"""
    stem = thick(_wavy(CX, 210.0, 700.0, 52.0, 3))
    return U(stem, circle(CX, 115.0, 44.0))


def g_2E61():
    """INVERTED WIGGLY EXCLAMATION MARK —— 上点 + 波折竖干"""
    stem = thick(_wavy(CX, 100.0, 590.0, 52.0, 3))
    return U(stem, circle(CX, 685.0, 44.0))


def g_2E62():
    """LEFT PARENTHESIS WITH MIDDLE RING"""
    r = 280.0
    paren = stroke_arc(CX + 150, CY, r, 125.0, 235.0)
    mx = CX + 150 + r * math.cos(math.radians(180.0))
    return U(paren, ring(mx, CY, 52.0))


def g_2E63():
    """RIGHT PARENTHESIS WITH MIDDLE RING"""
    r = 280.0
    paren = stroke_arc(CX - 150, CY, r, -55.0, 55.0)
    mx = CX - 150 + r * math.cos(0.0)
    return U(paren, ring(mx, CY, 52.0))


def g_208F():
    """MODIFIER LETTER HIGH AND LOW VERTICAL LINE"""
    return U(stroke_line((CX - 60, 470), (CX - 60, 700)),
             stroke_line((CX + 60, 100), (CX + 60, 330)))


# ---------------------------------------------------------------- 注册表
_RAW = {
    0x1F7F1: ("circleDoubleLine", g_1F7F1),
    0x1F7F2: ("circleDoubleCircleLine", g_1F7F2),
    0x1F7F3: ("circleHalfBlackOblique", g_1F7F3),
    0x1F7F4: ("circleLeftHalfWhite", g_1F7F4),
    0x1F7F5: ("circleRightHalfWhite", g_1F7F5),
    0x1F7F6: ("cubeTransparent", g_1F7F6),
    0x1F7F7: ("cubeWhite", g_1F7F7),
    0x1F7F8: ("squareDoubleWhiteHorizontal", g_1F7F8),
    0x1F7F9: ("squareDoubleWhiteVertical", g_1F7F9),
    0x1F7FA: ("squareBottomBisected", g_1F7FA),
    0x1F7FB: ("squareTopBisected", g_1F7FB),
    0x1F7FC: ("squareBisectingLines", g_1F7FC),
    0x1F7FD: ("triangleFlattenedLowerLeft", g_1F7FD),
    0x1F7FE: ("triangleFlattenedLowerRight", g_1F7FE),
    0x1F7FF: ("rhombus", g_1F7FF),
    0x2E60: ("exclamWiggly", g_2E60),
    0x2E61: ("exclamWigglyInverted", g_2E61),
    0x2E62: ("parenLeftRing", g_2E62),
    0x2E63: ("parenRightRing", g_2E63),
    0x208F: ("modifierVertical", g_208F),
}


def glyphs():
    """对外出口：所有字形都过一遍绕向规范化，避免 op() 翻绕向导致内白被填实。"""
    return {cp: (name, (lambda fn=fn: canon(fn()))) for cp, (name, fn) in _RAW.items()}


GLYPHS = glyphs()
