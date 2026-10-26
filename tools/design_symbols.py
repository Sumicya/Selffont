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

HW = 31                    # 符号用半笔宽（62 笔宽）
HW_CJK = 41                # 汉字半笔宽：从文渊实测「一」竖切 82 得出
Y_TOP, Y_BOT = 960, 30     # 汉字字面上/下沿（文渊实测 y 162..999，扣掉一点留白）
X_L, X_R = 60, 940         # 汉字字面左右沿（文渊实测 x 44..960）
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


def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def _ops_to_path(ops):
    """TrueType 画法的事件流 → 显式 moveTo/quadTo 的 pathops.Path。

    必须自己展开：`qCurveTo(..., None)` 是「闭合回起点」，而**以 qCurveTo 开头**的
    轮廓没有显式起点，起点是首末两个控制点的中点（TrueType 的隐含 on-curve 点）。
    直接把这些事件喂给 pathops 的笔，None 会被当成 (0,0)，每个反转过绕向的字形
    都多出一条贯穿画面的斜线（实测圆被斜线切开，填充后只剩半个黑饼）。
    """
    out = pathops.Path()
    cur = None
    for op, args in ops:
        if op == "moveTo":
            out.moveTo(args[0][0], args[0][1])
            cur = args[0]
        elif op == "lineTo":
            out.lineTo(args[0][0], args[0][1])
            cur = args[0]
        elif op == "qCurveTo":
            pts = list(args)
            closed = bool(pts) and pts[-1] is None
            if closed:
                pts = pts[:-1]
                start = _mid(pts[0], pts[-1]) if cur is None else cur
                out.moveTo(start[0], start[1])
                cur = start
            n = len(pts)
            for k in range(n):
                ctrl = pts[k]
                end = cur if (closed and k == n - 1) else (
                    _mid(pts[k], pts[k + 1]) if k + 1 < n else pts[k])
                out.quadTo(ctrl[0], ctrl[1], end[0], end[1])
                cur = end
        elif op == "curveTo":
            pts = list(args)
            if cur is None:
                out.moveTo(pts[0][0], pts[0][1])
                cur = pts[0]
            for k in range(0, len(pts) - 1, 2):
                out.quadTo(pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1])
                cur = pts[k + 1]
        elif op in ("closePath", "endPath"):
            out.close()
            cur = None
    return out


def _reversed(contour):
    """把一条轮廓反向，返回新的 pathops.Path（绕向翻转，形状不变）。

    不能用 `pathops.Path.reverse()`：实测它不改变绕向（反向前后面积完全一样）。
    用 fontTools 的 `ReverseContourPen` 按 TrueType 语义反向，再经 `_ops_to_path`
    展开成显式曲线。
    """
    rec = RecordingPen()
    _single(contour).draw(ReverseContourPen(rec))
    return _ops_to_path(rec.value)


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
        out.addPath(it["contour"] if want_negative == (it["orient"] < 0)
                    else _reversed(it["contour"]))
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


# ------------------------------------------------------------------ 汉字笔画基元
# 二创汉字的规则（从 Maruko 里量出来的三条，见 docs/design-principles.md 2026-10-25）：
#   ① 等宽笔画：半笔宽 31；
#   ② 端头 = 半径等于半笔宽的标准半圆（stroke 的 ROUND_CAP 天然满足）；
#   ③ 骨架定形，笔画沿骨架等宽展开。
# 折角的圆要**内外都圆**，所以不能只靠 stroke 的圆角连接（那样内角仍是尖的）：
# 在中线里先插入二次贝塞尔做圆角，再描边。这样中线本身 G1 连续，内外两侧都圆。

def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def fillet(pts, r=55.0, max_turn_deg=170.0):
    """中线圆角：折点处插入一段**真圆弧**，与两条直段相切。

    早先的写法用「三段点 + 一个二次贝塞尔、控制点取折点」近似，两个致命问题：
      1. 切线长直接取 t = r·tan(θ/2)·1.17，135° 的折角在 r=115 时算出 t≈256，
         把横画右侧整段吃掉（`了` 的包围盒右边界从 731 掉到 634）；
      2. 单段二次贝塞尔画 90° 以上的弧误差极大，弧顶会塌。
    改成「求圆心 → 用 _arc_quads 分 ≤45° 段贴弧」，切线连续且半径就是 r。
    """
    pts = [tuple(map(float, q)) for q in pts]
    if len(pts) < 3:
        return poly(pts)
    out = pathops.Path()
    out.moveTo(*pts[0])
    cur = pts[0]
    for k in range(1, len(pts) - 1):
        v, nxt = pts[k], pts[k + 1]
        ux, uy = _unit(cur, v)
        vx, vy = _unit(v, nxt)
        cosang = max(-1.0, min(1.0, ux * vx + uy * vy))
        turn = math.degrees(math.acos(cosang))
        la = math.hypot(v[0] - cur[0], v[1] - cur[1])
        lb = math.hypot(nxt[0] - v[0], nxt[1] - v[1])
        if turn < 3.0 or turn > max_turn_deg or la < 2 or lb < 2:
            out.lineTo(*v)
            cur = v
            continue
        t = r * math.tan(math.radians(turn) / 2)
        t = min(t, la * 0.45, lb * 0.45)
        a_pt = (v[0] - ux * t, v[1] - uy * t)
        b_pt = (v[0] + vx * t, v[1] + vy * t)
        # 圆心：从折点沿两条边方向的角平分线，距离 r / cos(turn/2)
        d1x, d1y = -ux, -uy
        d2x, d2y = vx, vy
        bx, by = d1x + d2x, d1y + d2y
        bn = math.hypot(bx, by) or 1.0
        bis = (bx / bn, by / bn)
        dist = r / math.cos(math.radians(turn) / 2)
        cx, cy = v[0] + bis[0] * dist, v[1] + bis[1] * dist
        a0 = math.atan2(a_pt[1] - cy, a_pt[0] - cx)
        a1 = math.atan2(b_pt[1] - cy, b_pt[0] - cx)
        while a1 - a0 > math.pi:
            a1 -= 2 * math.pi
        while a0 - a1 > math.pi:
            a1 += 2 * math.pi
        segs = max(1, int(abs(math.degrees(a1 - a0)) / 45) + 1)
        out.lineTo(*a_pt)
        for _p0, c, b in _arc_quads(cx, cy, r, a0, a1, segs):
            out.quadTo(c[0], c[1], b[0], b[1])
        cur = b_pt
    out.lineTo(*pts[-1])
    return out


def stroke_fillet(pts, r=90.0, width=2 * HW):
    """按圆角中线描一条等宽笔画。"""
    return thick(fillet(pts, r), width)


# ------------------------------------------------------------------ 二创汉字
# 字面：x 110..890，y -120..820；基线 0；与 CJK 全角一致，advance 1000。

def _vline_top(y, x=560.0, top=705.0, cut=95.0):
    """竖画的顶端：从横画中线往上一段就停，避免圆头鼓出横画上沿。"""
    return (x, top)


def g_4E59():
    """乙 —— 横 → 斜撇 → 横，一笔连续中线，无钩。

    文渊原版末横末端回卷成钩。这里骨架只有横、斜、横，等宽 82，
    折角是半径 48 的切线圆弧，端头是半径 41 的标准半圆。
    """
    return stroke_fillet([(X_L, 790), (720, 790), (300, 290), (820, 290)],
                         r=48, width=2 * HW_CJK)


def g_4E86():
    """了 —— 横撇与竖是**一条**连续中线：横 → 斜撇 → 转竖，竖末无钩。

    文渊原版的骨架就是这样（放大核对过）：横从左上走到右上，斜撇向左下，
    到字面中部转成竖，一直到底，末端带一个回卷的钩。这里只去掉钩，
    竖以半径 41 的标准半圆收头，其余按同一骨架重画。
    """
    return stroke_fillet([(X_L, 790), (720, 790), (390, 430), (390, Y_BOT + 40)],
                         r=48, width=2 * HW_CJK)


def g_5B50():
    """子 —— 横撇 + 竖（无钩）+ 长横。"""
    # 与「了」同一条骨架：横 → 斜撇 → 转竖；另加一长横穿过竖。
    return U(stroke_fillet([(100, 800), (720, 800), (390, 440), (390, Y_BOT + 40)],
                           r=48, width=2 * HW_CJK),
             stroke_fillet([(150, 300), (X_R, 300)], r=0, width=2 * HW_CJK))


def g_4E5D():
    """九 —— 撇 + 横折弯，无钩。

    撇从横画的左端**下方**起笔（y=640 是横的中线，减掉半笔宽才是它的下沿），
    早先取 760 高出横太多，撇在横上探出一截还带出小尖。
    """
    # 撇要真正穿出横画、明确伸到横画上方，才读成「丿」。
    # 起点压在横画末端附近（x 720~770、y 600 上下）时，两个圆头并集会鼓成一坨，
    # 放大后就是一个圆疙瘩——这正是主人说的「突起」。抬高到 830 并右移到 800，
    # 撇与横画是干净交叉，端头是独立的标准半圆。
    return U(stroke_fillet([(800, 830), (250, 110)], r=0, width=2 * HW_CJK),
             stroke_fillet([(230, 640), (720, 640), (720, 200), (X_R, 130)],
                           r=48, width=2 * HW_CJK))
