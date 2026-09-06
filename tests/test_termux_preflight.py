"""Transport guards, with fake commands only; never invoke the real phone or network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TermuxPreflightTests(unittest.TestCase):
    def run_fixture(self, http='200', auth=0):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binaries = root/'bin'
            binaries.mkdir()
            calls = root/'calls'
            (binaries/'curl').write_text('#!/bin/sh\nprintf "%s" "$TEST_HTTP"\n')
            (binaries/'gh').write_text('''#!/bin/sh
printf '%s\\n' "$1" >> "$TEST_CALLS"
if [ "$1" = auth ]; then exit "$TEST_AUTH"; fi
exit 1
''')
            (binaries/'su').write_text('#!/bin/sh\necho UNEXPECTED_ROOT >> "$TEST_CALLS"\nexit 99\n')
            for path in binaries.iterdir():
                path.chmod(0o755)
            env = dict(os.environ, HOME=str(root), PATH=str(binaries)+':'+os.environ['PATH'],
                       TEST_HTTP=http, TEST_AUTH=str(auth), TEST_CALLS=str(calls))
            result = subprocess.run(['bash', str(ROOT/'tools/termux_font_probe.sh')], env=env,
                                    capture_output=True, text=True)
            return result, calls.read_text() if calls.exists() else ''

    def test_network_failure_stops_before_authentication_or_root(self):
        result, calls = self.run_fixture(http='503')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(calls, '')
        self.assertIn('stage=network', result.stderr)

    def test_authentication_failure_does_not_auto_login(self):
        result, calls = self.run_fixture(auth=1)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(calls.splitlines(), ['auth'])
        self.assertIn('stage=authentication', result.stderr)

    def test_failed_download_attempts_never_reach_root(self):
        result, calls = self.run_fixture()
        self.assertEqual(result.returncode, 5)
        self.assertEqual(calls.splitlines(), ['auth', 'run', 'run'])
        self.assertIn('stage=artifact', result.stderr)
