import unittest

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from tools.compose_maruko_hangul import compose_syllables, split_syllable


def _rectangle(width=300, offset=0):
    pen = TTGlyphPen(None)
    pen.moveTo((offset, 0))
    pen.lineTo((offset + width, 0))
    pen.lineTo((offset + width, 300))
    pen.lineTo((offset, 300))
    pen.closePath()
    return pen.glyph()


def _make_font(include_trailing=True, include_hangul=False):
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "leading", "vowel"]
    cmap = {0x1100: "leading", 0x1161: "vowel"}
    glyphs = {".notdef": _rectangle(), "leading": _rectangle(300), "vowel": _rectangle(250, 400)}
    if include_trailing:
        order.append("trailing")
        cmap[0x11A8] = "trailing"
        glyphs["trailing"] = _rectangle(200, 700)
    if include_hangul:
        cmap[0xAC00] = "leading"
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap(cmap)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (1000, 0) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupVerticalHeader(ascent=880, descent=-120)
    builder.setupVerticalMetrics({name: (1000, 580) for name in order})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({
        "familyName": "Maruko Hangul Test",
        "styleName": "Regular",
        "uniqueFontIdentifier": "MarukoHangulTest",
        "fullName": "Maruko Hangul Test Regular",
        "psName": "MarukoHangulTest-Regular",
        "version": "Version 1.0",
    })
    builder.setupPost()
    builder.setupMaxp()
    return builder.font


class MarukoHangulCompositionTests(unittest.TestCase):
    def test_unicode_hangul_splitting(self):
        self.assertEqual(split_syllable(0xAC00), (0x1100, 0x1161, None))
        self.assertEqual(split_syllable(0xAC01), (0x1100, 0x1161, 0x11A8))
        self.assertEqual(split_syllable(0xD7A3), (0x1112, 0x1175, 0x11C2))
        with self.assertRaises(ValueError):
            split_syllable(0xD7A4)

    def test_composes_outline_and_adds_unicode_mapping(self):
        font = _make_font()

        added = compose_syllables(font, [0xAC00, 0xAC01])

        cmap = font.getBestCmap()
        self.assertEqual(added, 2)
        self.assertEqual(cmap[0xAC00], "hangulAC00")
        self.assertEqual(cmap[0xAC01], "hangulAC01")
        self.assertEqual(len(font["glyf"]["hangulAC00"].coordinates), 8)
        self.assertEqual(len(font["glyf"]["hangulAC01"].coordinates), 12)
        self.assertEqual(font["hmtx"].metrics["hangulAC01"][0], 1000)
        self.assertEqual(font["vmtx"].metrics["hangulAC01"], (1000, 580))
        self.assertEqual(font["maxp"].numGlyphs, len(font.getGlyphOrder()))

    def test_missing_jamo_and_existing_syllable_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "lacks"):
            compose_syllables(_make_font(include_trailing=False), [0xAC01])
        font = _make_font()
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[0xAC00] = "leading"
        with self.assertRaisesRegex(ValueError, "overwrite"):
            compose_syllables(font, [0xAC00])


if __name__ == "__main__":
    unittest.main()
