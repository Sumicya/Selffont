"""Contracts for borrowing outlines from a pinned reference font.

Zen Maru drew about half of GB2312, so the rest is imported from a reference
that is pinned by identity and SHA-256, licensed in the repository, and recorded
per glyph. These tests hold that line: an unpinned file is refused, a borrowed
glyph never displaces a glyph this project drew itself, the borrowed weight
follows the face's weight, and an offset that would turn a contour inside out,
collapse it, or throw it across the canvas backs off instead of shipping.
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import extend_font
import reference_font

# Characters both fixtures draw, so the weight comparison has something to
# measure: every one of these is in reference_font.PROBE.
SHARED = "一丁七万丈三上下"


def bar_font(characters=SHARED, weight=120, family="Reference Fixture"):
    """A tiny face whose characters are plain bars of a known weight."""
    order = [".notdef", "space", *(f"uni{ord(char):04X}" for char in characters)]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: "space", **{ord(char): f"uni{ord(char):04X}" for char in characters}})
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "space": TTGlyphPen(None).glyph()}
    for name in order[2:]:
        pen = TTGlyphPen(None)
        pen.moveTo((100, 400))
        pen.lineTo((900, 400))
        pen.lineTo((900, 400 + weight))
        pen.lineTo((100, 400 + weight))
        pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(dict.fromkeys(order, (1000, 0)))
    builder.setupHorizontalHeader(ascent=880, descent=-120)
    builder.setupNameTable({"familyName": family, "styleName": "Regular",
                            "uniqueFontIdentifier": family, "fullName": family,
                            "psName": family.replace(" ", "")})
    builder.setupOS2(sTypoAscender=880, sTypoDescender=-120, usWinAscent=880, usWinDescent=120)
    builder.setupPost()
    out = io.BytesIO()
    builder.save(out)
    return out.getvalue()


class PinningContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.reference = self.root / "reference.ttf"
        self.reference.write_bytes(bar_font())
        self.entry = {
            "id": "fixture",
            "file": self.reference.name,
            "bytes": self.reference.stat().st_size,
            "sha256": "0" * 64,
            "license": "OFL-1.1",
            "reservedFontNames": ["Fixture"],
        }
        saved = reference_font.REFERENCES
        reference_font.REFERENCES = {"fixture": self.entry}
        self.addCleanup(setattr, reference_font, "REFERENCES", saved)

    def test_a_file_whose_sha256_does_not_match_the_pin_is_refused(self):
        with self.assertRaises(reference_font.UnpinnedReference):
            reference_font.load("fixture", self.root)

    def test_a_file_whose_size_does_not_match_the_pin_is_refused(self):
        self.reference.write_bytes(bar_font() + b"\0")
        self.entry["sha256"] = hashlib.sha256(self.reference.read_bytes()).hexdigest()
        with self.assertRaises(reference_font.UnpinnedReference):
            reference_font.load("fixture", self.root)

    def test_an_undeclared_reference_is_refused(self):
        with self.assertRaises(reference_font.UnpinnedReference):
            reference_font.load("something-else", self.root)

    def test_a_missing_file_is_refused(self):
        self.reference.unlink()
        with self.assertRaises(reference_font.UnpinnedReference):
            reference_font.load("fixture", self.root)

    def test_the_pinned_file_loads(self):
        self.entry["sha256"] = hashlib.sha256(self.reference.read_bytes()).hexdigest()
        with reference_font.load("fixture", self.root)[0] as font:
            self.assertEqual(reference_font.load("fixture", self.root)[1]["id"], "fixture")
            self.assertIn(ord("一"), font.getBestCmap())

    def test_the_repository_manifest_pins_every_reference_it_ships(self):
        manifest = json.loads((ROOT / "config/reference-sources.json").read_text())
        self.assertTrue(manifest["references"])
        for entry in manifest["references"]:
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(entry["license"], "OFL-1.1")
            self.assertTrue(entry["reservedFontNames"])
            # The licence has to travel with the repository, not with the URL.
            self.assertTrue((ROOT / "licenses" / entry["licenseFile"]).is_file())


class BorrowingContractTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.face_path = self.root / "face.ttf"
        # The face deliberately lacks 一, so a recipe can claim it first.
        self.face_path.write_bytes(bar_font("丁七万丈三上下好", weight=60))
        self.reference = TTFont(io.BytesIO(bar_font(f"{SHARED}二乙")), lazy=True)
        self.addCleanup(self.reference.close)

    def face(self):
        return extend_font.Face(self.face_path)

    def reference_entry(self):
        return (self.reference, {"id": "fixture", "license": "OFL-1.1"})

    def test_a_borrowed_glyph_lands_at_the_weight_the_face_asks_for(self):
        for ratio in (0.6, 1.0, 1.5):
            with self.subTest(ratio=ratio):
                source = extend_font.contours_of(self.reference, "uni4E00")
                thickness = reference_font.contour_thickness(source)
                shaped, _delta, backoff = extend_font.match_thickness(
                    source, thickness * ratio, thickness * (ratio - 1) / 2,
                    reference_font.offset_matrix_free)
                self.assertEqual(backoff, 1.0)
                achieved = reference_font.contour_thickness(shaped)
                self.assertAlmostEqual(achieved, thickness * ratio, delta=thickness * 0.08)
                if ratio > 1:
                    self.assertGreater(achieved, thickness)
                elif ratio < 1:
                    self.assertLess(achieved, thickness)

    def test_a_borrowed_character_never_displaces_a_derived_one(self):
        # 一 is drawn by a recipe below; a charset that also lists it must not
        # produce a second, imported glyph for the same codepoint.
        recipes = {"一": [("丁", extend_font.all_contours, extend_font.translate(0, -300))]}
        face, skipped, borrowed = extend_font.extend_face(
            self.face_path, self.root / "out.ttf", recipes,
            reference=self.reference_entry(), charset={"一", "二"})
        self.assertEqual(skipped, {})
        self.assertEqual(borrowed, 1)  # 二 is borrowed, 一 is not
        self.assertNotIn("origin", face.added["一"])
        self.assertEqual(face.added["一"]["glyph"], "uni4E00")
        self.assertEqual(face.added["二"]["origin"], "reference")

    def test_only_characters_the_face_lacks_are_borrowed(self):
        face, skipped, borrowed = extend_font.extend_face(
            self.face_path, self.root / "out.ttf", {},
            reference=self.reference_entry(), charset={"丁", "好", "二", "乙", "甲"})
        self.assertEqual(borrowed, 2)  # 二 and 乙
        self.assertEqual(skipped, {"甲": "甲: the reference font has no glyph for it"})
        self.assertEqual(set(face.added), {"二", "乙"})
        self.assertEqual(face.added["乙"]["glyph"], "uni4E59")

    def test_the_report_says_where_every_borrowed_glyph_came_from(self):
        face, _skipped, borrowed = extend_font.extend_face(
            self.face_path, self.root / "out.ttf", {},
            reference=self.reference_entry(), charset={"二"})
        self.assertEqual(borrowed, 1)
        info = face.added["二"]
        self.assertEqual(info["origin"], "reference")
        self.assertEqual(info["sourceGlyph"], "uni4E8C")
        self.assertTrue(info["sources"][0].startswith("reference:"))
        thickness = reference_font.contour_thickness(
            extend_font.contours_of(self.reference, "uni4E8C"))
        with TTFont(self.face_path) as face_font:
            ratio = reference_font.shared_stroke_ratio(face_font, self.reference)
        self.assertLess(ratio, 1.0)  # the face is lighter than the reference
        self.assertAlmostEqual(info["targetThickness"], round(thickness * ratio, 1), delta=0.2)
        self.assertLess(info["offset"], 0.0)
        self.assertEqual(info["thickness"][0], round(thickness, 1))

    def test_an_offset_that_would_invert_or_collapse_a_contour_backs_off(self):
        # The bar is 120 units thick: thinning it by more than half turns the
        # short sides inside out, which is exactly when the back-off must fire.
        bar = extend_font.contours_of(self.reference, "uni4E00")
        moved, scale = extend_font.apply_offset(bar, -80, reference_font.offset_matrix_free)
        self.assertLess(scale, 1.0)
        self.assertEqual(extend_font._winding(moved[0]), extend_font._winding(bar[0]))
        self.assertGreater(reference_font.contour_thickness(moved), 1.0)
        # A convex outline takes the whole offset without complaint.
        box = extend_font.Contour([
            ("moveTo", ((100, 100),)), ("lineTo", ((900, 100),)),
            ("lineTo", ((900, 900),)), ("lineTo", ((100, 900),)), ("closePath", ())])
        self.assertEqual(extend_font.offset_contour(box, 50, reference_font.offset_matrix_free)[1], 1.0)

    def test_an_acute_corner_cannot_throw_a_point_across_the_canvas(self):
        spike = extend_font.Contour([
            ("moveTo", ((0, 0),)), ("lineTo", ((1000, 0),)), ("lineTo", ((1000, 20),)),
            ("lineTo", ((0, 4),)), ("closePath", ())])
        for delta in (-200, 200):
            moved = reference_font.offset_matrix_free([spike], delta)[0]
            points = [point for point in moved.points() if point]
            reach = reference_font.MITER_LIMIT * abs(delta)
            self.assertLessEqual(max(p[0] for p in points), 1000 + reach)
            self.assertLessEqual(abs(min(p[1] for p in points)), reach)

    def test_an_outline_that_runs_away_is_rejected(self):
        face = self.face()
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((extend_font.LIMIT + 1, 0))
        pen.lineTo((extend_font.LIMIT + 1, 400))
        pen.closePath()
        with self.assertRaises(ValueError):
            face.register("彐", pen.glyph(), ["fixture"])

    def test_a_borrowed_outline_is_written_to_the_font_and_verified(self):
        _face, _skipped, _borrowed = extend_font.extend_face(
            self.face_path, self.root / "out.ttf", {},
            reference=self.reference_entry(), charset={"二"})
        self.assertTrue((self.root / "out.ttf").is_file())
        with TTFont(self.root / "out.ttf") as after:
            self.assertEqual(after.getBestCmap()[ord("二")], "uni4E8C")
            # The advance comes from the reference glyph, not from a guess.
            self.assertEqual(after["hmtx"]["uni4E8C"][0], self.reference["hmtx"]["uni4E8C"][0])
            self.assertLessEqual(len(after.getGlyphOrder()), 40)

    def test_gb2312_set_is_generated_not_guessed(self):
        characters = extend_font.gb2312_characters()
        self.assertEqual(len(characters), 6763)
        for char in "员维见贝马鸟":
            self.assertIn(char, characters)


if __name__ == "__main__":
    unittest.main()
