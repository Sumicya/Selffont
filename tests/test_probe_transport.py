"""Host launcher tests; no Android runtime and no font measurements are simulated."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class ProbeTransportTests(unittest.TestCase):
    def test_complete_container_and_explicit_classpath_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = root/'bin'
            binaries.mkdir()
            (binaries/'id').write_text('#!/bin/sh\necho 0\n')
            process = binaries/'app_process'
            process.write_text('''#!/bin/sh
[ "$(stat -c %a "$CLASSPATH")" = 444 ] || exit 7
cmp "$CLASSPATH" "$TEST_ORIGINAL" || exit 8
[ "$1" = "-Djava.class.path=$CLASSPATH" ] || exit 9
[ "$3" = --nice-name=selffont-probe ] || exit 10
[ "$4" = com.mfga.xposed.diagnostics.FontMetricsProbe ] || exit 11
[ -z "${LD_PRELOAD:-}" ] && [ -z "${LD_LIBRARY_PATH:-}" ] || exit 12
printf 'probe fixture executed\\n'
''')
            for binary in binaries.iterdir():
                binary.chmod(0o755)
            archive = root/'container.apk'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('classes.dex', b'not the entry point')
                z.writestr('classes2.dex', b'entry point fixture')
            original = archive.read_bytes()
            script = (ROOT/'tools/run_font_probe.sh').read_text()
            script = script.replace('/data/local/tmp/selffont-font-probe.', str(root/'probe.'))
            script = script.replace('/system/bin/app_process', str(process))
            script = script.replace('/system/bin/timeout', '/usr/bin/timeout')
            script = script.replace('export PATH=/system/bin:/system/xbin', 'export PATH="'+str(binaries)+':/usr/bin:/bin"')
            env = dict(os.environ, PATH=str(binaries)+':'+os.environ['PATH'],
                       TEST_ORIGINAL=str(archive), LD_LIBRARY_PATH='must-not-reach-system-runtime')
            result = subprocess.run(['sh', '-c', script, 'probe-test', str(archive)],
                                    env=env, text=True, capture_output=True, check=True)
            self.assertIn('probe fixture executed', result.stdout)
            self.assertIn('[launcher-exit] 0', result.stdout)
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(list(root.glob('probe.*')), [])

    def test_probe_is_not_registered_as_a_module_entry(self):
        registrations = (ROOT/'mfga-xposed/app/src/main/resources/META-INF/xposed/java_init.list').read_text()
        self.assertNotIn('FontMetricsProbe', registrations)
        source = (ROOT/'mfga-xposed/app/src/main/kotlin/com/mfga/xposed/modern/ModernEntry.kt').read_text()
        self.assertNotIn('FontMetricsProbe', source)
