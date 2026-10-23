import tempfile
import unittest
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from tools.audit_maruko_coverage import _snapshot, encoded_printable_codepoints


def _rectangle(width=400):
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((width, 0))
    pen.lineTo((width, 600))
    pen.lineTo((0, 600))
    pen.closePath()
    return pen.glyph()


def _make_font(path: Path):
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "space", "A", "han"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({0x20: "space", 0x41: "A", 0x4E00: "han"})
    builder.setupGlyf({
        ".notdef": _rectangle(),
        "space": TTGlyphPen(None).glyph(),
        "A": _rectangle(),
        "han": _rectangle(800),
    })
    builder.setupHorizontalMetrics({
        ".notdef": (1000, 0),
        "space": (500, 0),
        "A": (600, 0),
        "han": (1000, 0),
    })
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({
        "familyName": "Coverage Audit Test",
        "styleName": "Regular",
        "uniqueFontIdentifier": "CoverageAuditTest",
        "fullName": "Coverage Audit Test Regular",
        "psName": "CoverageAuditTest-Regular",
        "version": "Version 1.0",
    })
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)


class MarukoCoverageAuditTests(unittest.TestCase):
    def test_codec_profile_excludes_controls_and_spaces(self):
        repertoire = encoded_printable_codepoints("shift_jis")
        self.assertIn(ord("A"), repertoire)
        self.assertIn(ord("あ"), repertoire)
        self.assertNotIn(0x0000, repertoire)
        self.assertNotIn(0x0020, repertoire)
        self.assertNotIn(0xAC00, repertoire)

    def test_snapshot_counts_cmap_and_outline_anomalies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test.ttf"
            _make_font(path)
            result = _snapshot("Regular", path)

        self.assertEqual(result["family"], "Coverage Audit Test")
        self.assertEqual(result["upm"], 1000)
        self.assertEqual(set(result["cmap"]), {0x20, 0x41, 0x4E00})
        self.assertEqual(result["blocks"]["CJK Unified Ideographs"], 1)
        self.assertEqual(result["empty"], [0x20])
        self.assertEqual(result["zero_advance"], [])
        self.assertEqual(result["axes"], [])


if __name__ == "__main__":
    unittest.main()
