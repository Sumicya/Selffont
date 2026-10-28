import tempfile
import unittest
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from tools.restore_glyph_outlines import restore_glyph_outlines


def _rectangle(x_max: int):
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((x_max, 0))
    pen.lineTo((x_max, 200))
    pen.lineTo((0, 200))
    pen.closePath()
    return pen.glyph()


def _make_font(path: Path, a_width: int, b_width: int, a_advance: int, b_advance: int):
    builder = FontBuilder(1000, isTTF=True)
    glyph_order = [".notdef", "a", "b"]
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap({0x61: "a", 0x62: "b"})
    builder.setupGlyf({
        ".notdef": _rectangle(100),
        "a": _rectangle(a_width),
        "b": _rectangle(b_width),
    })
    builder.setupHorizontalMetrics({
        ".notdef": (500, 0),
        "a": (a_advance, 10),
        "b": (b_advance, 20),
    })
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({
        "familyName": "Outline Restore Test",
        "styleName": "Regular",
        "uniqueFontIdentifier": "OutlineRestoreTest",
        "fullName": "Outline Restore Test Regular",
        "psName": "OutlineRestoreTest-Regular",
        "version": "Version 1.0",
    })
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)


class RestoreGlyphOutlinesTests(unittest.TestCase):
    def test_restores_only_selected_outline_and_preserves_target_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.ttf"
            target_path = root / "target.ttf"
            output_path = root / "output.ttf"
            _make_font(source_path, a_width=100, b_width=200, a_advance=500, b_advance=600)
            _make_font(target_path, a_width=300, b_width=400, a_advance=700, b_advance=800)

            restored = restore_glyph_outlines(source_path, target_path, output_path, "aa")
            self.assertEqual(restored, 1)

            with TTFont(source_path) as source, TTFont(target_path) as target, TTFont(output_path) as output:
                self.assertEqual(output["glyf"]["a"].coordinates, source["glyf"]["a"].coordinates)
                self.assertEqual(output["glyf"]["b"].coordinates, target["glyf"]["b"].coordinates)
                self.assertEqual(output["hmtx"]["a"], target["hmtx"]["a"])
                self.assertEqual(output["hmtx"]["b"], target["hmtx"]["b"])
                self.assertEqual(output.getBestCmap(), target.getBestCmap())

    def test_rejects_missing_char_and_input_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.ttf"
            target_path = root / "target.ttf"
            output_path = root / "output.ttf"
            _make_font(source_path, a_width=100, b_width=200, a_advance=500, b_advance=600)
            _make_font(target_path, a_width=300, b_width=400, a_advance=700, b_advance=800)

            with self.assertRaisesRegex(ValueError, "missing cmap"):
                restore_glyph_outlines(source_path, target_path, output_path, "c")
            with self.assertRaisesRegex(ValueError, "must not overwrite"):
                restore_glyph_outlines(source_path, target_path, target_path, "a")


if __name__ == "__main__":
    unittest.main()
