"""The install-time platform gate blocks untested platforms by default, but an
explicit user opt-in marker lets an advanced user force installation."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CustomizeOverrideTests(unittest.TestCase):
    def run_customize(self, *, api, ksu, brand, manufacturer, override):
        """Source customize.sh with KernelSU helpers stubbed; return (rc, output)."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binaries = root / "bin"
            modpath = root / "mod"
            override_dir = root / "adb"
            (modpath / "system/fonts").mkdir(parents=True)
            binaries.mkdir()
            override_dir.mkdir()
            # A non-empty prepared font so the later font check passes.
            (modpath / "system/fonts/Selffont-WenYuanRoundedSCVF.ttf").write_bytes(b"font")
            # Stub getprop to return the requested identity.
            (binaries / "getprop").write_text(
                "#!/bin/sh\n"
                f'case "$1" in\n'
                f'  ro.product.brand) echo "{brand}";;\n'
                f'  ro.product.manufacturer) echo "{manufacturer}";;\n'
                f"  *) echo '';;\n"
                f"esac\n"
            )
            (binaries / "getprop").chmod(0o755)
            marker = override_dir / "selffont_allow_unsupported"
            if override:
                marker.write_text("")
            # Harness: define abort/ui_print, set installer vars, neutralise the
            # font-XML sourcing, and point the override path at our temp marker.
            harness = textwrap.dedent(f"""
                abort() {{ echo "ABORT: $*"; exit 1; }}
                ui_print() {{ echo "UI: $*"; }}
                API={api}
                KSU={ksu}
                MODPATH="{modpath}"
                # Redirect the hard-coded override path and the XML sourcing.
                sed -e 's#/data/adb/selffont_allow_unsupported#{marker}#g' \\
                    -e 's#\\. "$MODPATH/search_dirs.sh".*#true#' \\
                    "{ROOT}/script/customize.sh" > "{root}/customize_patched.sh"
                . "{root}/customize_patched.sh"
            """)
            script = root / "harness.sh"
            script.write_text(harness)
            env = dict(os.environ, PATH=str(binaries) + ":" + os.environ["PATH"])
            result = subprocess.run(["sh", str(script)], env=env, text=True,
                                    capture_output=True)
            return result.returncode, result.stdout + result.stderr

    def test_supported_platform_installs(self):
        rc, out = self.run_customize(api=36, ksu="true", brand="OnePlus",
                                     manufacturer="OPLUS", override=False)
        self.assertEqual(rc, 0, out)

    def test_wrong_api_aborts_without_override(self):
        rc, out = self.run_customize(api=35, ksu="true", brand="OnePlus",
                                     manufacturer="OPLUS", override=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("Android 16", out)

    def test_non_oplus_aborts_without_override(self):
        rc, out = self.run_customize(api=36, ksu="true", brand="google",
                                     manufacturer="google", override=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("Oplus", out)

    def test_override_bypasses_all_gates(self):
        rc, out = self.run_customize(api=35, ksu="false", brand="google",
                                     manufacturer="google", override=True)
        self.assertEqual(rc, 0, out)
        self.assertIn("override marker present", out)


if __name__ == "__main__":
    unittest.main()
