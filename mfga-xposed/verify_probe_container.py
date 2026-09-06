#!/usr/bin/env python3
"""Check every DEX for the probe's class definition and public static main.

A descriptor in the string pool is not proof that its class is defined. This is
an entry-point packaging check, not a replacement for ART's DEX verifier.
"""
import argparse
import json
import os
import re
import struct
import zipfile

PROBE = 'Lcom/mfga/xposed/diagnostics/FontMetricsProbe;'
MAX_DEX = 16 * 1024 * 1024


class Dex:
    def __init__(self, data, header=0):
        self.data = data
        self.header = header
        if not re.fullmatch(rb'dex\n0(?:3[5-9]|4[01])\x00', data[header:header+8]):
            raise ValueError('Unsupported DEX magic/version')
        self.version = int(data[header+4:header+7])
        self.size = self.u32(header + 0x20)
        header_size = self.u32(header + 0x24)
        if self.size < header_size or header + self.size > len(data):
            raise ValueError('Invalid DEX section size')
        if self.u32(header + 0x28) != 0x12345678:
            raise ValueError('Only little-endian DEX is supported')
        if self.version >= 41:
            if header_size != 0x78 or self.u32(header+0x70) != len(data) or self.u32(header+0x74) != header:
                raise ValueError('Invalid DEX container header')
        elif header_size != 0x70 or header != 0:
            raise ValueError('Invalid standalone DEX header')
        self.strings = self.table(0x38, 4)
        self.types = self.table(0x40, 4)
        self.protos = self.table(0x48, 12)
        self.methods = self.table(0x58, 8)
        self.classes = self.table(0x60, 32)

    def span(self, offset, length):
        if offset < 0 or length < 0 or offset + length > len(self.data):
            raise ValueError('DEX offset outside container')

    def u16(self, offset):
        self.span(offset, 2)
        return struct.unpack_from('<H', self.data, offset)[0]

    def u32(self, offset):
        self.span(offset, 4)
        return struct.unpack_from('<I', self.data, offset)[0]

    def table(self, location, width):
        count, offset = self.u32(self.header+location), self.u32(self.header+location+4)
        self.span(offset, count * width)
        return count, offset

    def indexed(self, table, index, width):
        count, offset = table
        if index >= count:
            raise ValueError('DEX table index out of bounds')
        return offset + index * width

    def uleb(self, offset):
        value = 0
        for shift in range(0, 35, 7):
            self.span(offset, 1)
            byte = self.data[offset]
            offset += 1
            value |= (byte & 0x7f) << shift
            if byte < 0x80:
                return value, offset
        raise ValueError('Invalid DEX ULEB128')

    def string(self, index):
        offset = self.u32(self.indexed(self.strings, index, 4))
        _, offset = self.uleb(offset)
        end = self.data.find(b'\x00', offset)
        if end < 0:
            raise ValueError('Unterminated DEX string')
        # Only ASCII class/method/type descriptors are relevant to this check.
        return self.data[offset:end].decode('utf-8', errors='replace')

    def type(self, index):
        return self.string(self.u32(self.indexed(self.types, index, 4)))

    def main_proto(self, index):
        offset = self.indexed(self.protos, index, 12)
        if self.type(self.u32(offset+4)) != 'V':
            return False
        params = self.u32(offset+8)
        return bool(params and self.u32(params) == 1 and self.type(self.u16(params+4)) == '[Ljava/lang/String;')

    def probe(self):
        for i in range(self.classes[0]):
            offset = self.indexed(self.classes, i, 32)
            class_index = self.u32(offset)
            if self.type(class_index) != PROBE:
                continue
            if not self.u32(offset+4) & 1:
                raise ValueError('Probe class is not public')
            pos = self.u32(offset+24)
            if not pos:
                raise ValueError('Probe class has no method definitions')
            sizes = []
            for _ in range(4):
                size, pos = self.uleb(pos)
                sizes.append(size)
            for _ in range(sizes[0] + sizes[1]):
                _, pos = self.uleb(pos)
                _, pos = self.uleb(pos)
            method_index = 0
            for _ in range(sizes[2]):
                diff, pos = self.uleb(pos)
                access, pos = self.uleb(pos)
                code, pos = self.uleb(pos)
                method_index += diff
                method = self.indexed(self.methods, method_index, 8)
                if (self.u16(method) == class_index and self.string(self.u32(method+4)) == 'main'
                        and self.main_proto(self.u16(method+2)) and access & 9 == 9 and code != 0):
                    self.span(code, 16)
                    return True
            raise ValueError('Probe has no concrete public static main(String[])')
        return False


def inspect(apk):
    files, found = [], []
    with zipfile.ZipFile(apk) as archive:
        for entry in archive.infolist():
            if not re.fullmatch(r'classes(?:[0-9]+)?\.dex', entry.filename):
                continue
            if entry.file_size > MAX_DEX:
                raise ValueError('Diagnostic DEX exceeds inspection limit')
            data = archive.read(entry)
            files.append(entry.filename)
            offset = 0
            while offset < len(data):
                dex = Dex(data, offset)
                if dex.probe():
                    found.append({'dex': entry.filename, 'headerOffset': offset, 'version': dex.version})
                offset += dex.size
                if dex.version < 41:
                    if offset != len(data):
                        raise ValueError('Unexpected trailing data in standalone DEX')
                    break
    if len(found) != 1:
        raise ValueError(f'Expected one defined probe main, found {len(found)}; DEX files={files}')
    return {'probe': PROBE, 'main': 'public static main(String[])', 'dexFiles': files,
            'definition': found[0], 'classpathContract': 'WHOLE_APK'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk')
    args = parser.parse_args()
    try:
        report = inspect(args.apk)
    except (ValueError, zipfile.BadZipFile) as error:
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            print('::error title=Probe entry verification::' + str(error).replace('%', '%25').replace('\n', '%0A'))
        raise
    print(json.dumps(report, indent=2))
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print('::notice title=Probe entry verified::' + report['definition']['dex']
              + '; headerOffset=' + str(report['definition']['headerOffset'])
              + '; main(String[]) defined; classpath must retain the whole APK')


if __name__ == '__main__':
    main()
