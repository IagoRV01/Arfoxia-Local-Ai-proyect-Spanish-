"""Bounded ECMA-335 TypeDef/MethodDef inspection. No Mono, execution or network.

Accepts locally obtained files with embedded BSJB metadata, including AOT ELF.
Only public format rules are implemented; proprietary libraries stay private.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

MAX_FILE = 64 * 1024 * 1024
MAX_ROWS = 200_000
DEFAULT_TYPES = (
    'Sce.PlayStation.PUI.UISystem', 'Sce.PlayStation.PUI.Application',
    'Sce.PlayStation.PUI.UISynchronizationContext',
    'Sce.PlayStation.PUI.UI2.Widget', 'Sce.PlayStation.PUI.UI2.Panel',
    'Sce.PlayStation.PUI.UI2.ImageBox', 'Sce.PlayStation.PUI.UI2.ImageAsset',
    'Sce.Vsh.ShellUI.AppSystem.LayerManager',
    'System.Threading.SynchronizationContext',
)


class MetadataError(ValueError):
    pass


def chunk(data: bytes, offset: int, size: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise MetadataError('Metadata range outside file/stream')
    return data[offset:offset + size]


def uint(data: bytes, offset: int, width: int) -> int:
    return int.from_bytes(chunk(data, offset, width), 'little')


def compressed(data: bytes, offset: int) -> tuple[int, int]:
    first = uint(data, offset, 1)
    if first < 0x80:
        return first, offset + 1
    if first < 0xc0:
        return ((first & 0x3f) << 8) | uint(data, offset + 1, 1), offset + 2
    if first < 0xe0:
        return int.from_bytes(chunk(data, offset, 4), 'big') & 0x1fffffff, offset + 4
    raise MetadataError('Invalid compressed integer')


class Metadata:
    def __init__(self, data: bytes, offset: int):
        if len(data) > MAX_FILE or chunk(data, offset, 4) != b'BSJB':
            raise MetadataError('Invalid metadata signature or file size')
        version_size = uint(data, offset + 12, 4)
        if not 1 <= version_size <= 256:
            raise MetadataError('Invalid runtime version length')
        version = chunk(data, offset + 16, version_size)
        self.version = version.rstrip(b'\0').decode('ascii', 'strict')
        cursor = offset + 16 + version_size
        count = uint(data, cursor + 2, 2)
        if not 1 <= count <= 16:
            raise MetadataError('Invalid stream count')
        cursor += 4
        entries = {}
        ranges = []
        for _ in range(count):
            start, size = struct.unpack('<II', chunk(data, cursor, 8))
            name_bytes = chunk(data, cursor + 8, min(32, len(data) - cursor - 8))
            end = name_bytes.find(b'\0')
            if end < 0:
                raise MetadataError('Unterminated stream name')
            name = name_bytes[:end].decode('ascii', 'strict')
            cursor += 8 + ((end + 1 + 3) & ~3)
            if name in entries:
                raise MetadataError('Duplicate metadata stream')
            entries[name] = chunk(data, offset + start, size)
            ranges.append((start, start + size))
        header_size = cursor - offset
        previous = header_size
        for start, end in sorted(ranges):
            if start < previous:
                raise MetadataError('Overlapping streams/header')
            previous = end
        if not {'#~', '#Strings', '#Blob'} <= entries.keys():
            raise MetadataError('Optimized tables, strings and blobs required')
        self.strings = entries['#Strings']
        self.blobs = entries['#Blob']
        tables = entries['#~']
        heap_sizes = uint(tables, 6, 1)
        valid = uint(tables, 8, 8)
        self.rows = [0] * 64
        cursor = 24
        for i in range(64):
            if valid & (1 << i):
                self.rows[i] = uint(tables, cursor, 4)
                cursor += 4
                if self.rows[i] > MAX_ROWS:
                    raise MetadataError('Metadata table exceeds row limit')
        if any(self.rows[i] for i in (3, 5, 7)):
            raise MetadataError('Pointer tables are not supported')
        string = 4 if heap_sizes & 1 else 2
        guid = 4 if heap_sizes & 2 else 2
        blob = 4 if heap_sizes & 4 else 2
        def index(table):
            return 4 if self.rows[table] >= 65536 else 2
        def coded(bits, candidates):
            return 4 if max(self.rows[i] for i in candidates) >= (1 << (16 - bits)) else 2
        layouts = (
            (2, string, guid, guid, guid),
            (coded(2, (0, 26, 35, 1)), string, string),
            (4, string, string, coded(2, (2, 1, 27)), index(4), index(6)),
            (index(4),), (2, string, blob), (index(6),),
            (4, 2, 2, string, blob, index(8)),
        )
        decoded = {}
        for table, layout in enumerate(layouts):
            width = sum(layout)
            chunk(tables, cursor, width * self.rows[table])
            if table in (1, 2, 6):
                records = []
                for _ in range(self.rows[table]):
                    values = []
                    for size in layout:
                        values.append(uint(tables, cursor, size))
                        cursor += size
                    records.append(values)
                decoded[table] = records
            else:
                cursor += width * self.rows[table]
        self.refs = decoded[1]
        self.types = decoded[2]
        self.methods = decoded[6]
        starts = [row[5] for row in self.types]
        if starts != sorted(starts) or any(not 1 <= n <= len(self.methods) + 1 for n in starts):
            raise MetadataError('Invalid TypeDef MethodList range')

    def text(self, offset: int) -> str:
        chunk(self.strings, offset, 1)
        end = self.strings.find(b'\0', offset, min(len(self.strings), offset + 4096))
        if end < 0:
            raise MetadataError('Unterminated/oversized string')
        return self.strings[offset:end].decode('utf-8', 'strict')

    def typename(self, coded: int) -> str:
        table, row = coded & 3, coded >> 2
        records = self.types if table == 0 else self.refs if table == 1 else None
        if records is None:
            if table == 2 and 1 <= row <= self.rows[27]:
                return f'TypeSpec#{row}'
            raise MetadataError('Invalid signature type token')
        if not 1 <= row <= len(records):
            raise MetadataError('Signature type token out of range')
        entry = records[row - 1]
        return '.'.join(filter(None, (self.text(entry[2]), self.text(entry[1]))))

    def signature(self, value: bytes) -> str:
        primitives = {1: 'void', 2: 'bool', 3: 'char', 4: 'sbyte', 5: 'byte',
                      6: 'short', 7: 'ushort', 8: 'int', 9: 'uint', 10: 'long',
                      11: 'ulong', 12: 'float', 13: 'double', 14: 'string',
                      24: 'nint', 25: 'nuint', 28: 'object'}
        position = 0
        def number():
            nonlocal position
            result, position = compressed(value, position)
            return result
        def kind(depth=0):
            nonlocal position
            if depth > 16:
                raise MetadataError('Signature nesting limit')
            code = uint(value, position, 1)
            position += 1
            if code in primitives:
                return primitives[code]
            if code in (0x11, 0x12):
                return self.typename(number())
            if code in (0x13, 0x1e):
                return ('!' if code == 0x13 else '!!') + str(number())
            if code in (0x0f, 0x10, 0x1d):
                return kind(depth + 1) + {0x0f: '*', 0x10: '&', 0x1d: '[]'}[code]
            if code == 0x15:
                base = kind(depth + 1)
                count = number()
                if count > 32:
                    raise MetadataError('Generic signature limit')
                return base + '<' + ', '.join(kind(depth + 1) for _ in range(count)) + '>'
            raise MetadataError(f'Unsupported signature element {code:#x}')
        convention = number()
        if convention & 0x10:
            number()  # Generic parameter count, not parameter types.
        count = number()
        if count > 256:
            raise MetadataError('Method parameter limit')
        result = kind()
        args = [kind() for _ in range(count)]
        if position != len(value):
            raise MetadataError('Trailing/unsupported signature bytes')
        return result + '(' + ', '.join(args) + ')'

    def report(self, selected: tuple[str, ...]) -> dict:
        found = []
        for index, row in enumerate(self.types):
            name = '.'.join(filter(None, (self.text(row[2]), self.text(row[1]))))
            if name not in selected:
                continue
            begin = row[5]
            end = self.types[index + 1][5] if index + 1 < len(self.types) else len(self.methods) + 1
            methods = []
            for i in range(begin, end):
                _, _, flags, name_index, blob_index, _ = self.methods[i - 1]
                size, start = compressed(self.blobs, blob_index)
                if size > 16384:
                    raise MetadataError('Oversized method signature')
                blob = chunk(self.blobs, start, size)
                try:
                    signature = self.signature(blob)
                except MetadataError:
                    signature = None  # Preserve raw bytes, do not invent a signature.
                methods.append({'token': f'0x{0x06000000 | i:08x}', 'name': self.text(name_index),
                                'static': bool(flags & 0x10), 'signature': signature,
                                'signature_hex': blob.hex()})
            found.append({'name': name, 'token': f'0x{0x02000000 | (index + 1):08x}', 'methods': methods})
        return {'runtime': self.version, 'types': found,
                'missing': sorted(set(selected) - {t['name'] for t in found}),
                'offline_only': True, 'render_validated': False}


def inspect(data: bytes, selected=DEFAULT_TYPES, offset: int | None = None) -> dict:
    if len(data) > MAX_FILE:
        raise MetadataError('File exceeds offline size limit')
    if offset is not None:
        return Metadata(data, offset).report(tuple(selected))
    candidates = []
    position = 0
    for _ in range(64):
        position = data.find(b'BSJB', position)
        if position < 0:
            break
        try:
            candidates.append(Metadata(data, position))
        except (MetadataError, UnicodeError):
            pass
        position += 4
    else:
        raise MetadataError('Too many metadata candidates; specify an offset')
    if len(candidates) != 1:
        raise MetadataError('Expected one valid metadata root; specify an offset')
    return candidates[0].report(tuple(selected))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--type', action='append', dest='types')
    parser.add_argument('--offset', type=lambda value: int(value, 0))
    args = parser.parse_args()
    try:
        with args.file.open('rb') as source:
            data = source.read(MAX_FILE + 1)
        print(json.dumps(inspect(data, args.types or DEFAULT_TYPES, args.offset), indent=2))
    except (OSError, MetadataError, UnicodeError) as exc:
        parser.exit(1, f'Offline inspection stopped: {exc}\n')


if __name__ == '__main__':
    main()
