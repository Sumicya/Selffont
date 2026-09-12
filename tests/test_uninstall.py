"""uninstall.sh must restore recorded app-font permission changes and nothing else.

It is intentionally minimal: it delegates to app_fonts.sh restore --confirm, so
these tests confirm it invokes exactly that (restore, with --confirm) against a
sibling app_fonts.sh, and never a destructive 'block'. The restore logic itself
is covered by the PermissionTests in test_refactor.py.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNINSTALL = (ROOT / "script/uninstall.sh").read_text()


class UninstallScriptTests(unittest.TestCase):
    def run_uninstall(self):
        """Run uninstall.sh with a stub app_fonts.sh that records its arguments."""
        with tempfile.TemporaryDirectory() as temp:
            modpath = Path(temp)
            calls = modpath / "calls.log"
            (modpath / "uninstall.sh").write_text(UNINSTALL)
            (modpath / "app_fonts.sh").write_text(
                f'#!/bin/sh\necho "$*" >> "{calls}"\nexit 0\n')
            (modpath / "app_fonts.sh").chmod(0o755)
            result = subprocess.run(["sh", str(modpath / "uninstall.sh")],
                                    text=True, capture_output=True, env=dict(os.environ))
            log = calls.read_text().strip() if calls.exists() else ""
            return result.returncode, log

    def test_delegates_restore_with_confirm(self):
        rc, log = self.run_uninstall()
        self.assertEqual(rc, 0)
        self.assertEqual(log, "restore --confirm")

    def test_never_blocks(self):
        # Uninstall must never re-apply the destructive 'block' operation.
        _, log = self.run_uninstall()
        self.assertNotIn("block", log)

    def test_source_only_restores(self):
        # Static guard: the script body contains restore, not block.
        self.assertIn("restore --confirm", UNINSTALL)
        self.assertNotIn("block", UNINSTALL)


if __name__ == "__main__":
    unittest.main()
