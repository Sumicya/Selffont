"""Privacy and path-boundary checks for the read-only Android state report."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "config/font-source.json").read_text())
FACES = [face["installedFile"] for face in MANIFEST["faces"]]
VISIBILITY = MANIFEST["visibilityFile"]
FONT_CONF = "".join(
    f"SELFFONT_INSTALLED_{face['style'].upper()}={face['installedFile']}\n" for face in MANIFEST["faces"]
) + f"SELFFONT_VISIBILITY_FILE={VISIBILITY}\n"


class DeviceStateTests(unittest.TestCase):
    def report(self, running=False, with_font_conf=True):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod, system, proc, binaries = (root / name for name in ("mod", "system", "proc", "bin"))
            for directory in (mod / "system/fonts", system / "fonts", system / "etc", proc, binaries):
                directory.mkdir(parents=True)
            for name in FACES:
                (mod / "system/fonts" / name).write_bytes(b"public fixture font")
                (system / "fonts" / name).write_bytes(b"public fixture font")
            if with_font_conf:
                (mod / "font.conf").write_text(FONT_CONF)
            (mod / "module.prop").write_text("id=MFGA\nversion=test\nprivate_key=not-for-report\n")
            (mod / "fonts.xml").write_text("<familyset/>")
            (system / "etc/fonts.xml").write_text("<familyset/>")
            (proc / "uptime").write_text("42 42\n")
            (binaries / "pidof").write_text("#!/bin/sh\n" + ("echo 123\n" if running else "exit 1\n"))
            (binaries / "dumpsys").write_text(
                '#!/bin/sh\nprintf "%s\\n" " versionName=test" " unrelated secret" " User 0: installed=true enabled=0"\n'
            )
            for binary in binaries.iterdir():
                binary.chmod(0o755)
            if running:
                scoped = proc / "123/root/system/fonts" / VISIBILITY
                scoped.parent.mkdir(parents=True)
                scoped.write_bytes(b"different namespace font")
            env = dict(
                os.environ,
                SELFFONT_MODULE_ROOT=str(mod),
                SELFFONT_SYSTEM_ROOT=str(system),
                SELFFONT_PROC_ROOT=str(proc),
                PATH=str(binaries) + ":" + os.environ["PATH"],
            )
            result = subprocess.run(
                ["sh", str(ROOT / "tools/device_state.sh")], env=env, text=True, capture_output=True, check=True
            )
            for name in FACES:
                self.assertEqual((mod / "system/fonts" / name).read_bytes(), b"public fixture font")
                self.assertEqual((system / "fonts" / name).read_bytes(), b"public fixture font")
            return result.stdout

    def test_no_process_and_only_selected_metadata(self):
        result = self.report()
        self.assertIn("[firefox-main-not-running]", result)
        self.assertIn("versionName=test", result)
        self.assertNotIn("not-for-report", result)
        self.assertNotIn("unrelated secret", result)

    def test_every_installed_face_is_reported(self):
        result = self.report()
        digest = hashlib.sha256(b"public fixture font").hexdigest()
        for name in FACES:
            self.assertIn(name, result)
        self.assertEqual(result.count(digest), len(FACES) * 2)  # module copy + system copy

    def test_process_root_view_is_separate_and_not_an_app_access_claim(self):
        result = self.report(running=True)
        self.assertIn("main_pid=123", result)
        self.assertIn("not proof of app-UID access", result)
        self.assertIn(hashlib.sha256(b"different namespace font").hexdigest(), result)
        self.assertIn(hashlib.sha256(b"public fixture font").hexdigest(), result)

    def test_missing_font_conf_is_reported_not_guessed(self):
        result = self.report(with_font_conf=False)
        self.assertIn("[font-conf-missing]", result)
        self.assertNotIn("different namespace font", result)


if __name__ == "__main__":
    unittest.main()
