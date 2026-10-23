import unittest

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from tools.curve_simplify import process_font, unique_mapped_chars


def _rectangle(width=400):
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((width, 0))
    pen.lineTo((width, 600))
    pen.lineTo((0, 600))
    pen.closePath()
    return pen.glyph()


def _wavy_shape():
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((400, 0))
    pen.lineTo((400, 260))
    for point in ((350, 262), (300, 258), (250, 263), (200, 259), (150, 262), (100, 258), (50, 261)):
        pen.lineTo(point)
    pen.closePath()
    return pen.glyph()


def _make_font():
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "space", "han"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({0x20: "space", 0x4E00: "han", 0x4E01: "han"})
    builder.setupGlyf({
        ".notdef": _rectangle(),
        "space": TTGlyphPen(None).glyph(),
        "han": _rectangle(800),
    })
    builder.setupHorizontalMetrics({".notdef": (1000, 0), "space": (500, 0), "han": (1000, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({
        "familyName": "Curve Simplify Test",
        "styleName": "Regular",
        "uniqueFontIdentifier": "CurveSimplifyTest",
        "fullName": "Curve Simplify Test Regular",
        "psName": "CurveSimplifyTest-Regular",
        "version": "Version 1.0",
    })
    builder.setupPost()
    builder.setupMaxp()
    return builder.font


def _make_composite_font():
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "space", "base", "composite"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({0x20: "space", 0x4E00: "base", 0x4E01: "composite"})
    composite_pen = TTGlyphPen(set(order))
    composite_pen.addComponent("base", (1, 0, 0, 1, 100, 20))
    builder.setupGlyf({
        ".notdef": _rectangle(),
        "space": TTGlyphPen(None).glyph(),
        "base": _wavy_shape(),
        "composite": composite_pen.glyph(),
    })
    metrics = {name: (1000, 0) for name in order}
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({
        "familyName": "Curve Composite Test",
        "styleName": "Regular",
        "uniqueFontIdentifier": "CurveCompositeTest",
        "fullName": "Curve Composite Test Regular",
        "psName": "CurveCompositeTest-Regular",
        "version": "Version 1.0",
    })
    builder.setupPost()
    builder.setupMaxp()
    return builder.font


class CurveSimplifyTests(unittest.TestCase):
    def test_all_mapped_selection_deduplicates_glyph_aliases(self):
        font = _make_font()
        chars = unique_mapped_chars(font)

        self.assertEqual(chars, [" ", "一"])

    def test_processing_aliases_changes_each_unique_glyph_once(self):
        font = _make_font()
        original_metrics = font["hmtx"].metrics["han"]

        report = process_font(font, ["一", "丁"], tolerance=4.0, seg_len=1.5)

        self.assertEqual(len(report), 1)
        self.assertEqual(report[0][1], "han")
        self.assertEqual(font["hmtx"].metrics["han"], original_metrics)
        self.assertIn(" -> ", report[0][2])

    def test_composite_geometry_uses_immutable_source_not_prior_output(self):
        expected_source = _make_composite_font()
        expected_output = _make_composite_font()
        process_font(
            expected_output, ["丁"], tolerance=1.0, seg_len=1.0,
            source_font=expected_source,
        )

        ordered_source = _make_composite_font()
        ordered_output = _make_composite_font()
        source_base_before = list(ordered_source["glyf"]["base"].coordinates)
        process_font(
            ordered_output, ["一", "丁"], tolerance=1.0, seg_len=1.0,
            source_font=ordered_source,
        )

        expected_coords, expected_ends, _ = expected_output["glyf"]["composite"].getCoordinates(
            expected_output["glyf"]
        )
        actual_coords, actual_ends, _ = ordered_output["glyf"]["composite"].getCoordinates(
            ordered_output["glyf"]
        )
        self.assertEqual(list(actual_coords), list(expected_coords))
        self.assertEqual(list(actual_ends), list(expected_ends))
        self.assertEqual(list(ordered_source["glyf"]["base"].coordinates), source_base_before)
        self.assertFalse(ordered_output["glyf"]["composite"].isComposite())


if __name__ == "__main__":
    unittest.main()
