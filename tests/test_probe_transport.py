"""Host tests cover the probe launcher, not Android Paint behavior."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('unzip'), 'host unzip required')
class ProbeTransportTests(unittest.TestCase):
    def test_only_private_temporary_dex_is_executed_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = root/'bin'
            binaries.mkdir()
            (binaries/'id').write_text('#!/bin/sh\necho 0\n')
            process = binaries/'app_process'
            process.write_text('''#!/bin/sh
[ "$(stat -c %a "$CLASSPATH")" = 444 ] || exit 7
[ "$(cat "$CLASSPATH")" = 'original test bytes' ] || exit 8
[ "$2" = com.mfga.xposed.diagnostics.FontMetricsProbe ] || exit 9
printf 'probe fixture executed\\n'
''')
            for binary in binaries.iterdir():
                binary.chmod(0o755)
            archive = root/'container.apk'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('classes.dex', b'original test bytes')
                z.writestr('unrelated', b'not executed')
            original = archive.read_bytes()
            script = (ROOT/'tools/run_font_probe.sh').read_text()
            script = script.replace('/data/local/tmp/selffont-font-probe.', str(root/'probe.'))
            script = script.replace('/system/bin/app_process', str(process))
            env = dict(os.environ, PATH=str(binaries)+':'+os.environ['PATH'])
            result = subprocess.run(['sh', '-c', script, 'probe-test', str(archive)],
                                    env=env, text=True, capture_output=True, check=True)
            self.assertIn('probe fixture executed', result.stdout)
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(list(root.glob('probe.*')), [])

    def test_probe_is_not_registered_as_a_module_entry(self):
        registrations = (ROOT/'mfga-xposed/app/src/main/resources/META-INF/xposed/java_init.list').read_text()
        self.assertNotIn('FontMetricsProbe', registrations)
        source = (ROOT/'mfga-xposed/app/src/main/java/com/mfga/xposed/modern/ModernEntry.java').read_text()
        self.assertNotIn('FontMetricsProbe', source)
