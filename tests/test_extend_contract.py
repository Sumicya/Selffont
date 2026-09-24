"""Contracts for the simplified-Chinese derivation engine.

The engine's promise is narrow and checkable: every glyph it adds is composed
from contours the face already owns, every pre-existing glyph survives byte for
byte, and a weight whose drawing cannot be derived is reported instead of being
quietly given a guessed shape.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import edit_font
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


class WindingTests(unittest.TestCase):
    """Mirroring reverses winding; a frame with holes must survive that."""

    @staticmethod
    def _box(x0, y0, x1, y1, reversed_=False):
        """A box wound the way this face winds outlines (negative signed area)."""
        corners = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if reversed_:
            corners = list(reversed(corners))
        return extend_font.Contour([("moveTo", (corners[0],)),
                                    *[("lineTo", (p,)) for p in corners[1:]],
                                    ("closePath", ())])

    def test_reversed_flips_the_signed_area(self):
        box = self._box(0, 0, 100, 100)
        self.assertLess(extend_font.signed_area(box), 0)
        self.assertGreater(extend_font.signed_area(box.reversed()), 0)
        self.assertEqual(extend_font.bounds([box.reversed()]), extend_font.bounds([box]))

    def test_reversed_keeps_curves_and_their_endpoints(self):
        curve = extend_font.Contour([("moveTo", ((0, 0),)), ("qCurveTo", ((50, 100), (100, 0))),
                                     ("lineTo", ((50, -20),)), ("closePath", ())])
        back = curve.reversed()
        self.assertEqual(extend_font.bounds([back]), extend_font.bounds([curve]))
        self.assertEqual([op for op, _ in back.commands],
                         ["moveTo", "lineTo", "qCurveTo", "closePath"])

    def test_frame_mirrors_without_turning_holes_into_ink(self):
        outer = self._box(600, 0, 900, 500)
        hole = self._box(650, 100, 850, 400, reversed_=True)
        built = extend_font.frame()([outer, hole], {"built": [], "notes": {}})
        self.assertEqual(len(built), 4)
        mirrored_outer, mirrored_hole = built[2], built[3]
        self.assertLess(extend_font.signed_area(mirrored_outer), 0)
        self.assertGreater(extend_font.signed_area(mirrored_hole), 0)
        self.assertEqual(len(extend_font.classify(built)[1]), 2)

    def test_frame_moves_the_half_onto_the_centre_line(self):
        outer = self._box(600, 0, 900, 500)
        built = extend_font.frame(axis=500)([outer], {"built": [], "notes": {}})
        x0, _, x1, _ = extend_font.bounds(built)
        self.assertEqual((x0 + x1) / 2, 500)
        self.assertEqual(extend_font.bounds([built[0]])[0], 500,
                         "the half handed over should end up touching the centre line")


class SelectorTests(unittest.TestCase):
    """Selectors name roles, so a weight that fused them must come back empty."""

    @staticmethod
    def _box(x0, y0, x1, y1, reversed_=False):
        corners = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if reversed_:
            corners = list(reversed(corners))
        return extend_font.Contour([("moveTo", (corners[0],)),
                                    *[("lineTo", (p,)) for p in corners[1:]],
                                    ("closePath", ())])

    def setUp(self):
        # A compound character: a full-height radical on the left (with its slot
        # and the little top bar of 戶), and a body on the right.
        self.radical = self._box(40, -80, 400, 840)
        self.slot = self._box(150, 300, 300, 600, reversed_=True)
        self.top_bar = self._box(60, 700, 450, 760)
        self.body = self._box(460, -80, 960, 840)
        self.compound = [self.radical, self.slot, self.top_bar, self.body]

    def test_the_radical_is_the_whole_side_of_the_character(self):
        picked = extend_font.left_radical(self.compound)
        self.assertEqual(len(picked), 3, "the radical's slot and top bar come with it")
        self.assertIn(self.slot, picked)
        self.assertIn(self.top_bar, picked)
        self.assertNotIn(self.body, picked)

    def test_a_fragment_beside_the_centre_line_is_not_a_radical(self):
        """陳's 阝 is fused into the body in the heavy weights: only a slot is left."""
        fused = [self.body, self._box(150, 300, 300, 600, reversed_=True)]
        self.assertEqual(extend_font.left_radical(fused), [])
        self.assertEqual(len(extend_font.left_half(fused)), 1,
                         "left_half still sees the fragment; left_radical must not")

    def test_rightmost_and_leftmost_name_the_two_feet(self):
        left, middle, right = (self._box(40, 0, 200, 300), self._box(430, -60, 540, 800),
                               self._box(700, 0, 900, 300))
        feet = [left, middle, right]
        self.assertIs(extend_font.leftmost(feet)[0], left)
        self.assertIs(extend_font.rightmost(feet)[0], right)

    def test_flip_x_mirrors_in_place_and_keeps_the_winding(self):
        dot = extend_font.Contour([("moveTo", ((100, 0),)), ("lineTo", ((160, 0),)),
                                   ("lineTo", ((220, 400),)), ("closePath", ())])
        before = extend_font.bounds([dot])
        flipped = extend_font.flip_x()([dot], {"built": [], "notes": {}})[0]
        self.assertEqual(extend_font.bounds([flipped]), before, "it mirrors in place")
        self.assertEqual(extend_font.signed_area(flipped), extend_font.signed_area(dot),
                         "a mirrored outline must stay an outline, so the winding is restored")
        points = list(flipped.points())
        self.assertEqual(max(p[0] for p in points) - min(p[0] for p in points), 120)

    def test_a_selection_that_must_not_be_empty_is_refused(self):
        """A missing radical is half a character, not an empty detail."""
        with tempfile.TemporaryDirectory() as temp:
            path = write_face(Path(temp), static_font(family="Fixture Maru"))
            face = extend_font.Face(path)
            # 中 in the fixture is a single box, so it has no "everything but the body".
            with self.assertRaisesRegex(ValueError, "except_highest.*cannot be proved"):
                face.add("户", [("中", extend_font.except_highest, extend_font.translate(0, 0))])
            face.add("户", [("中", extend_font.everything_but_main, extend_font.translate(0, 0)),
                            ("体", extend_font.all_contours, extend_font.translate(0, 0))])
            self.assertIn("户", face.added)


class ChainTests(unittest.TestCase):
    def test_edit_defaults_to_the_extended_faces(self):
        """The hand patches run after the extension, so the default must say so."""
        parser = edit_font.build_parser()
        self.assertEqual(Path(parser.get_default("prepared")).name, "fonts-simplified")
        self.assertEqual(Path(parser.get_default("output")).name, "fonts-patched")

    def test_editing_a_derived_face_is_announced(self):
        with tempfile.TemporaryDirectory() as temp:
            path = write_face(Path(temp), static_font(family="Fixture Maru"))
            face = {"style": "Regular", "file": "ZenMaruGothic-Regular.ttf",
                    "sha256": "0" * 64}
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                edit_font._warn_if_derived(path, face)
            self.assertIn("derived face", stderr.getvalue())
            quiet = io.StringIO()
            with contextlib.redirect_stderr(quiet):
                edit_font._warn_if_derived(path, dict(face, sha256=edit_font.sha256(path)))
            self.assertNotIn("derived face", quiet.getvalue())


class ShaperTests(unittest.TestCase):
    @staticmethod
    def _box(x0, y0, x1, y1, reversed_=False):
        corners = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if reversed_:
            corners = list(reversed(corners))
        return extend_font.Contour([("moveTo", (corners[0],)),
                                    *[("lineTo", (p,)) for p in corners[1:]],
                                    ("closePath", ())])

    def test_classify_separates_holes_from_strokes(self):
        """A slot wound the other way is a hole; a same-winding small box is a foot."""
        outer = self._box(0, 0, 100, 100)
        hole = self._box(20, 20, 80, 80, reversed_=True)
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
