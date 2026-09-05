import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from font_config import configure_fonts, PRIMARY_NAMES
from prepare_font import MANIFEST, verify_font
from build_module import build, font_members


class FontConfigurationTests(unittest.TestCase):
    def test_primary_families_and_axes(self):
        root = ET.fromstring(configure_fonts((ROOT / 'fonts.xml').read_bytes(), MANIFEST['installedFile']))
        for name in PRIMARY_NAMES:
            family = root.find(f"family[@name='{name}']")
            self.assertIsNotNone(family, name)
            fonts = family.findall('font')
            self.assertEqual(len(fonts), 18)
            for font in fonts:
                self.assertEqual(font.text.strip(), MANIFEST['installedFile'])
                axes = {axis.get('tag'): axis.get('stylevalue') for axis in font}
                self.assertEqual(axes['wght'], font.get('weight'))
                self.assertEqual(axes['ital'], '1' if font.get('style') == 'italic' else '0')
                self.assertEqual(set(axes), {'wght', 'ital'})
        # Preserve fallback coverage and alias semantics, not the empty-Roboto workaround.
        self.assertTrue(any((f.text or '').strip() == 'NotoSansPro.otf' for f in root.iter('font')))
        self.assertIsNotNone(root.find("alias[@name='sans-serif-semibold']"))
        self.assertFalse(any((f.text or '').strip() == '400.ttf' for f in root.iter('font')))

    def test_reject_wrong_schema_and_path(self):
        for xml, filename in [(b'<fonts-modification/>', 'a.ttf'), (b'<familyset/>', '../a.ttf')]:
            with self.assertRaises(ValueError):
                configure_fonts(xml, filename)

    def test_hash_failure_precedes_font_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'font.ttf'
            file.write_bytes(b'bad')
            manifest = dict(MANIFEST, bytes=3)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                verify_font(file, manifest)

    def test_java_contract_matches_manifest(self):
        source = (ROOT / 'mfga-xposed/app/src/main/java/com/mfga/xposed/GeckoFontPolicy.java').read_text()
        self.assertIn('"' + MANIFEST['family'] + '"', source)
        self.assertIn('"/system/fonts/' + MANIFEST['installedFile'] + '"', source)

    def test_probe_is_original_ascii_control(self):
        from fontTools.ttLib import TTFont
        with TTFont(ROOT / 'webroot/probe.ttf') as font:
            self.assertEqual(font.getBestCmap()[ord('A')], 'triangle')
            self.assertEqual(set(font.getBestCmap()), {32, 65})


class PackagingTests(unittest.TestCase):
    def test_base_code_never_inherited(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            base, font, output = temp/'base.zip', temp/'font.ttf', temp/'module.zip'
            font.write_bytes(b'fixture font')
            with zipfile.ZipFile(base, 'w') as z:
                z.writestr('system/fonts/NotoSansPro.otf', b'fallback fixture')
                z.writestr('system/fonts/400.ttf', b'old primary')
                z.writestr('service.sh', 'dangerous old boot hook')
                z.writestr('bin/old_tool', 'old tool')
                z.writestr('module.prop', 'updateJson=https://upstream.example/update')
                z.writestr('LICENSES.md', 'base attribution')
            with patch('build_module.verify_font', return_value={'deviceRendering': 'NOT_TESTED'}) as verify:
                build(base, font, output)
                verify.assert_called_once_with(font)
            with zipfile.ZipFile(output) as z:
                self.assertIn('system/fonts/' + MANIFEST['installedFile'], z.namelist())
                self.assertNotIn('system/fonts/400.ttf', z.namelist())
                self.assertNotIn('bin/old_tool', z.namelist())
                self.assertNotIn('updateJson', z.read('module.prop').decode())
                self.assertEqual(z.read('service.sh'), (ROOT/'script/service.sh').read_bytes())
                self.assertIn('licenses/MFGA-base-LICENSES.md', z.namelist())
                self.assertIn('licenses/WenYuan-OFL.txt', z.namelist())
                self.assertEqual(stat.S_IMODE(z.getinfo('system/fonts/' + MANIFEST['installedFile']).external_attr >> 16), 0o644)
                self.assertEqual(stat.S_IMODE(z.getinfo('action.sh').external_attr >> 16), 0o755)

    def test_malformed_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)/'bad.zip'
            for name in ('../system/fonts/a.ttf', '/system/fonts/a.ttf'):
                with zipfile.ZipFile(base, 'w') as z:
                    z.writestr(name, b'font')
                with zipfile.ZipFile(base) as z, self.assertRaises(ValueError):
                    list(font_members(z))
            with zipfile.ZipFile(base, 'w') as z:
                info = zipfile.ZipInfo('system/fonts/link.ttf')
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(info, '/data/private')
            with zipfile.ZipFile(base) as z, self.assertRaises(ValueError):
                list(font_members(z))


@unittest.skipUnless(shutil.which('busybox'), 'requires BusyBox ash (KernelSU shell model)')
class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root/'data'
        self.state = self.root/'state'
        self.font = self.data/'com.dragon.read/files/font/test font.ttf'
        self.font.parent.mkdir(parents=True)
        self.font.write_text('fixture')
        self.font.chmod(0o640)
        self.env = dict(os.environ, SELFFONT_DATA_ROOT=str(self.data), SELFFONT_STATE_DIR=str(self.state))

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, operation, confirm=True):
        command = ['busybox', 'sh', str(ROOT/'script/app_fonts.sh'), operation]
        if confirm:
            command.append('--confirm')
        return subprocess.run(command, env=self.env, text=True, capture_output=True)

    def mode(self):
        return stat.S_IMODE(self.font.stat().st_mode)

    def test_requires_confirmation(self):
        self.assertEqual(self.run_script('block', False).returncode, 2)
        self.assertEqual(self.mode(), 0o640)
        self.assertFalse(self.state.exists())

    def test_roundtrip_and_repeated_block(self):
        for _ in range(2):
            result = self.run_script('block')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.mode(), 0)
        self.assertEqual(len((self.state/'app-permissions.tsv').read_text().splitlines()), 1)
        self.assertEqual(self.run_script('restore').returncode, 0)
        self.assertEqual(self.mode(), 0o640)
        self.assertEqual(self.run_script('restore').returncode, 0)

    def test_unrecorded_mode_zero_is_not_guessed(self):
        self.font.chmod(0)
        self.assertEqual(self.run_script('block').returncode, 0)
        self.assertEqual(self.run_script('restore').returncode, 0)
        self.assertEqual(self.mode(), 0)

    def test_later_changes_and_replaced_files_are_preserved(self):
        self.run_script('block')
        self.font.chmod(0o644)
        self.run_script('restore')
        self.assertEqual(self.mode(), 0o644)
        self.run_script('block')
        self.font.rename(self.font.with_suffix('.old'))
        self.font.write_text('new inode')
        self.font.chmod(0o600)
        self.run_script('restore')
        self.assertEqual(self.mode(), 0o600)

    def test_replaced_file_can_be_blocked_and_restored_again(self):
        self.run_script('block')
        self.font.rename(self.font.with_suffix('.old'))
        self.font.write_text('replacement')
        self.font.chmod(0o600)
        self.assertEqual(self.run_script('block').returncode, 0)
        self.assertEqual(self.mode(), 0)
        self.assertEqual(self.run_script('restore').returncode, 0)
        self.assertEqual(self.mode(), 0o600)

    def test_lock_and_invalid_records(self):
        self.state.mkdir()
        lock = self.state/'app-fonts.lock'
        lock.mkdir()
        self.assertNotEqual(self.run_script('block').returncode, 0)
        self.assertEqual(self.mode(), 0o640)
        lock.rmdir()
        outside = self.root/'outside.ttf'
        outside.write_text('untouched')
        outside.chmod(0)
        (self.state/'app-permissions.tsv').write_text(f'777\t0:0\t{outside}\n')
        self.assertNotEqual(self.run_script('restore').returncode, 0)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0)
        self.assertIn(str(outside), (self.state/'app-permissions.tsv').read_text())

    def test_real_advisory_lock_blocks_then_releases(self):
        self.state.mkdir()
        with (self.state/'app-fonts.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotEqual(self.run_script('block').returncode, 0)
            self.assertEqual(self.mode(), 0o640)
        self.assertEqual(self.run_script('block').returncode, 0)
        self.assertEqual(self.run_script('restore').returncode, 0)
        self.assertEqual(self.mode(), 0o640)

    def test_parent_symlink_cannot_escape_the_app_font_directory(self):
        outside = self.root/'outside'
        outside.mkdir()
        protected = outside/'protected.ttf'
        protected.write_text('outside')
        protected.chmod(0o600)
        self.font.unlink()
        self.font.parent.rmdir()
        self.font.parent.symlink_to(outside, target_is_directory=True)
        result = self.run_script('block')
        self.assertEqual(stat.S_IMODE(protected.stat().st_mode), 0o600)
        # find may simply skip a root symlink, or the explicit path check rejects it.
        self.assertIn(result.returncode, (0, 1))

    def test_failed_journal_write_never_precedes_a_permission_change(self):
        self.state.mkdir()
        (self.state/'app-permissions.tsv').mkdir()
        self.assertNotEqual(self.run_script('block').returncode, 0)
        self.assertEqual(self.mode(), 0o640)

    def test_non_fonts_and_newline_paths_are_not_mutated(self):
        other = self.font.with_suffix('.txt')
        other.write_text('not a font')
        other.chmod(0o644)
        unsafe = self.font.parent/'line\nbreak.ttf'
        unsafe.write_text('fixture')
        unsafe.chmod(0o644)
        self.assertNotEqual(self.run_script('block').returncode, 0)
        self.assertEqual(stat.S_IMODE(unsafe.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(other.stat().st_mode), 0o644)


@unittest.skipUnless(shutil.which('busybox'), 'requires BusyBox')
class InstallerTests(unittest.TestCase):
    def run_install(self, api='36', ksu='true', brand='OnePlus', manufacturer='OnePlus'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod, system, bin_dir = root/'module', root/'system', root/'bin'
            mod.mkdir(); bin_dir.mkdir(); (system/'etc').mkdir(parents=True)
            (mod/'system/fonts').mkdir(parents=True)
            (mod/'system/fonts'/MANIFEST['installedFile']).write_text('prepared fixture')
            shutil.copytree(ROOT/'lang', mod/'lang')
            for src, dst in [('script/search_dirs.sh','search_dirs.sh'), ('fonts_list.yaml','fonts_list.yaml')]:
                shutil.copyfile(ROOT/src, mod/dst)
            (mod/'fonts.xml').write_text('<familyset/>')
            (system/'etc/font_fallback.xml').write_text('<old/>')
            (system/'etc/fonts_customization.xml').write_text('<fonts-modification/>')
            (bin_dir/'getprop').write_text(f'#!/bin/sh\ncase "$1" in *brand) echo "{brand}";; *manufacturer) echo "{manufacturer}";; *) echo zh-CN;; esac\n')
            (bin_dir/'getprop').chmod(0o755)
            command = 'abort() { echo "$*" >&2; exit 1; }; ui_print() { echo "$*"; }; . "$INSTALLER"'
            env = dict(os.environ, API=api, KSU=ksu, MODPATH=str(mod), SELFFONT_SYSTEM_ROOT=str(system),
                       INSTALLER=str(ROOT/'script/customize.sh'), PATH=str(bin_dir)+':'+os.environ['PATH'])
            result = subprocess.run(['busybox','sh','-c',command],env=env,capture_output=True,text=True)
            copied = (mod/'system/etc/font_fallback.xml').exists()
            blacklisted = (mod/'system/etc/fonts_customization.xml').exists()
            return result, copied, blacklisted

    def test_supported_platform_and_schema_exception(self):
        result, copied, blacklisted = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertTrue(copied)
        self.assertFalse(blacklisted)

    def test_other_platforms_fail_before_copying(self):
        for kwargs in ({'api':'35'}, {'ksu':'false'}, {'brand':'google','manufacturer':'google'}):
            result, copied, _ = self.run_install(**kwargs)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(copied)


class RepositoryContractTests(unittest.TestCase):
    def test_removed_features(self):
        for path in ('script/recolor_glyph.sh','script/unicode_filter.sh','tools/recolor_glyph.c',
                     'tools/unicode_filter.c','.github/workflows/build-recolor_glyph.yml',
                     '.github/workflows/build-unicode_filter.yml',
                     'mfga-xposed/app/src/main/assets/xposed_init'):
            self.assertFalse((ROOT/path).exists(), path)
        for name in ('index.html','scripts.js'):
            text = (ROOT/'webroot'/name).read_text()
            self.assertNotIn('recolor-input', text)
            self.assertNotIn('font-input', text)
            self.assertNotIn('innerHTML', text)

    def test_service_is_inert(self):
        commands = [line.strip() for line in (ROOT/'script/service.sh').read_text().splitlines()
                    if line.strip() and not line.startswith('#')]
        self.assertEqual(commands, ['exit 0'])

    def test_locales_have_same_keys(self):
        files = list((ROOT/'webroot/strings/locales').glob('*.json'))
        expected = set(json.loads(files[0].read_text()))
        for file in files:
            self.assertEqual(set(json.loads(file.read_text())), expected)


if __name__ == '__main__':
    unittest.main()
