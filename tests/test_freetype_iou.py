import unittest

import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from tools.freetype_iou import compare, iou, render


def _square(pen, x0, y0, x1, y1):
    pen.moveTo((x0, y0))
    pen.lineTo((x1, y0))
    pen.lineTo((x1, y1))
    pen.lineTo((x0, y1))
    pen.closePath()


def _font(path, glyphs, upm=1000):
    """写一个最小 TTF：`glyphs` 是 {字符: [矩形...]}，矩形全部同向。"""
    builder = FontBuilder(upm, isTTF=True)
    order = [".notdef"] + [f"u{ord(c):04X}" for c in glyphs]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({ord(c): f"u{ord(c):04X}" for c in glyphs})
    builder.setupGlyf({
        name: _pen_glyph(_square, rects) if rects is not None else TTGlyphPen(None).glyph()
        for name, rects in [(".notdef", None)] + [
            (f"u{ord(c):04X}", glyphs[c]) for c in glyphs
        ]
    })
    builder.setupHorizontalMetrics({name: (upm, 0) for name in order})
    builder.setupHorizontalHeader(ascent=880, descent=-120)
    builder.setupNameTable({"familyName": "T", "styleName": "R"})
    builder.setupOS2()
    builder.setupPost()
    builder.save(path)
    return path


def _pen_glyph(draw, rects):
    pen = TTGlyphPen(None)
    for rect in rects:
        draw(pen, *rect)
    return pen.glyph()


class FreeTypeRenderTests(unittest.TestCase):
    def test_same_winding_overlap_is_filled_not_punched(self):
        """FreeType 用非零环绕：两条同向重叠轮廓应当并起来。

        这正是 `hook_erase.render_glyph_object` 做错的地方——它按有向面积的正负
        填/挖，把同向重叠区挖成洞，`鬱` 因此被量成"重描后完全没变"（IoU 1.000），
        换成 FreeType 后是 0.854。回归锁在这里。
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = _font(Path(tmp, "t.ttf"), {"十": [(200, 400, 800, 600), (400, 200, 600, 800)]})
            mask = render(path, "十", size=400)
        ys, xs = np.where(mask)
        cy, cx = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
        centre = mask[cy - 2:cy + 2, cx - 2:cx + 2]
        self.assertTrue(centre.all(), "重叠加中心没有墨迹：说明渲染器按奇偶/面积挖了洞")


class IouTests(unittest.TestCase):
    def test_identical_masks(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[2:8, 2:8] = True
        self.assertEqual(iou(mask, mask), 1.0)

    def test_disjoint_masks(self):
        a = np.zeros((10, 10), dtype=bool)
        b = np.zeros((10, 10), dtype=bool)
        a[0:4, 0:4] = True
        b[6:10, 6:10] = True
        self.assertEqual(iou(a, b), 0.0)

    def test_same_font_compares_equal(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = _font(Path(tmp, "t.ttf"), {"口": [(300, 200, 700, 800)]})
            self.assertEqual(compare(path, path, "口", size=200), 1.0)
