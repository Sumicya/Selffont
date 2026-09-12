"""Synthetic DEX headers/tables exercise entry inspection, not ART execution."""
import importlib.util
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_probe_container', ROOT/'mfga-xposed/verify_probe_container.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def uleb(value):
    result = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        result.append(byte | (128 if value else 0))
        if not value:
            return result


def dex_fixture(defined=True, static=True, offset=0, container=0):
    data = bytearray(2064)
    header_size = 0x78 if container else 0x70
    data[:8] = b'dex\n041\0' if container else b'dex\n039\0'
    def put(pos, value):
        struct.pack_into('<I', data, pos, value)
    put(0x20, len(data))
    put(0x24, header_size)
    put(0x28, 0x12345678)
    if container:
        put(0x70, container)
        put(0x74, offset)
    strings = [verify.PROBE, 'V', '[Ljava/lang/String;', 'VL', 'main']
    string_ids = header_size
    type_ids = string_ids + 4*len(strings)
    protos = type_ids + 12
    methods = protos + 12
    classes = methods + 8
    params = classes + 32
    for field, count, location in ((0x38, 5, string_ids), (0x40, 3, type_ids),
                                    (0x48, 1, protos), (0x58, 1, methods),
                                    (0x60, int(defined), classes)):
        put(field, count)
        put(field+4, location+offset)
    for index in range(3):
        put(type_ids+4*index, index)
    put(protos, 3)
    put(protos+4, 1)
    put(protos+8, params+offset)
    struct.pack_into('<HHI', data, methods, 0, 0, 4)
    put(params, 1)
    struct.pack_into('<H', data, params+4, 2)
    current = params + 6
    for i, value in enumerate(strings):
        encoded = uleb(len(value)) + value.encode() + b'\0'
        put(string_ids+4*i, current+offset)
        data[current:current+len(encoded)] = encoded
        current += len(encoded)
    put(classes, 0)
    put(classes+4, 1)
    put(classes+24, current+offset)
    class_data = b'\0\0\1\0' + uleb(0) + uleb(9 if static else 1) + uleb(2048+offset)
    data[current:current+len(class_data)] = class_data
    return bytes(data)


class ProbeContainerTests(unittest.TestCase):
    def inspect(self, entries):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'container.apk'
            with zipfile.ZipFile(path, 'w') as archive:
                for name, data in entries:
                    archive.writestr(name, data)
            return verify.inspect(path)

    def test_secondary_dex_definition_is_found(self):
        result = self.inspect([('classes.dex', dex_fixture(defined=False)),
                               ('classes2.dex', dex_fixture())])
        self.assertEqual(result['definition']['dex'], 'classes2.dex')
        self.assertEqual(result['classpathContract'], 'WHOLE_APK')

    def test_string_reference_is_not_a_class_definition(self):
        with self.assertRaisesRegex(ValueError, 'found 0'):
            self.inspect([('classes.dex', dex_fixture(defined=False))])

    def test_main_must_be_static(self):
        with self.assertRaisesRegex(ValueError, 'public static main'):
            self.inspect([('classes.dex', dex_fixture(static=False))])

    def test_dex_041_container_offsets(self):
        data = dex_fixture(defined=False, container=4128) + dex_fixture(offset=2064, container=4128)
        result = self.inspect([('classes.dex', data)])
        self.assertEqual(result['definition']['headerOffset'], 2064)
        self.assertEqual(result['definition']['version'], 41)

    def test_bad_offset_is_rejected(self):
        data = bytearray(dex_fixture())
        struct.pack_into('<I', data, 0x3c, 0x7fffffff)
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.inspect([('classes.dex', data)])
