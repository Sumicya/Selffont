"""Bind the platform-support single source of truth to every call site.

config/platform-support.json declares which platforms Selffont natively supports.
Kotlin (TargetPlatform.kt) and the installer (script/customize.sh) each inline
those values for their own runtime -- neither parses JSON on-device. These tests
fail if any call site drifts from the manifest, so adding a vendor or bumping the
API is a single decision enforced across languages instead of a silent mismatch.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/platform-support.json").read_text())
JAVA = (ROOT / "mfga-xposed/app/src/main/kotlin/com/mfga/xposed/TargetPlatform.kt").read_text()
CUSTOMIZE = (ROOT / "script/customize.sh").read_text()


class PlatformSupportManifestTests(unittest.TestCase):
    def test_manifest_shape(self):
        self.assertEqual(MANIFEST["api"], 36)
        self.assertTrue(MANIFEST["vendors"])
        self.assertEqual(MANIFEST["vendors"], [v.lower() for v in MANIFEST["vendors"]])
        self.assertEqual(sorted(set(MANIFEST["vendors"])), sorted(MANIFEST["vendors"]))
        self.assertTrue(MANIFEST["overrideMarker"].startswith("/"))

    def test_java_matches_manifest(self):
        self.assertIn(f"SUPPORTED_API = {MANIFEST['api']}", JAVA)
        # setOf("oplus", "oppo", ...) must equal exactly the manifest vendor set.
        match = re.search(r"VENDORS\s*=\s*setOf\(([^)]*)\)", JAVA)
        self.assertIsNotNone(match, "VENDORS setOf literal not found")
        java_vendors = re.findall(r'"([^"]+)"', match.group(1))
        self.assertEqual(sorted(java_vendors), sorted(MANIFEST["vendors"]))
        self.assertIn(f'OVERRIDE_MARKER = "{MANIFEST["overrideMarker"]}"', JAVA)

    def test_customize_matches_manifest(self):
        self.assertIn(f'"${{API:-}}" = {MANIFEST["api"]}', CUSTOMIZE)
        self.assertIn(f"OVERRIDE={MANIFEST['overrideMarker']}", CUSTOMIZE)
        # The shell case arm ("oplus|oppo|...") must list exactly the manifest vendors.
        match = re.search(r"\n\s*([a-z|]+)\)\s*oplus=1", CUSTOMIZE)
        self.assertIsNotNone(match, "vendor case arm not found")
        shell_vendors = match.group(1).split("|")
        self.assertEqual(sorted(shell_vendors), sorted(MANIFEST["vendors"]))


if __name__ == "__main__":
    unittest.main()
