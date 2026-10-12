"""Synthetic AOT container fixtures, not redistributed PS4 binaries."""
from ports.ps4 import offline_aot as aot
import struct
import pytest


def fixture(*, version=140, flags=3, opcode=0xe8, target=0x1000, symbol_size=456,
            guid=b'01234567-89ab-cdef-0123-456789abcdef\0'):
    data = bytearray(3000)
    data[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<H', data, 18, 62)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HH', data, 54, 56, 4)
    # Executable LOAD, data LOAD, Orbis libdata and DYNAMIC.
    segments = [(1, 5, 512, 0x1000, 200, 200),
                (1, 6, 800, 0x2000, 500, 500),
                (0x61000000, 0, 1400, 0, 500, 500),
                (2, 0, 2000, 0, 80, 80)]
    for i, (kind, perms, off, addr, size, memory) in enumerate(segments):
        struct.pack_into('<IIQQQQQQ', data, 64+i*56, kind, perms, off, addr, 0, size, memory, 1)
    data[512] = 0xc3
    entry = 0x1080
    data[640] = opcode
    struct.pack_into('<i', data, 641, target-(entry+5))
    struct.pack_into('<II', data, 800, version, 0)
    struct.pack_into('<Q', data, 800+8+7*8, entry)
    struct.pack_into('<Q', data, 800+8+19*8, 0x21c8)
    data[1256:1256+len(guid)] = guid
    struct.pack_into('<II', data, 800+8+33*8+3*4, 1, flags)
    name = aot.nid('mono_aot_file_info').encode() + b'#C#A\0'
    data[1500:1500+len(name)] = name
    struct.pack_into('<IBBHQQ', data, 1400, 0, 0x11, 0, 1, 0x2000, symbol_size)
    for i, (tag, value) in enumerate(((0x61000039, 0), (0x6100003f, 24),
                                    (0x61000035, 100), (0x61000037, len(name)), (0x6100003b, 24))):
        struct.pack_into('<QQ', data, 2000+i*16, tag, value)
    return bytes(data)


def test_resolves_relative_call_without_executing_it():
    image = aot.AotImage(fixture())
    assert image.version == 140 and image.flags == 3
    assert image.body('0x06000001') == 0x1000


def test_runtime_provided_sentinel_is_not_native_body():
    assert aot.AotImage(fixture(target=0x1080)).body('0x06000001') is None


def test_guid_is_bounded_and_canonical():
    assert aot.AotImage(fixture()).assembly_guid() == '01234567-89AB-CDEF-0123-456789ABCDEF'


@pytest.mark.parametrize('guid', [b'x'*36+b'\0', b'0'*37, b'0'*35+b'\0\0'])
def test_invalid_guid_is_rejected(guid):
    with pytest.raises(ValueError, match='GUID'):
        aot.AotImage(fixture(guid=guid)).assembly_guid()


@pytest.mark.parametrize('kwargs', [{'version': 139}, {'symbol_size': 448}, {'flags': 1}])
def test_unknown_aot_layout_is_never_guessed(kwargs):
    with pytest.raises(ValueError):
        aot.AotImage(fixture(**kwargs))


@pytest.mark.parametrize('target', [0x2000, 0x9999, -100])
def test_non_executable_or_unmapped_method_is_rejected(target):
    image = aot.AotImage(fixture(target=target))
    with pytest.raises(ValueError):
        image.body('0x06000001')


def test_unknown_call_encoding_is_rejected():
    with pytest.raises(ValueError, match='encoding'):
        aot.AotImage(fixture(opcode=0xe9)).body('0x06000001')


@pytest.mark.parametrize('token', ['0x02000001', '0x06000000', '0x06000002'])
def test_bad_method_token_is_rejected(token):
    with pytest.raises(ValueError, match='token'):
        aot.AotImage(fixture()).body(token)


def test_duplicate_required_tag_is_rejected():
    data = bytearray(fixture())
    struct.pack_into('<Q', data, 2016, 0x61000039)
    with pytest.raises(ValueError, match='Duplicate'):
        aot.AotImage(bytes(data))


def test_library_table_bounds_are_checked():
    data = bytearray(fixture())
    struct.pack_into('<Q', data, 2008, 499)
    with pytest.raises(ValueError, match='outside library'):
        aot.AotImage(bytes(data))


@pytest.mark.parametrize('data', [b'', b'\x7fELF', fixture()[:2100]])
def test_truncated_or_wrong_elf_is_rejected(data):
    # The truncated file is still complete for parsed ranges: corrupt a segment
    # range for that case rather than claim unused trailing bytes are required.
    if len(data) == 2100:
        data = bytearray(data)
        struct.pack_into('<Q', data, 64+3*56+32, 500)
        data = bytes(data)
    with pytest.raises(ValueError):
        aot.AotImage(data)


def test_orbis_nid_matches_public_aot_symbol():
    assert aot.nid('mono_aot_file_info') == 'RkSFw3znsvI'


def test_aot_tools_have_no_console_transport_or_executable_loading():
    import inspect
    source = inspect.getsource(aot)
    for word in ('import socket', 'import ftplib', 'import ctypes', 'subprocess', 'mprotect'):
        assert word not in source
