import struct
import uuid
import pytest
from ports.ps4.offline_metadata import parse


def fixture(index=1, large=False):
    guid = uuid.UUID('01234567-89ab-cdef-0123-456789abcdef')
    tables = struct.pack('<IBBBBQQI', 0, 2, 0, 2 if large else 0, 1, 1, 0, 1)
    tables += struct.pack('<HHIII' if large else '<HHHHH', 0, 0, index, 0, 0)
    streams = [(b'#~', tables), (b'#Strings', b'\0'), (b'#Blob', b'\0'), (b'#GUID', guid.bytes_le)]
    header = bytearray(b'BSJB' + struct.pack('<HHII', 1, 1, 0, 12) + b'v4.0.30319\0\0' + struct.pack('<HH', 0, 4))
    start = len(header) + sum(8 + ((len(name)+4) & ~3) for name, _ in streams)
    body = bytearray()
    for name, data in streams:
        header += struct.pack('<II', start+len(body), len(data))
        header += (name+b'\0').ljust((len(name)+4) & ~3, b'\0')
        body += data
    return bytes(header+body)


@pytest.mark.parametrize('large', [True, False])
def test_mvid_endianness_and_heap_width(large):
    assert parse(fixture(large=large)).module_guid() == '01234567-89AB-CDEF-0123-456789ABCDEF'


@pytest.mark.parametrize('index', [0, 2, 65535])
def test_mvid_missing_or_outside_heap_rejected(index):
    with pytest.raises(ValueError):
        parse(fixture(index=index)).module_guid()
