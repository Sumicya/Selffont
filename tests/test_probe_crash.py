"""Existing native crash collection must stay limited to this standalone probe."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProbeCrashTests(unittest.TestCase):
    def test_only_probe_header_and_backtrace_are_exported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'tombstone_00').write_text('''Timestamp: fixture
Cmdline: /system/bin/app_process /system/bin com.mfga.xposed.diagnostics.FontMetricsProbe
pid: 123, tid: 123
signal 6 (SIGABRT)
Abort message: 'fixture abort'
backtrace:
  #00 pc 00000001 /system/lib64/libc.so
memory near x0: PRIVATE_MEMORY
''')
            (root/'tombstone_01').write_text('''Cmdline: com.example.private
Abort message: 'mentioned com.mfga.xposed.diagnostics.FontMetricsProbe'
  #00 pc OTHER_APP_FRAME
''')
            (root/'tombstone_02.pb').write_text('Cmdline: selffont-probe\nAbort message: PRIVATE_PROTOBUF\n')
            result = subprocess.run(['sh', str(ROOT/'tools/collect_probe_crash.sh')],
                                    env=dict(os.environ, SELFFONT_TOMBSTONE_DIR=str(root)),
                                    text=True, capture_output=True, check=True).stdout
            self.assertIn('fixture abort', result)
            self.assertIn('/system/lib64/libc.so', result)
            self.assertIn('matched_probe=1', result)
            for forbidden in ('PRIVATE_MEMORY', 'OTHER_APP_FRAME', 'PRIVATE_PROTOBUF', 'com.example.private'):
                self.assertNotIn(forbidden, result)

    def test_missing_tombstones_are_not_a_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(['sh', str(ROOT/'tools/collect_probe_crash.sh')],
                                    env=dict(os.environ, SELFFONT_TOMBSTONE_DIR=temp),
                                    text=True, capture_output=True, check=True).stdout
            self.assertIn('matched_probe=0', result)
            self.assertIn('[crash-unavailable]', result)
