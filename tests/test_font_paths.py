"""Bind every font-path call site to its single source of truth.

The installed primary filename lives in config/font-source.json (installedFile)
and the metrics carrier in tools/font_config.py (METRIC_CARRIER). On-device
shell scripts and the Kotlin runtime cannot parse those at runtime: the module
therefore carries a generated font.conf (SELFFONT_INSTALLED_FONT) written by
tools/build_module.py, the scripts read from it, and FontIdentity.kt mirrors
the manifest. These tests fail if any binding drifts, so renaming the installed
font is a config edit enforced across languages instead of a silent mismatch.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from font_config import METRIC_CARRIER

FONT = json.loads((ROOT / "config/font-source.json").read_text())
INSTALLED = FONT["installedFile"]

CUSTOMIZE = (ROOT / "script/customize.sh").read_text()
DIAGNOSE = (ROOT / "script/diagnose.sh").read_text()
DEVICE_STATE = (ROOT / "tools/device_state.sh").read_text()
IDENTITY = (ROOT / "mfga-xposed/app/src/main/kotlin/com/mfga/xposed/FontIdentity.kt").read_text()


class InstalledFontNameTests(unittest.TestCase):
    def test_manifest_shape(self):
        self.assertTrue(INSTALLED.endswith(".ttf"))
        self.assertNotIn("/", INSTALLED)

    def test_kotlin_identity_matches_manifest(self):
        self.assertIn(f'"/system/fonts/{INSTALLED}"', IDENTITY)
        self.assertIn(f'"/system/fonts/{METRIC_CARRIER}"', IDENTITY)

    def test_installer_reads_font_conf(self):
        self.assertIn('font.conf', CUSTOMIZE)
        self.assertIn('system/fonts/$SELFFONT_INSTALLED_FONT', CUSTOMIZE)

    def test_diagnose_reads_font_conf(self):
        self.assertIn('font.conf', DIAGNOSE)
        self.assertIn('/system/fonts/${SELFFONT_INSTALLED_FONT', DIAGNOSE)

    def test_device_state_reads_font_conf_and_carrier(self):
        self.assertIn('font.conf', DEVICE_STATE)
        self.assertIn('SELFFONT_INSTALLED_FONT', DEVICE_STATE)
        # The metrics carrier stays the fixed Roboto face even across swaps.
        self.assertIn(METRIC_CARRIER, DEVICE_STATE)


if __name__ == "__main__":
    unittest.main()
