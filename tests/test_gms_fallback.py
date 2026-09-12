"""Behavioural tests for the manual, destructive GMS-font fallback helper.

gms_fallback.sh is never called by installation or service.sh; it force-stops
Chrome/Gmail, disables GMS font components and deletes font caches. These tests
run it against stubbed pm/am binaries and a synthetic /data tree so its safety
contract (confirmation gate, tool checks, numeric-user-only scope, cache
deletion) is locked down without touching a real device.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script/gms_fallback.sh"


class GmsFallbackTests(unittest.TestCase):
    def run_script(self, *args, with_pm=True, with_am=True, data_users=("0",),
                   gms_cache=True, data_fonts=True):
        """Run gms_fallback.sh with stubbed pm/am and a synthetic /data tree."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binaries = root / "bin"
            binaries.mkdir()
            calls = root / "calls.log"
            # Stub pm/am: record their invocation and succeed.
            for name, present in (("pm", with_pm), ("am", with_am)):
                if present:
                    (binaries / name).write_text(
                        f'#!/bin/sh\necho "{name} $*" >> "{calls}"\nexit 0\n')
                    (binaries / name).chmod(0o755)
            # Synthetic /data/user/<id> tree and /data/fonts.
            data = root / "data"
            for user in data_users:
                profile = data / "user" / user
                (profile).mkdir(parents=True)
                if gms_cache:
                    cache = profile / "com.google.android.gms/files/fonts"
                    cache.mkdir(parents=True)
                    (cache / "cached.ttf").write_text("cache")
            # A non-numeric dir that must be skipped.
            (data / "user" / "list").mkdir(parents=True, exist_ok=True)
            if data_fonts:
                (data / "fonts").mkdir(parents=True)
                (data / "fonts" / "stale.ttf").write_text("stale")
            # Rewrite the hard-coded /data paths at the top of the script to our tree.
            patched = root / "gms_patched.sh"
            body = SCRIPT.read_text()
            body = body.replace("/data/user/*", f"{data}/user/*")
            body = body.replace('"$profile/com.google.android.gms/files/fonts"',
                                '"$profile/com.google.android.gms/files/fonts"')
            body = body.replace("/data/fonts", f"{data}/fonts")
            patched.write_text(body)
            env = dict(os.environ, PATH=str(binaries) + ":" + os.environ["PATH"])
            result = subprocess.run(["sh", str(patched), *args], env=env, text=True,
                                    capture_output=True)
            log = calls.read_text() if calls.exists() else ""
            return result.returncode, result.stdout + result.stderr, log, data

    def test_requires_confirm(self):
        rc, out, log, _ = self.run_script()
        self.assertEqual(rc, 2)
        self.assertIn("Requires --confirm", out)
        self.assertEqual(log, "")  # nothing was force-stopped

    def test_missing_pm_aborts_before_acting(self):
        rc, out, log, _ = self.run_script("--confirm", with_pm=False)
        self.assertEqual(rc, 1)
        self.assertIn("pm is unavailable", out)
        self.assertEqual(log, "")

    def test_confirmed_run_stops_apps_disables_components_and_clears_cache(self):
        rc, out, log, data = self.run_script("--confirm")
        self.assertEqual(rc, 0, out)
        # Chrome and Gmail were force-stopped.
        self.assertIn("am force-stop com.android.chrome", log)
        self.assertIn("am force-stop com.google.android.gm", log)
        # Both font components were disabled for the numeric user.
        self.assertIn("UpdateSchedulerService", log)
        self.assertIn("provider.FontsProvider", log)
        # The GMS font cache and /data/fonts entries were deleted.
        self.assertFalse((data / "user/0/com.google.android.gms/files/fonts").exists())
        self.assertFalse((data / "fonts/stale.ttf").exists())
        self.assertIn("[gms-exit] 0", out)

    def test_non_numeric_user_dirs_are_skipped(self):
        _, _, log, _ = self.run_script("--confirm")
        # The 'list' directory is not a user id; pm disable must not target it.
        self.assertNotIn("--user list", log)

    def test_no_user_profiles_reports_failure(self):
        rc, _, _, _ = self.run_script("--confirm", data_users=())
        # found=0 -> non-zero exit even though apps were stopped.
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
