"""Contracts for the simplified-Chinese derivation engine.

The engine's promise is narrow and checkable: every glyph it adds is composed
from contours the face already owns, every pre-existing glyph survives byte for
byte, and a weight whose drawing cannot be derived is reported instead of being
quietly given a guessed shape.
"""
import sys
import tempfile
import unittest
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import extend_font
from font_fixtures import composite_font, static_font


def write_face(directory: Path, data: bytes, name="fixture.ttf"):
    path = directory / name
    path.write_bytes(data)
    return path


class RecipeContractTests(unittest.TestCase):
    def test_every_recipe_names_a_source_that_exists(self):
        for char, parts in extend_font.RECIPES.items():
            self.assertEqual(len(char), 1, f"{char!r} is not a single character")
            self.assertTrue(parts, f"{char} has no parts")
            for source, select, shape in parts:
                self.assertIsInstance(source, str)
                self.assertTrue(callable(select) and callable(shape), f"{char}: {source}")

    def test_derived_characters_are_all_cjk_and_unique(self):
        self.assertEqual(len(extend_font.RECIPES), len(set(extend_font.RECIPES)))
        for char in extend_font.RECIPES:
            self.assertGreaterEqual(ord(char), 0x4E00)
            self.assertLessEqual(ord(char), 0x9FFF)

    def test_a_recipe_never_targets_a_character_the_face_already_draws(self):
        """The engine must not overwrite: 见 is exactly this case in Zen Maru."""
        with tempfile.TemporaryDirectory() as temp:
            path = write_face(Path(temp), static_font(family="Fixture Maru"))
            face = extend_font.Face(path)
            with self.assertRaisesRegex(ValueError, "already drawn"):
                face.add("好", [("中", extend_font.all_contours, extend_font.translate(0, 0))])


class FaceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_derived_glyph_is_composed_from_source_contours(self):
        path = write_face(self.root, static_font(family="Fixture Maru"))
        face = extend_font.Face(path)
        info = face.add("狗", [("好", extend_font.main_contour, extend_font.translate(40, 0))])
        source = extend_font.bounds([max(face.contours("好"), key=extend_font.area)])
        built = extend_font.bounds([face.pending[0][2].draw and c
                                    for c in extend_font._glyph_contours(face.pending[0][2])])
        self.assertEqual(built[0], source[0] + 40)
        self.assertEqual(built[2], source[2] + 40)
        self.assertEqual(info["advance"], 500)

    def test_original_glyphs_survive_byte_for_byte(self):
        path = write_face(self.root, static_font(family="Fixture Maru"))
        before = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)
        original = {name: before["glyf"][name].compile(before["glyf"]) for name in before.getGlyphOrder()}
        face = extend_font.Face(path)
        face.add("狗", [("好", extend_font.all_contours, extend_font.translate(0, 0))])
        output = face.save(self.root / "extended.ttf")
        after = TTFont(output, recalcBBoxes=False, recalcTimestamp=False)
        for name, compiled in original.items():
            self.assertIn(name, after.getGlyphOrder(), f"{name} disappeared")
            self.assertEqual(after["glyf"][name].compile(after["glyf"]), compiled,
                             f"{name} changed during the derivation")

    def test_cmap_only_gains_the_derived_codepoints(self):
        path = write_face(self.root, static_font(family="Fixture Maru"))
        face = extend_font.Face(path)
        face.add("狗", [("好", extend_font.all_contours, extend_font.translate(0, 0))])
        output = face.save(self.root / "extended.ttf")
        before = set(TTFont(path, lazy=True).getBestCmap())
        after = set(TTFont(output, lazy=True).getBestCmap())
        self.assertEqual(after - before, {ord("狗")})

    def test_metrics_are_copied_from_the_sources_not_invented(self):
        path = write_face(self.root, static_font(family="Fixture Maru"))
        face = extend_font.Face(path)
        info = face.add("狗", [("好", extend_font.all_contours, extend_font.translate(0, 0))])
        self.assertEqual(info["advance"], 500)
        output = face.save(self.root / "extended.ttf")
        font = TTFont(output, lazy=True)
        self.assertEqual(font["hmtx"][info["glyph"]][0], 500)
        if "vmtx" in font:
            self.assertIn(info["glyph"], font["vmtx"].metrics)

    def test_an_empty_recipe_is_refused(self):
        path = write_face(self.root, static_font(family="Fixture Maru"))
        face = extend_font.Face(path)
        with self.assertRaisesRegex(ValueError, "missing from the face"):
            face.add("狗", [("空", extend_font.main_contour, extend_font.translate(0, 0))])

    def test_a_weight_that_cannot_be_derived_is_skipped_and_reported(self):
        """Bold-like merges must be visible in the report, never guessed at."""
        path = write_face(self.root, static_font(family="Fixture Maru"))
        recipes = {"狗": [("好", extend_font.main_contour, extend_font.translate(0, 0))],
                   "猫": [("缺失字", extend_font.main_contour, extend_font.translate(0, 0))]}
        face, skipped = extend_font.extend_face(path, self.root / "out.ttf", recipes)
        self.assertEqual(sorted(skipped), ["猫"])
        self.assertIn("猫", skipped)
        self.assertEqual(sorted(face.added), ["狗"])

    def test_composite_sources_are_decomposed(self):
        """A source glyph that is a composite must still yield real contours."""
        path = write_face(self.root, composite_font(family="Fixture Maru"))
        face = extend_font.Face(path)
        info = face.add("狗", [("Á", extend_font.all_contours, extend_font.translate(0, 0))])
        self.assertEqual(info["glyph"], "uni72D7")
        self.assertEqual(len(extend_font._glyph_contours(face.pending[0][2])), 1)


class ShaperTests(unittest.TestCase):
    @staticmethod
    def _box(x0, y0, x1, y1, clockwise=False):
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if clockwise:
            corners = list(reversed(corners))
        return extend_font.Contour([("moveTo", (corners[0],)),
                                    *[("lineTo", (p,)) for p in corners[1:]],
                                    ("closePath", ())])

    def test_classify_separates_holes_from_strokes(self):
        """A slot wound the other way is a hole; a same-winding small box is a foot."""
        outer = self._box(0, 0, 100, 100)
        hole = self._box(20, 20, 80, 80, clockwise=True)
        foot = self._box(-40, -40, -20, -20)
        main, holes, strokes = extend_font.classify([outer, hole, foot])
        self.assertIs(main, outer)
        self.assertEqual(holes, [hole])
        self.assertEqual(strokes, [foot])

    def test_merged_cut_keeps_the_floor_and_drops_what_hangs_below(self):
        """A box with a foot fused into it loses the foot, not the whole box."""
        box = extend_font.Contour([("moveTo", ((0, 0),)), ("lineTo", ((60, 0),)),
                                   ("lineTo", ((60, -40),)), ("lineTo", ((100, -40),)),
                                   ("lineTo", ((100, 100),)), ("lineTo", ((0, 100),)),
                                   ("closePath", ())])
        self.assertEqual(extend_font.bounds([box])[1], -40)
        kept = extend_font.without_feet([box])
        self.assertEqual(len(kept), 1)
        self.assertEqual(extend_font.bounds([kept[0]])[1], 0,
                         "the cut should have removed the part below the floor")

    def test_a_glyph_without_a_flat_floor_is_refused(self):
        """No measurable floor means no safe cut: refuse instead of eating ink."""
        triangle = extend_font.Contour([("moveTo", ((0, 0),)), ("lineTo", ((50, 90),)),
                                        ("lineTo", ((100, 0),)), ("closePath", ())])
        with self.assertRaisesRegex(ValueError, "no floor"):
            extend_font.without_feet([triangle])

    def test_bar_over_feet_needs_the_measured_band(self):
        bar = extend_font.Contour([("moveTo", ((0, 0),)), ("lineTo", ((100, 0),)),
                                   ("lineTo", ((100, 10),)), ("lineTo", ((0, 10),)),
                                   ("closePath", ())])
        with self.assertRaisesRegex(ValueError, "feet band"):
            extend_font.bar_over_feet()([bar], {"built": [bar], "notes": {}})


if __name__ == "__main__":
    unittest.main()
