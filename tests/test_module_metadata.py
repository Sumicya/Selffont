"""Bind the rendered module.prop to config/module.json (single source of truth).

tools/build_module.py renders module.prop from config/module.json rather than a
hardcoded string, so bumping the module release is a one-file edit. These tests
fail if the renderer drifts from the config or emits a malformed module.prop.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_module import MODULE, MODULE_PROP_KEYS, render_module_prop

MANIFEST = json.loads((ROOT / "config/module.json").read_text())


class ModuleMetadataTests(unittest.TestCase):
    def test_rendered_prop_matches_manifest(self):
        rendered = render_module_prop()
        lines = rendered.splitlines()
        # Every declared key appears exactly once, in the fixed order, with its value.
        self.assertEqual(lines, [f"{key}={MANIFEST[key]}" for key in MODULE_PROP_KEYS])
        self.assertTrue(rendered.endswith("\n"))

    def test_required_ksu_fields_present(self):
        # KSU/Magisk need at least these to install and display the module.
        for key in ("id", "name", "version", "versionCode"):
            self.assertIn(key, MANIFEST)
            self.assertTrue(str(MANIFEST[key]).strip())
        self.assertEqual(MANIFEST["id"], "MFGA")

    def test_missing_field_is_rejected(self):
        broken = dict(MODULE)
        del broken["versionCode"]
        with self.assertRaisesRegex(ValueError, "missing required keys"):
            render_module_prop(broken)

    def test_multiline_field_is_rejected(self):
        broken = dict(MODULE, description="line one\nline two")
        with self.assertRaisesRegex(ValueError, "single-line"):
            render_module_prop(broken)


if __name__ == "__main__":
    unittest.main()
