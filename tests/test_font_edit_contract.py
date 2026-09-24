"""Safety contracts for the only glyph editor in the project.

The editor may reshape an explicitly named glyph, but it must never turn into a
bulk rewriter: no charset mode, no inferred strokes from a photo, no touching a
glyph that is not named. These checks drive the real code with a tiny fixture
face, then assert the shipped promise -- only the named glyphs differ.
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import prepare_font
from edit_font import (
    PatchError,
    apply_glyphs,
    apply_patch_dir,
    characters_for,
    component_users,
    load_patch,
    verify_only_targets_changed,
)
from font_fixtures import composite_font, static_font

FACE = {
    "weight": 400,
    "style": "Regular",
    "file": "fixture-Regular.ttf",
    "installedFile": "SelffontMaru-Regular.ttf",
    "bytes": 0,
    "sha256": "",
}


def fixture_face(family="Selffont Maru"):
    data = static_font(family=family, weight=400)
    return data, dict(FACE, bytes=len(data), sha256=__import__("hashlib").sha256(data).hexdigest())


def patch_file(temp: Path, face: dict, glyphs: dict) -> Path:
    path = temp / "Regular.json"
    path.write_text(json.dumps({"faceSha256": face["sha256"], "glyphs": glyphs}, ensure_ascii=False))
    return path


class EditContractTests(unittest.TestCase):
    def test_only_named_glyphs_move_and_topology_is_kept(self):
        data, face = fixture_face()
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source = temp / "prepared.ttf"
            source.write_bytes(data)
            output = temp / "patched.ttf"
            from edit_font import apply_patch

            before = TTFont(io.BytesIO(data))
            glyph = before["glyf"]["A"]
            glyph.expand(before["glyf"])
            points = len(glyph.coordinates)
            contours = tuple(glyph.endPtsOfContours)

            result = apply_patch(
                source, patch_file(temp, face, {"A": {"points": [{"index": 0, "dx": 5, "dy": -3}]}}),
                output, face,
            )
            after = TTFont(output)
            patched = after["glyf"]["A"]
            patched.expand(after["glyf"])
            self.assertEqual(len(patched.coordinates), points)
            self.assertEqual(tuple(patched.endPtsOfContours), contours)
            self.assertEqual(sorted(result["changedGlyphs"]), ["A"])
            self.assertEqual(result["outputSha256"], __import__("hashlib").sha256(output.read_bytes()).hexdigest())
            # The untouched glyphs stay byte-identical.
            verify_only_targets_changed(data, output.read_bytes(), ["A"])

    def test_refuses_patch_for_a_character_the_face_lacks(self):
        data, _ = fixture_face()
        font = TTFont(io.BytesIO(data))
        with self.assertRaisesRegex(PatchError, "no cmap entry"):
            apply_glyphs(font, {"马": {"points": [{"index": 0, "dx": 1}]}})

    def test_refuses_a_patch_bound_to_another_face(self):
        _, face = fixture_face()
        with tempfile.TemporaryDirectory() as temp:
            path = patch_file(Path(temp), dict(face, sha256="0" * 64), {"A": {"points": [{"index": 0, "dx": 1}]}})
            with self.assertRaisesRegex(PatchError, "faceSha256"):
                load_patch(path, face)

    def test_refuses_empty_duplicate_and_mixed_edits(self):
        data, _ = fixture_face()
        font = TTFont(io.BytesIO(data))
        for glyphs, message in (
            ({"A": {"points": []}}, "not a change"),
            ({"A": {"points": [{"index": 0, "dx": 1}, {"index": 0, "dy": 1}]}}, "more than once"),
            ({"A": {"points": [{"index": 0, "dx": 1, "x": 2}]}}, "mix relative and absolute"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(PatchError, message):
                apply_glyphs(font, glyphs)

    def test_a_patch_that_does_not_move_anything_is_refused(self):
        data, _ = fixture_face()
        font = TTFont(io.BytesIO(data))
        with self.assertRaisesRegex(PatchError, "does not change the outline"):
            apply_glyphs(font, {"A": {"points": [{"index": 0, "dx": 0, "dy": 0}]}})

    def test_component_borrowers_are_reported_not_hidden(self):
        font = TTFont(io.BytesIO(composite_font()))
        self.assertEqual(component_users(font, ["A"]), {"A": ["Aacute"]})
        self.assertEqual(component_users(font, ["space"]), {})
        self.assertEqual(characters_for(font, ["Aacute"]), {"Aacute": "\u00c1"})
        with self.assertRaisesRegex(PatchError, "composite"):
            apply_glyphs(TTFont(io.BytesIO(composite_font())), {"\u00c1": {"points": [{"index": 0, "dx": 1}]}})

    def test_patch_directory_applies_per_face_and_copies_the_rest(self):
        manifest_face = prepare_font.FACES[1]
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            prepared, patched, patches = temp / "prepared", temp / "patched", temp / "patches"
            prepared.mkdir()
            patches.mkdir()
            data = static_font(family=prepare_font.MANIFEST["family"], weight=manifest_face["weight"])
            for face_spec in prepare_font.FACES:
                (prepared / face_spec["installedFile"]).write_bytes(data)
            (patches / f"{manifest_face['style']}.json").write_text(
                json.dumps(
                    {
                        "faceSha256": manifest_face["sha256"],
                        "glyphs": {"A": {"points": [{"index": 0, "dx": 4, "dy": 0}]}},
                    }
                )
            )
            results = apply_patch_dir(prepared, patched, patches)
            changed = [sorted(r["changedGlyphs"]) for r in results if r["changedGlyphs"]]
            self.assertEqual(changed, [["A"]])
            for face_spec in prepare_font.FACES:
                target = patched / face_spec["installedFile"]
                self.assertTrue(target.is_file(), face_spec["installedFile"])
                if face_spec["style"] != manifest_face["style"]:
                    self.assertEqual(target.read_bytes(), (prepared / face_spec["installedFile"]).read_bytes())

    def test_the_cli_surface_stays_explicit(self):
        """A charset/range switch is how the old bulk rewriter got in."""
        import re

        source = (ROOT / "tools/edit_font.py").read_text()
        switches = set(re.findall(r'add_argument\("(--[a-z-]+)"', source))
        self.assertEqual(switches, {"--prepared", "--patches", "--output", "--report"})
        code = source.split('"""', 2)[-1]
        for forbidden in ("gb2312", "GB2312", "charset", "smooth_strokes", "round_terminals"):
            self.assertNotIn(forbidden, code, f"bulk/opaque mode came back: {forbidden}")


class AuditContractTests(unittest.TestCase):
    def test_audit_separates_editable_from_missing(self):
        from glyph_audit import MANIFEST as TARGET_MANIFEST  # noqa: F401
        from glyph_audit import audit

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            for face_spec in prepare_font.FACES:
                (temp / face_spec["installedFile"]).write_bytes(
                    static_font(family=prepare_font.MANIFEST["family"], weight=face_spec["weight"])
                )
            report = audit(temp, {"textCharacters": ["A", "马"], "radicalStudies": ["扌"]})
            self.assertEqual(report["editable"], ["A"])
            self.assertEqual(report["needsNewGlyph"], ["马"])
            self.assertEqual(report["radicalStudies"][0]["faces"], [])

    def test_targets_file_is_honest_about_radicals(self):
        targets = json.loads((ROOT / "config/glyph-targets.json").read_text())
        self.assertTrue(targets["textCharacters"])
        self.assertTrue(targets["radicalStudies"])
        self.assertTrue(targets["strokeRules"])
        # Radicals are stroke studies; they must never be counted as text coverage.
        self.assertFalse(set(targets["textCharacters"]) & set(targets["radicalStudies"]))


if __name__ == "__main__":
    unittest.main()
