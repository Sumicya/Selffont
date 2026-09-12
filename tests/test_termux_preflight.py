"""Transport guards, with fake commands only; never invoke the real phone or network."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TermuxPreflightTests(unittest.TestCase):
    def run_fixture(self, http='200', auth=0, success=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binaries = root/'bin'
            binaries.mkdir()
            calls = root/'calls'
            (binaries/'curl').write_text('#!/bin/sh\nprintf "%s" "$TEST_HTTP"\n')
            (binaries/'gh').write_text('''#!/bin/sh
printf '%s\\n' "$1" >> "$TEST_CALLS"
if [ "$1" = auth ]; then exit "$TEST_AUTH"; fi
if [ "$TEST_SUCCESS" = 1 ]; then
    if [ "$1" = run ]; then
        while [ "$#" -gt 0 ]; do
            if [ "$1" = -D ]; then shift; printf fixture > "$1/app-debug.apk"; exit 0; fi
            shift
        done
    elif [ "$1" = api ]; then
        cat "$TEST_LAUNCHER"
        exit 0
    fi
fi
exit 1
''')
            (binaries/'su').write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALLS"\n[ "$TEST_SUCCESS" = 1 ] && { echo DIRECT_STDOUT; exit 0; }\nexit 99\n')
            for path in binaries.iterdir():
                path.chmod(0o755)
            env = dict(os.environ, HOME=str(root), PATH=str(binaries)+':'+os.environ['PATH'],
                       TEST_HTTP=http, TEST_AUTH=str(auth), TEST_CALLS=str(calls),
                       TEST_SUCCESS='1' if success else '0',
                       TEST_LAUNCHER=str(ROOT/'tools/run_font_probe.sh'))
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

    def test_measurement_output_stays_in_terminal(self):
        result, calls = self.run_fixture(success=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DIRECT_STDOUT', result.stdout)
        self.assertIn('Probe exit=0', result.stdout)
        self.assertNotIn('/sdcard/Download', calls)
        self.assertNotIn('>', calls)
