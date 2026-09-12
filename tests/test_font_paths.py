"""Bind every hardcoded font-path call site to its single source of truth.

The installed WenYuan filename lives in config/font-source.json (installedFile)
and the metrics carrier in tools/font_config.py (METRIC_CARRIER). On-device shell
scripts and the Kotlin runtime cannot parse those at runtime, so they inline the
names -- exactly like the platform-support gates. These tests fail if any inlined
copy drifts from the source, so renaming the installed font is a single edit
enforced across languages instead of a silent mismatch.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from font_config import METRIC_CARRIER  # noqa: E402

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

    def test_installer_checks_the_prepared_font(self):
        self.assertIn(f"system/fonts/{INSTALLED}", CUSTOMIZE)

    def test_diagnose_probes_the_installed_font(self):
        self.assertIn(f"/system/fonts/{INSTALLED}", DIAGNOSE)

    def test_device_state_reads_both_font_names(self):
        self.assertIn(INSTALLED, DEVICE_STATE)
        self.assertIn(METRIC_CARRIER, DEVICE_STATE)


if __name__ == "__main__":
    unittest.main()
