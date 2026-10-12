"""Validate and flatten a self-contained PIE ELF into a raw BinLoader image.

Raw BinLoader does not apply ELF relocations or run a dynamic linker. Include
zero-filled BSS explicitly instead of depending on the receiver's spare buffer.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

MAX_IMAGE = 64 * 1024


def pack(elf: bytes) -> bytes:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)

    require(len(elf) >= 64 and elf[:7] == b'\x7fELF\x02\x01\x01', 'Expected little-endian ELF64')
    kind, machine = struct.unpack_from('<HH', elf, 16)
    require(kind == 3 and machine == 62, 'Raw payload must be an x86-64 PIE (ET_DYN), not ET_EXEC')
    entry, phoff, shoff = struct.unpack_from('<QQQ', elf, 24)
    phsize, phcount, shsize, shcount = struct.unpack_from('<HHHH', elf, 54)
    require(entry == 0, 'Raw entry point must be at byte zero')
    require(phsize == 56 and 0 < phcount <= 64 and phoff + phcount * phsize <= len(elf), 'Invalid program table')
    for index in range(phcount):
        program = struct.unpack_from('<IIQQQQQQ', elf, phoff + index * phsize)
        require(program[0] != 3, 'Raw payload cannot have a dynamic interpreter')
    require(shsize == 64 and 0 < shcount <= 512 and shoff + shcount * shsize <= len(elf), 'Invalid section table')
    sections = []
    for index in range(shcount):
        _, kind, flags, address, offset, size, _, _, _, _ = struct.unpack_from('<IIQQQQIIQQ', elf, shoff + index * shsize)
        require(kind not in (4, 9) or size == 0, 'Raw payload contains unapplied relocations')
        if kind == 6:  # SHT_DYNAMIC
            require(offset + size <= len(elf) and size % 16 == 0, 'Invalid dynamic table')
            for position in range(offset, offset + size, 16):
                tag, _ = struct.unpack_from('<QQ', elf, position)
                require(tag != 1, 'Raw payload has an external shared-library dependency')
        if flags & 2 and size:  # SHF_ALLOC
            require(address + size <= MAX_IMAGE, 'Payload image exceeds the size limit')
            require(kind == 8 or offset + size <= len(elf), 'Section exceeds its ELF input')
            sections.append((address, size, flags, None if kind == 8 else elf[offset:offset + size]))
    require(bool(sections), 'No allocated sections')
    sections.sort(key=lambda section: section[0])
    require(sections[0][0] == 0 and sections[0][2] & 4, 'Byte zero must be executable code')
    image = bytearray(max(address + size for address, size, _, _ in sections))
    end = 0
    for address, size, _, data in sections:
        require(address >= end, 'Overlapping allocated sections')
        if data is not None:
            image[address:address + size] = data
        end = address + size
    require(image[:1] == b'\xe9', 'Expected SDK entry jump at byte zero')
    return bytes(image)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    image = pack(args.elf.read_bytes())
    args.output.write_bytes(image)
    print(f'Validated relocatable raw payload: {len(image)} bytes, including zero BSS')


if __name__ == '__main__':
    main()
