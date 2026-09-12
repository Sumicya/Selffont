"""Privacy and path-boundary checks for the read-only Android state report."""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT = 'Selffont-WenYuanRoundedSCVF.ttf'


class DeviceStateTests(unittest.TestCase):
    def report(self, running=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod, system, proc, binaries = (root/name for name in ('mod', 'system', 'proc', 'bin'))
            for directory in (mod/'system/fonts', system/'fonts', system/'etc', proc, binaries):
                directory.mkdir(parents=True)
            for path in (mod/'system/fonts'/FONT, system/'fonts'/FONT):
                path.write_bytes(b'public fixture font')
            (mod/'module.prop').write_text('id=MFGA\nversion=test\nprivate_key=not-for-report\n')
            (mod/'fonts.xml').write_text('<familyset/>')
            (system/'etc/fonts.xml').write_text('<familyset/>')
            (proc/'uptime').write_text('42 42\n')
            (binaries/'pidof').write_text('#!/bin/sh\n' + ('echo 123\n' if running else 'exit 1\n'))
            (binaries/'dumpsys').write_text('#!/bin/sh\nprintf "%s\\n" " versionName=test" " unrelated secret" " User 0: installed=true enabled=0"\n')
            for binary in binaries.iterdir():
                binary.chmod(0o755)
            if running:
                scoped = proc/'123/root/system/fonts'/FONT
                scoped.parent.mkdir(parents=True)
                scoped.write_bytes(b'different namespace font')
            env = dict(os.environ, SELFFONT_MODULE_ROOT=str(mod),
                       SELFFONT_SYSTEM_ROOT=str(system), SELFFONT_PROC_ROOT=str(proc),
                       PATH=str(binaries)+':'+os.environ['PATH'])
            result = subprocess.run(['sh', str(ROOT/'tools/device_state.sh')], env=env,
                                    text=True, capture_output=True, check=True)
            self.assertEqual((mod/'system/fonts'/FONT).read_bytes(), b'public fixture font')
            self.assertEqual((system/'fonts'/FONT).read_bytes(), b'public fixture font')
            return result.stdout

    def test_no_process_and_only_selected_metadata(self):
        result = self.report()
        self.assertIn('[firefox-main-not-running]', result)
        self.assertIn('versionName=test', result)
        self.assertNotIn('not-for-report', result)
        self.assertNotIn('unrelated secret', result)

    def test_process_root_view_is_separate_and_not_an_app_access_claim(self):
        result = self.report(running=True)
        self.assertIn('main_pid=123', result)
        self.assertIn('not proof of app-UID access', result)
        self.assertIn(hashlib.sha256(b'different namespace font').hexdigest(), result)
        self.assertIn(hashlib.sha256(b'public fixture font').hexdigest(), result)
