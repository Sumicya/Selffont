"""Bind every on-device font-path call site to its single source of truth.

The installed face filenames and the visibility file live in
config/font-source.json; the module build renders them into the module's
font.conf, which the shell scripts source. Nothing else may hardcode a face name.
These tests fail if either half drifts, so a font swap (docs/font-swap.md) stays a
single edit across languages.
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from font_config import METRIC_CARRIER

MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())
INSTALLED = [face["installedFile"] for face in MANIFEST["faces"]]
VISIBILITY = MANIFEST["visibilityFile"]

CUSTOMIZE = (ROOT / "script/customize.sh").read_text()
DIAGNOSE = (ROOT / "script/diagnose.sh").read_text()
DEVICE_STATE = (ROOT / "tools/device_state.sh").read_text()
IDENTITY = (ROOT / "mfga-xposed/app/src/main/kotlin/com/mfga/xposed/FontIdentity.kt").read_text()
SHELL_SCRIPTS = [*sorted((ROOT / "script").glob("*.sh")), ROOT / "tools/device_state.sh"]

# font.conf keys the module renders, in the order build_module.py writes them.
CONF_KEYS = [f"SELFFONT_INSTALLED_{face['style'].upper()}" for face in MANIFEST["faces"]]
CONF_KEYS.append("SELFFONT_VISIBILITY_FILE")


class FontPathContractTests(unittest.TestCase):
    def test_manifest_shape(self):
        for name in INSTALLED:
            self.assertTrue(name.endswith(".ttf"))
            self.assertNotIn("/", name)
        self.assertIn(VISIBILITY, INSTALLED)

    def test_kotlin_identity_matches_manifest(self):
        for name in INSTALLED:
            self.assertIn(f'"/system/fonts/{name}"', IDENTITY)
        self.assertIn(f'"/system/fonts/{METRIC_CARRIER}"', IDENTITY)

    def test_build_renders_every_conf_key(self):
        from build_module import render_font_conf

        rendered = dict(
            line.split("=", 1) for line in render_font_conf().splitlines() if "=" in line
        )
        self.assertEqual(sorted(rendered), sorted(CONF_KEYS))
        for face in MANIFEST["faces"]:
            self.assertEqual(rendered[f"SELFFONT_INSTALLED_{face['style'].upper()}"], face["installedFile"])
        self.assertEqual(rendered["SELFFONT_VISIBILITY_FILE"], VISIBILITY)

    def test_shell_reads_conf_instead_of_hardcoding_faces(self):
        for name, text in (("customize.sh", CUSTOMIZE), ("diagnose.sh", DIAGNOSE),
                           ("device_state.sh", DEVICE_STATE)):
            self.assertIn("font.conf", text, f"{name} must source the generated font.conf")
            for face in INSTALLED:
                self.assertNotIn(face, text, f"{name} must not hardcode {face}")

    def test_conf_keys_are_not_typos(self):
        script_text = CUSTOMIZE + DIAGNOSE + DEVICE_STATE
        # These three are host-side path overrides for the read-only report, not
        # keys of the generated font.conf.
        overrides = {"SELFFONT_MODULE_ROOT", "SELFFONT_SYSTEM_ROOT", "SELFFONT_PROC_ROOT"}
        referenced = set(re.findall(r"SELFFONT_[A-Z_]+", script_text)) - overrides
        self.assertTrue(referenced)
        self.assertTrue(referenced <= set(CONF_KEYS), sorted(referenced - set(CONF_KEYS)))

    def test_no_script_carries_a_stale_family_name(self):
        for path in SHELL_SCRIPTS:
            text = path.read_text()
            self.assertNotIn("WenYuan", text, f"{path} still names the old font")
            self.assertNotIn("Rounded SC VF", text, f"{path} still names the old font")

    def test_visibility_file_is_one_of_the_installed_faces(self):
        self.assertIn(VISIBILITY, INSTALLED)


if __name__ == "__main__":
    unittest.main()
