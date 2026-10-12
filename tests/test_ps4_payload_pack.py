import importlib.util
from pathlib import Path
import struct

import pytest

spec = importlib.util.spec_from_file_location('ps4_payload_pack', Path(__file__).parents[1] / 'ports/ps4/pack_payload.py')
packer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packer)


def fixture(*, elf_type=3, entry=0, extra_kind=8, extra_address=32, extra_size=16, interpreter=False):
    image = bytearray(400)
    image[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HH', image, 16, elf_type, 62)
    struct.pack_into('<QQQ', image, 24, entry, 64, 128)
    struct.pack_into('<HHHH', image, 54, 56, 1, 64, 3)
    struct.pack_into('<IIQQQQQQ', image, 64, 3 if interpreter else 1, 5, 320, 0, 0, 16, 48, 16)
    struct.pack_into('<IIQQQQIIQQ', image, 192, 0, 1, 6, 0, 320, 16, 0, 0, 16, 0)
    struct.pack_into('<IIQQQQIIQQ', image, 256, 0, extra_kind, 3, extra_address, 352, extra_size, 0, 0, 16, 0)
    image[320:336] = b'\xe9' + b'\x90'*15
    image[352:368] = b'\xff'*16  # NOBITS must NOT copy these bytes.
    return bytes(image)


def test_real_bss_is_materialized_as_zero_not_elf_bytes():
    payload = packer.pack(fixture())
    assert len(payload) == 48
    assert payload[:16] == b'\xe9' + b'\x90'*15
    assert payload[16:] == bytes(32)


def test_static_linker_relaxation_build_is_rejected():
    with pytest.raises(ValueError, match='PIE'):
        packer.pack(fixture(elf_type=2))


@pytest.mark.parametrize('kind', [4, 9])
def test_raw_loader_never_contains_runtime_relocations(kind):
    with pytest.raises(ValueError, match='unapplied relocations'):
        packer.pack(fixture(extra_kind=kind))


@pytest.mark.parametrize('kwargs,reason', [
    ({'entry': 16}, 'entry point'),
    ({'interpreter': True}, 'interpreter'),
    ({'extra_address': 65536}, 'size limit'),
    ({'extra_address': 8}, 'Overlapping'),
    ({'extra_kind': 1, 'extra_size': 100}, 'exceeds its ELF'),
])
def test_invalid_or_non_self_contained_images_are_rejected(kwargs, reason):
    with pytest.raises(ValueError, match=reason):
        packer.pack(fixture(**kwargs))


def test_dynamic_dependency_is_rejected():
    image = bytearray(fixture(extra_kind=6))
    struct.pack_into('<QQ', image, 352, 1, 0)
    with pytest.raises(ValueError, match='shared-library'):
        packer.pack(bytes(image))


@pytest.mark.parametrize('image', [b'', b'\x7fELF', bytes(64)])
def test_truncated_or_non_elf_input_is_rejected(image):
    with pytest.raises(ValueError, match='ELF64'):
        packer.pack(image)
