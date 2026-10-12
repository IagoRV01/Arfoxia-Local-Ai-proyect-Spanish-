"""Synthetic public-format fixtures only; no console libraries in the repo."""
import importlib.util
from pathlib import Path
import struct

import pytest

spec = importlib.util.spec_from_file_location('ps4_offline_metadata', Path(__file__).parents[1] / 'ports/ps4/offline_metadata.py')
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


def fixture(*, signature=b'\x00\x01\x01\x0e', large_heaps=False, pointer=False, method_start=1):
    strings = b'\0TestWidget\0Test.UI\0Post\0'
    # TypeDef and MethodDef. No proprietary names/bytecode or executable code.
    tables = bytearray(struct.pack('<IBBBBQQ', 0, 2, 0, 5 if large_heaps else 0, 1,
                                   (1 << 2) | (1 << 6) | ((1 << 3) if pointer else 0), 0))
    tables += struct.pack('<I', 1)
    if pointer:
        tables += struct.pack('<I', 1)
    tables += struct.pack('<I', 1)
    if large_heaps:
        tables += struct.pack('<IIIHHH', 0, 1, 12, 0, 1, method_start)
    else:
        tables += struct.pack('<IHHHHH', 0, 1, 12, 0, 1, method_start)
    if pointer:
        tables += b'\x01\0'
    if large_heaps:
        tables += struct.pack('<IHHIIH', 0, 0, 0x10, 20, 1, 1)
    else:
        tables += struct.pack('<IHHHHH', 0, 0, 0x10, 20, 1, 1)
    streams = [(b'#~', bytes(tables)), (b'#Strings', strings), (b'#Blob', b'\0' + bytes([len(signature)]) + signature)]
    header = bytearray(b'BSJB' + struct.pack('<HHII', 1, 1, 0, 12) + b'v4.0.30319\0\0' + struct.pack('<HH', 0, 3))
    first = len(header) + sum(8 + ((len(name) + 4) & ~3) for name, _ in streams)
    body = bytearray()
    for name, data in streams:
        header += struct.pack('<II', first + len(body), len(data))
        header += (name + b'\0').ljust((len(name) + 4) & ~3, b'\0')
        body += data
    return bytes(header + body)


def report(data):
    return offline.inspect(data, ('Test.UI.TestWidget', 'Missing.Type'))


@pytest.mark.parametrize('large', [False, True])
def test_reads_signatures_and_tokens_without_loading_runtime(large):
    result = report(fixture(large_heaps=large))
    assert result['offline_only'] and not result['render_validated']
    assert result['missing'] == ['Missing.Type']
    cls = result['types'][0]
    assert cls['token'] == '0x02000001'
    assert cls['methods'] == [{'name': 'Post', 'token': '0x06000001', 'static': True,
                              'signature': 'void(string)', 'signature_hex': '0001010e'}]


def test_finds_embedded_metadata_and_skips_false_magic():
    result = report(b'ELF private bytes BSJB' + b'\0' * 300 + fixture())
    assert result['types'][0]['name'] == 'Test.UI.TestWidget'


def test_rejects_ambiguous_metadata_instead_of_guessing():
    data = fixture() + fixture()
    with pytest.raises(ValueError, match='one valid'):
        report(data)
    assert offline.inspect(data, ('Test.UI.TestWidget',), offset=len(fixture()))['types']


@pytest.mark.parametrize('data', [b'', b'BSJB', fixture()[:-1], fixture(pointer=True), fixture(method_start=0)])
def test_malformed_metadata_is_rejected(data):
    with pytest.raises(ValueError):
        report(data)


def test_overlapping_stream_header_is_rejected():
    data = bytearray(fixture())
    struct.pack_into('<I', data, 32, 0)
    with pytest.raises(ValueError, match='one valid'):
        report(bytes(data))


def test_oversized_row_count_is_rejected_before_allocating(monkeypatch):
    monkeypatch.setattr(offline, 'MAX_ROWS', 0)
    with pytest.raises(ValueError):
        report(fixture())


def test_file_limit_applies_before_scanning(monkeypatch):
    monkeypatch.setattr(offline, 'MAX_FILE', 10)
    with pytest.raises(ValueError, match='size limit'):
        report(fixture())


def test_unsupported_signature_is_explicit_not_invented():
    method = report(fixture(signature=b'\0\0\xff'))['types'][0]['methods'][0]
    assert method['signature'] is None and method['signature_hex'] == '0000ff'


@pytest.mark.parametrize('raw,value,end', [(b'\x7f', 127, 1), (b'\x81\x80', 384, 2),
                                          (b'\xc0\x01\0\0', 65536, 4)])
def test_compressed_integer_widths(raw, value, end):
    assert offline.compressed(raw, 0) == (value, end)


@pytest.mark.parametrize('raw', [b'\xff', b'\x81', b'\xc0\0'])
def test_bad_compressed_integer_is_rejected(raw):
    with pytest.raises(ValueError):
        offline.compressed(raw, 0)


def test_signature_type_reference_and_parameter_limits():
    metadata = offline.Metadata(fixture(), 0)
    assert metadata.signature(bytes.fromhex('00001204')) == 'Test.UI.TestWidget()'
    with pytest.raises(ValueError, match='out of range'):
        metadata.signature(bytes.fromhex('00001208'))
    with pytest.raises(ValueError, match='parameter limit'):
        metadata.signature(bytes.fromhex('00810101'))


def test_cli_reports_invalid_file_without_traceback(tmp_path, monkeypatch, capsys):
    import sys
    path = tmp_path / 'not-executable.txt'
    path.write_bytes(b'not metadata')
    monkeypatch.setattr(sys, 'argv', ['offline_metadata.py', str(path)])
    with pytest.raises(SystemExit) as exc:
        offline.main()
    assert exc.value.code == 1
    assert 'Offline inspection stopped:' in capsys.readouterr().err
