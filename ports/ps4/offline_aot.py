"""Offline native-body availability for the observed x64 Mono AOT v140 layout.

No console access, pointer calls, hooks or permission changes. Addresses are
relative virtual addresses in the PRIVATE file, not usable live addresses.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import uuid

if __package__:
    from .offline_metadata import MAX_FILE, MetadataError, chunk, inspect, uint
else:
    from offline_metadata import MAX_FILE, MetadataError, chunk, inspect, uint


def nid(name: str) -> str:
    # Public Orbis identifier format; uses stdlib hashing, not SDK code.
    digest = hashlib.sha1(name.encode('ascii') + bytes.fromhex('518d64a635ded8c1e6b039b1c3e55230')).digest()
    return base64.b64encode(digest[:8][::-1]).decode('ascii').rstrip('=').replace('/', '-')


class AotImage:
    def __init__(self, data: bytes):
        if len(data) > MAX_FILE or chunk(data, 0, 7) != b'\x7fELF\x02\x01\x01' or uint(data, 18, 2) != 62:
            raise MetadataError('Expected bounded ELF64 little-endian x86-64')
        self.data = data
        start = uint(data, 32, 8)
        width, count = uint(data, 54, 2), uint(data, 56, 2)
        if width != 56 or not 1 <= count <= 32:
            raise MetadataError('Invalid ELF program headers')
        self.loads = []
        dyn = library = None
        for i in range(count):
            kind, flags, file_offset, address, _, size, memory_size, _ = struct.unpack('<IIQQQQQQ', chunk(data, start+i*width, width))
            chunk(data, file_offset, size)
            if kind == 1:
                if size > memory_size:
                    raise MetadataError('ELF file segment larger than memory segment')
                self.loads.append((address, address+size, file_offset, flags))
            if kind == 2:
                if dyn is not None:
                    raise MetadataError('Duplicate dynamic segment')
                dyn = chunk(data, file_offset, size)
            if kind == 0x61000000:
                if library is not None:
                    raise MetadataError('Duplicate Orbis library-data segment')
                library = (file_offset, size)
        previous = -1
        for first, last, _, _ in sorted(self.loads):
            if first < previous:
                raise MetadataError('Overlapping ELF load segments')
            previous = last
        if dyn is None or library is None or len(dyn) % 16 or len(dyn) > 65536:
            raise MetadataError('Orbis dynamic/library data missing or invalid')
        tags = {}
        required = {0x61000039, 0x6100003f, 0x61000035, 0x61000037, 0x6100003b}
        for tag, value in struct.iter_unpack('<QQ', dyn):
            if tag not in required:
                continue
            if tag in tags:
                raise MetadataError('Duplicate dynamic tag')
            tags[tag] = value
        def table(tag, size_tag):
            if tag not in tags or size_tag not in tags:
                raise MetadataError('Required Orbis symbol-table tag missing')
            offset, size = tags[tag], tags[size_tag]
            if offset + size > library[1]:
                raise MetadataError('Symbol/string table outside library data')
            return chunk(data, library[0]+offset, size)
        symbols = table(0x61000039, 0x6100003f)
        strings = table(0x61000035, 0x61000037)
        if tags.get(0x6100003b) != 24 or len(symbols) % 24 or len(symbols) // 24 > 200_000:
            raise MetadataError('Invalid Orbis symbol entries')
        wanted = {nid('mono_aot_file_info'), 'mono_aot_file_info'}
        found = []
        for offset in range(0, len(symbols), 24):
            name, info, _, section, address, size = struct.unpack('<IBBHQQ', chunk(symbols, offset, 24))
            if not address or not section:
                continue
            chunk(strings, name, 1)
            end = strings.find(b'\0', name, min(name+4096, len(strings)))
            if end < 0:
                raise MetadataError('Invalid symbol name')
            if strings[name:end].decode('ascii', 'strict').split('#')[0] in wanted:
                if info & 15 != 1:
                    raise MetadataError('AOT info must be a data symbol')
                found.append((address, size))
        if len(found) != 1:
            raise MetadataError('Expected exactly one exported AOT info symbol')
        address, size = found[0]
        if size != 456:
            raise MetadataError('Unknown AOT info layout; do not guess fields')
        header = self.at(address, size)
        self.version = uint(header, 0, 4)
        if self.version != 140 or uint(header, 4, 4) != 0:
            raise MetadataError('Unsupported AOT version/alignment marker')
        self.guid_address = uint(header, 8+19*8, 8)
        self.method_table = uint(header, 8+7*8, 8)
        self.nmethods = uint(header, 8+33*8+3*4, 4)
        self.flags = uint(header, 8+33*8+4*4, 4)
        if not self.flags & 2 or not 1 <= self.nmethods <= 200_000:
            raise MetadataError('Expected bounded full-AOT method table')
        if not self.method_table:
            raise MetadataError('Native call table missing; LLVM-only layout not supported')
        self.at(self.method_table, self.nmethods*5, executable=True)

    def assembly_guid(self) -> str:
        text = self.at(self.guid_address, 37)
        if text[-1:] != b'\0':
            raise MetadataError('Unterminated AOT assembly GUID')
        try:
            return str(uuid.UUID(text[:-1].decode('ascii'))).upper()
        except (ValueError, UnicodeError) as exc:
            raise MetadataError('Invalid AOT assembly GUID') from exc

    def at(self, address: int, size: int, executable=False) -> bytes:
        for begin, end, offset, flags in self.loads:
            if begin <= address and address+size <= end and size >= 0:
                if executable and not flags & 1:
                    raise MetadataError('Native method body/table is not executable')
                return chunk(self.data, offset+address-begin, size)
        raise MetadataError('AOT virtual range not backed by file data')

    def body(self, token: str) -> int | None:
        value = int(token, 16)
        index = (value & 0xffffff) - 1
        if value >> 24 != 6 or not 0 <= index < self.nmethods:
            raise MetadataError('MethodDef token outside native table')
        entry = self.method_table+index*5
        data = self.at(entry, 5, executable=True)
        if data[0] != 0xe8:
            raise MetadataError('Unsupported native call-table encoding')
        target = entry+5+struct.unpack('<i', data[1:])[0]
        if target == self.method_table:
            return None  # Runtime-provided/missing body sentinel, not executable proof.
        self.at(target, 1, executable=True)
        return target


def report(data: bytes, selected=None) -> dict:
    metadata = inspect(data) if selected is None else inspect(data, selected)
    image = AotImage(data)
    result = {'sha256': hashlib.sha256(data).hexdigest(), 'aot_version': image.version,
              'full_aot': bool(image.flags & 2), 'native_method_count': image.nmethods,
              'offline_only': True, 'dispatch_validated': False, 'render_validated': False,
              'types': metadata['types'], 'missing': metadata['missing']}
    for cls in result['types']:
        for method in cls['methods']:
            address = image.body(method['token'])
            method['native_body'] = address is not None
            method['file_virtual_address'] = None if address is None else hex(address)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--type', action='append', dest='types')
    args = parser.parse_args()
    try:
        with args.file.open('rb') as source:
            data = source.read(MAX_FILE+1)
        print(json.dumps(report(data, args.types), indent=2))
    except (OSError, MetadataError, UnicodeError) as exc:
        parser.exit(1, f'Offline AOT inspection stopped: {exc}\n')


if __name__ == '__main__':
    main()
