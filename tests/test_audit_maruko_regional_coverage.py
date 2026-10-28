import tempfile
import unittest
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from tools.audit_maruko_regional_coverage import _validate_fonts, compare_region_pair


def _rectangle(width: int):
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((width, 0))
    pen.lineTo((width, 600))
    pen.lineTo((0, 600))
    pen.closePath()
    return pen.glyph()


def _make_font(path: Path, mapping: dict[int, str], widths: dict[str, int]) -> None:
    glyph_order = [".notdef", "han_a", "han_b"]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(mapping)
    builder.setupGlyf({
        ".notdef": _rectangle(500),
        "han_a": _rectangle(widths["han_a"]),
        "han_b": _rectangle(widths["han_b"]),
    })
    builder.setupHorizontalMetrics({name: (1000, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({
        "familyName": "Regional Audit Test",
        "styleName": "Regular",
        "uniqueFontIdentifier": "RegionalAuditTest",
        "fullName": "Regional Audit Test Regular",
        "psName": "RegionalAuditTest-Regular",
        "version": "Version 1.0",
    })
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)


class MarukoRegionalCoverageAuditTests(unittest.TestCase):
    def test_requires_exact_nine_region_weight_inputs(self):
        with self.assertRaisesRegex(ValueError, "need exactly"):
            _validate_fonts([("SC-Light", Path("unused.ttf"))])

    def test_compares_han_coverage_and_expanded_outline_signature(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sc_path, tc_path = root / "sc.ttf", root / "tc.ttf"
            _make_font(sc_path, {0x4E00: "han_a", 0x4E01: "han_b"}, {"han_a": 400, "han_b": 500})
            _make_font(tc_path, {0x4E00: "han_a"}, {"han_a": 600, "han_b": 500})
            result = compare_region_pair(
                {"path": sc_path, "cmap": {0x4E00: "han_a", 0x4E01: "han_b"}},
                {"path": tc_path, "cmap": {0x4E00: "han_a"}},
            )

        self.assertEqual(result["shared"], 1)
        self.assertEqual(result["only_a"], 1)
        self.assertEqual(result["only_b"], 0)
        self.assertEqual(result["outline_coordinate_diff"], 1)
        self.assertEqual(result["outline_structure_diff"], 0)


if __name__ == "__main__":
    unittest.main()
