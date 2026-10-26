"""Unicode 尚未分配码位的占位字形（17 个）。

为什么需要这一支
----------------
主人要求「全字符覆盖」，而 U+10EEF、U+1CED5..U+1CEDC、U+1FAC7/C9/CA/CB/DE、
U+1FAEC/ED/EE 这 17 个码位到 Unicode 18.0 仍未分配，市面上任何字库（含上游 MFGA
的 Unicode16/17/18-new）都没有标准字形。要让字体声称覆盖它们，只能自绘。

设计取向：**按所在区块的邻居定形**，不画豆腐块。
- U+1CED5..U+1CEDC 夹在炼金术符号与叠层根号之间 → 几何符号（圆/三角/方/菱 + 内线）
- U+1FAC7/C9/CA/CB 夹在人物与生物之间 → 人形
- U+1FADE 夹在腌菜与泼溅之间 → 器物
- U+1FAEC/ED/EE 夹在碎裂脸与打斗云之间 → 面部
- U+10EEF 在阿拉伯冠字母区 → 阿拉伯字母形

所有字形走同一套设计系统（HW=31 笔宽、端头半径 31 半圆、折角切线圆弧），
与 tools/design_symbols.py 的符号同一规则。
"""
from __future__ import annotations

import math

import pathops

from design_symbols import (HW, U, D, canon, circle, ring, filled_rounded_rect,
                            rect_outline, stroke_arc, stroke_fillet, stroke_line,
                            _arc_quads)

CXS, CYS = 500.0, 480.0     # 符号中心（emoji 区略高，避开基线）
R = 260.0                    # 主半径
W = 2 * HW                   # 笔宽 62


# ---------------------------------------------------------------- 炼金术区
def _ringed(inner):
    """外环 + 内在符号。"""
    return U(ring(CXS, CYS, R, W), inner)


def r_1CED5():
    """环 + 竖线：炼金术风的「油/水」变体。"""
    return _ringed(stroke_line((CXS, CYS - R + HW), (CXS, CYS + R - HW), W))


def r_1CED6():
    """环 + 横线。"""
    return _ringed(stroke_line((CXS - R + HW, CYS), (CXS + R - HW, CYS), W))


def r_1CED7():
    """环 + 十字。"""
    return _ringed(U(stroke_line((CXS, CYS - R + HW), (CXS, CYS + R - HW), W),
                     stroke_line((CXS - R + HW, CYS), (CXS + R - HW, CYS), W)))


def r_1CED8():
    """三重同心环。"""
    return U(ring(CXS, CYS, R, W), ring(CXS, CYS, R - 3 * W, W))


def _tri(up=True, half=138.0, hh=120.0):
    """环内的正/倒三角形（闭合描边，圆角）。"""
    sgn = 1 if up else -1
    return stroke_fillet([(CXS - half, CYS - sgn * hh), (CXS + half, CYS - sgn * hh),
                          (CXS, CYS + sgn * hh), (CXS - half, CYS - sgn * hh)],
                         r=24, width=W)


def r_1CED9():
    """环 + 正三角。"""
    return _ringed(_tri(True))


def r_1CEDA():
    """环 + 倒三角。"""
    return _ringed(_tri(False))


def r_1CEDB():
    """环 + 方。"""
    # 方框自己描边（rect_outline 是**填充**环，套在环里会出现双层鼓包）
    # 方框离环太近时，两个描边的圆头会并集鼓包；缩到 0.50 让内外净空 ≥ 2Hw
    s = (R - HW) * 0.50
    return _ringed(stroke_fillet([(CXS - s, CYS - s), (CXS + s, CYS - s),
                                  (CXS + s, CYS + s), (CXS - s, CYS + s),
                                  (CXS - s, CYS - s)], r=26, width=W))


def r_1CEDC():
    """环 + 菱。"""
    s = (R - HW) * 0.72
    return _ringed(stroke_fillet([(CXS, CYS + s), (CXS + s, CYS),
                                  (CXS, CYS - s), (CXS - s, CYS), (CXS, CYS + s)],
                                 r=24, width=W))


# ---------------------------------------------------------------- emoji：人物 / 器物 / 面部
def _head_shoulders(shoulder):
    """头 + 肩，人物类占位的公共骨架。"""
    head = circle(CXS, CYS + 95, 108)
    return U(head, shoulder)


def r_1FAC7():
    """人形：头 + 圆肩。

    肩的上沿必须高到和头的圆相接（CYS-5 时头底 CYS-13，差 8 单位，中间露出细颈，
    并集后读成一条斜线穿过身体）。抬到 CYS+20，两形真正重叠。
    """
    # 圆角半径不能接近高度的一半：150 时矩形的左下圆角与直边相切处会塌成一条斜线
    return _head_shoulders(filled_rounded_rect(CXS - 185, CYS - 215, CXS + 185, CYS + 60, 110))


def r_1FAC9():
    """人形：头 + 方肩。"""
    return _head_shoulders(filled_rounded_rect(CXS - 180, CYS - 220, CXS + 180, CYS + 20, 34))


def r_1FACA():
    """人形：头 + 三角身。"""
    body = pathops.Path()
    body.moveTo(CXS - 190, CYS - 215)
    body.lineTo(CXS + 190, CYS - 215)
    body.lineTo(CXS, CYS + 40)
    body.close()
    return _head_shoulders(body)


def r_1FACB():
    """双人：两个头 + 合并的肩。"""
    return U(circle(CXS - 95, CYS + 150, 92), circle(CXS + 95, CYS + 150, 92),
             filled_rounded_rect(CXS - 215, CYS - 215, CXS + 215, CYS + 90, 130))


def r_1FADE():
    """器物：圆角罐 + 内横线。"""
    return U(rect_outline(CXS - 175, CYS - 215, CXS + 175, CYS + 175, r=54),
             stroke_line((CXS - 120, CYS + 90), (CXS + 120, CYS + 90), 46),
             stroke_line((CXS - 120, CYS + 5), (CXS + 120, CYS + 5), 46))


def _face(mouth_path, eyes):
    return U(ring(CXS, CYS, R, W), eyes, mouth_path)


def _eyes_dots(dy=40):
    return U(circle(CXS - 88, CYS + dy, 34), circle(CXS + 88, CYS + dy, 34))


def _eyes_closed(dy=45):
    return U(stroke_line((CXS - 130, CYS + dy), (CXS - 46, CYS + dy), 40),
             stroke_line((CXS + 46, CYS + dy), (CXS + 130, CYS + dy), 40))


def r_1FAEC():
    """面无表情：圆脸 + 点眼 + 平嘴。"""
    return _face(stroke_line((CXS - 105, CYS - 105), (CXS + 105, CYS - 105), 46),
                 _eyes_dots())


def r_1FAED():
    """困惑：圆脸 + 点眼 + 波浪嘴。"""
    return _face(U(stroke_arc(CXS - 55, CYS - 105, 55, 200, 340, 42),
                   stroke_arc(CXS + 55, CYS - 105, 55, 200, 340, 42)),
                 _eyes_dots())


def r_1FAEE():
    """惊讶：圆脸 + 闭眼 + 张口。

    张口必须是**加墨**（实心圆）而不是挖孔：环内部本来就是空白，挖掉什么也看不见。
    """
    return _face(circle(CXS, CYS - 100, 62), _eyes_closed())


# ---------------------------------------------------------------- 阿拉伯扩展 C
def r_10EEF():
    """阿拉伯冠字母形：主干 + 下弯钩 + 上方冠符（该区块的邻居都是冠字母）。"""
    stem = stroke_fillet([(CXS + 60, CYS + 250), (CXS + 60, CYS - 60),
                          (CXS - 40, CYS - 170), (CXS - 235, CYS - 170)],
                         r=90, width=112)
    crown = U(stroke_line((CXS + 150, CYS + 330), (CXS + 150, CYS + 235), 46),
              stroke_line((CXS + 60, CYS + 330), (CXS + 60, CYS + 235), 46))
    return U(stem, crown)


# 帕尔米拉文字区的三个未分配码位（U+1095A..1095C）。Unicode17 字件里画了字形，
# 但 Unicode 本身没定义，这里也补自绘占位，保证「每个未分配码位都有确定字形」。
def r_1095A():
    """帕尔米拉风：竖干 + 右上斜臂。"""
    return U(stroke_fillet([(CXS - 90, CYS - 260), (CXS - 90, CYS + 250)], r=0, width=W),
             stroke_fillet([(CXS - 90, CYS + 40), (CXS + 190, CYS + 250)], r=40, width=W))


def r_1095B():
    """帕尔米拉风：竖干 + 左横臂 + 底横。"""
    return U(stroke_fillet([(CXS - 90, CYS - 260), (CXS - 90, CYS + 250)], r=0, width=W),
             stroke_fillet([(CXS - 90, CYS + 120), (CXS - 230, CYS + 120)], r=0, width=W),
             stroke_fillet([(CXS - 90, CYS - 190), (CXS + 190, CYS - 190)], r=0, width=W))


def r_1095C():
    """帕尔米拉风：竖干 + 顶部弧。"""
    return U(stroke_fillet([(CXS - 90, CYS - 260), (CXS - 90, CYS + 180)], r=0, width=W),
             stroke_arc(CXS - 20, CYS + 120, 160, 30, 150, W))


RESERVED = {
    0x1095A:  ("reserved.1095A", r_1095A),
    0x1095B:  ("reserved.1095B", r_1095B),
    0x1095C:  ("reserved.1095C", r_1095C),
    0x10EEF:  ("reserved.10EEF", r_10EEF),
    0x1CED5:  ("reserved.1CED5", r_1CED5),
    0x1CED6:  ("reserved.1CED6", r_1CED6),
    0x1CED7:  ("reserved.1CED7", r_1CED7),
    0x1CED8:  ("reserved.1CED8", r_1CED8),
    0x1CED9:  ("reserved.1CED9", r_1CED9),
    0x1CEDA:  ("reserved.1CEDA", r_1CEDA),
    0x1CEDB:  ("reserved.1CEDB", r_1CEDB),
    0x1CEDC:  ("reserved.1CEDC", r_1CEDC),
    0x1FAC7:  ("reserved.1FAC7", r_1FAC7),
    0x1FAC9:  ("reserved.1FAC9", r_1FAC9),
    0x1FACA:  ("reserved.1FACA", r_1FACA),
    0x1FACB:  ("reserved.1FACB", r_1FACB),
    0x1FADE:  ("reserved.1FADE", r_1FADE),
    0x1FAEC:  ("reserved.1FAEC", r_1FAEC),
    0x1FAED:  ("reserved.1FAED", r_1FAED),
    0x1FAEE:  ("reserved.1FAEE", r_1FAEE),
}


def glyphs():
    """出口：每个都过绕向规范化。"""
    return {cp: (name, (lambda fn=fn: canon(fn()))) for cp, (name, fn) in RESERVED.items()}
