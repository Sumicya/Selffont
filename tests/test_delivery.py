"""Pinned build inputs and narrowly scoped log collection; no device access."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from prepare_base import verify_base, prepare


class BaseSourceTests(unittest.TestCase):
    def fixture(self, directory, props='id=MFGA\nversionCode=1717180003\n'):
        path = directory/'base.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('module.prop', props)
            archive.writestr('system/fonts/NotoSansPro.otf', b'font fixture')
            archive.writestr('service.sh', b'never execute this')
        data = path.read_bytes()
        return path, {'version': '1717180003', 'bytes': len(data),
                      'sha256': hashlib.sha256(data).hexdigest()}

    def test_size_and_hash_precede_zip_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'bad.zip'
            path.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'size'):
                verify_base(path, {'bytes': 4, 'sha256': '0'*64})
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                verify_base(path, {'bytes': 3, 'sha256': '0'*64})

    def test_identity_and_core_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            path, manifest = self.fixture(Path(temp))
            self.assertEqual(verify_base(path, manifest)['versionCode'], '1717180003')
            path, manifest = self.fixture(Path(temp), 'id=another-module\nversionCode=1717180003\n')
            with self.assertRaisesRegex(ValueError, 'identity'):
                verify_base(path, manifest)

    def test_local_copy_is_exact_and_failure_preserves_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path, manifest = self.fixture(directory)
            output = directory/'output/base.zip'
            with patch('prepare_base.MANIFEST', manifest):
                prepare(path, output)
                self.assertEqual(path.read_bytes(), output.read_bytes())
                path.write_bytes(b'bad')
                with self.assertRaises(ValueError):
                    prepare(path, output)
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), manifest['sha256'])

    def test_manifest_has_a_fixed_resource_identity(self):
        data = json.loads((ROOT/'config/base-source.json').read_text())
        self.assertEqual(data['assetId'], 537532212)
        self.assertEqual(data['version'], '1717180003')
        self.assertEqual(len(data['sha256']), 64)


@unittest.skipUnless(shutil.which('busybox'), 'requires the target BusyBox shell model')
class LogFilterTests(unittest.TestCase):
    def line(self, origin='com.mfga.xposed,Selffont', message='[attach] phase1', process='org.mozilla.firefox'):
        return f'[ 2026-01-01T00:00:00 I/LSPosedLogDaemon ] ({process})[{origin},test,0,1] {message}'

    def filter(self, text):
        return subprocess.run(['busybox', 'awk', '-f', str(ROOT/'script/filter_logs.awk')],
                              input=text, text=True, capture_output=True, check=True).stdout

    def test_origin_filter_rejects_old_code_and_intent_mentions(self):
        current = self.line()
        inputs = [
            current,
            self.line('com.mfga.xposed,MFGA', 'MFGA v1.5 attach'),
            self.line('com.example.observer,IntentAnalyzer', 'URL=https://example.test/Selffont'),
            self.line('com.example.observer,IntentAnalyzer', 'module://com.mfga.xposed:0'),
            self.line('com.example.observer,Other', 'quoted record: ' + current),
        ]
        self.assertEqual(self.filter('\n'.join(inputs)+'\n'), current+'\n')

    def test_duplicates_removed_but_distinct_processes_retained(self):
        main = self.line()
        child = self.line(process='org.mozilla.firefox:tab')
        self.assertEqual(self.filter('\n'.join([main, child, main, child])), main+'\n'+child+'\n')

    def test_only_last_300_unique_records_are_output(self):
        lines = [self.line(message=f'[test] {i}') for i in range(305)]
        self.assertEqual(self.filter('\n'.join(lines)).splitlines(), lines[-300:])

    def test_no_match_is_not_a_false_injection_verdict(self):
        result = self.filter('unrelated private data\n')
        self.assertIn('[logs-no-match]', result)
        self.assertNotIn('private data', result)

    def test_collector_uses_only_the_expected_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = self.line()
            (root/'modules_1.log').write_text(current+'\n')
            (root/'verbose_1.log').write_text(current+'\n')
            (root/'props.txt').write_text(self.line(message='private properties'))
            env = dict(os.environ, SELFFONT_LOG_DIR=str(root))
            result = subprocess.run(['busybox', 'sh', str(ROOT/'script/collect_logs.sh')],
                                    env=env, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, current+'\n')
