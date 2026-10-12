"""Owned synthetic contracts. No Sony files or console access in tests."""
import inspect
from pathlib import Path
import pytest
from ports.ps4 import dispatch_profile as profile


def row(name='.ctor', signature='void()', static=False, token='0x06000001'):
    return dict(name=name, signature=signature, static=static, token=token)


@pytest.mark.parametrize('methods', [[], [row(static=True)], [row(signature='void(int)')], [row(), row()]])
def test_missing_static_wrong_or_ambiguous_method_is_rejected(monkeypatch, methods):
    monkeypatch.setattr(profile, 'inspect', lambda *args: {'types': [{'token': '0x02000001', 'methods': methods}]})
    with pytest.raises(ValueError, match='signature'):
        profile.contract(b'', 'Owned.Context', {'.ctor': 'void()'})


@pytest.mark.parametrize('types', [[], [{}, {}]])
def test_exact_unique_type_required(monkeypatch, types):
    monkeypatch.setattr(profile, 'inspect', lambda *args: {'types': types})
    with pytest.raises(ValueError, match='type'):
        profile.contract(b'', 'Owned.Context', {'.ctor': 'void()'})


def test_instance_contract_is_exact(monkeypatch):
    monkeypatch.setattr(profile, 'inspect', lambda *args: {'types': [{'token': '0x02000001', 'methods': [row()]}]})
    assert profile.contract(b'', 'Owned.Context', {'.ctor': 'void()'}) == ('0x02000001', {'.ctor': '0x06000001'})


@pytest.mark.parametrize('native', [True, False])
def test_generation_requires_native_pui_but_allows_runtime_delegate_ctor(monkeypatch, native):
    def contract(data, *args):
        return ('0x02000001', {'.ctor': '0x06000001', 'Post': '0x06000002'} if data == b'pui' else {'.ctor': '0x06000001'})
    class OwnedAot:
        def __init__(self, data): self.data = data
        def body(self, token): return 0x1000 if self.data == b'pui' and native else None
        def assembly_guid(self): return '01234567-89AB-CDEF-0123-456789ABCDEF'
    monkeypatch.setattr(profile, 'contract', contract)
    monkeypatch.setattr(profile, 'AotImage', OwnedAot)
    monkeypatch.setattr(profile, 'parse', lambda data: OwnedModule())
    class OwnedModule:
        def module_guid(self): return '01234567-89AB-CDEF-0123-456789ABCDEF'
    if not native:
        with pytest.raises(ValueError, match='native AOT'):
            profile.generate(b'pui', b'corlib')
    else:
        value = profile.generate(b'pui', b'corlib')
        assert 'ARFOXIA_CALLBACK_CTOR 0x06000001u' in value
        assert 'ARFOXIA_PS4_DISPATCH_PROBE_ENABLED' not in value


def test_aot_guid_metadata_mismatch_stops_before_generating_profile(monkeypatch):
    class Aot:
        def __init__(self, data): pass
        def assembly_guid(self): return 'A'
    class Module:
        def module_guid(self): return 'B'
    monkeypatch.setattr(profile, 'contract', lambda *args: ('0x02000001', {}))
    monkeypatch.setattr(profile, 'AotImage', Aot)
    monkeypatch.setattr(profile, 'parse', lambda data: Module())
    with pytest.raises(ValueError, match='MVID'):
        profile.generate(b'', b'')


@pytest.mark.parametrize('body, match', [(True, True), (False, True), (True, False)])
def test_optional_owner_query_needs_static_boolean_native_body_and_matching_guid(monkeypatch, body, match):
    calls = []
    def contract(data, classname, names, **kwargs):
        calls.append((data, classname, names, kwargs))
        return ('0x02000001', {name: '0x06000001' for name in names})
    class Aot:
        def __init__(self, data): self.data = data
        def assembly_guid(self): return 'GUID'
        def body(self, token): return 1 if self.data != b'core' or body else None
    class Module:
        def __init__(self, data): self.data = data
        def module_guid(self): return 'GUID' if self.data != b'core' or match else 'OTHER'
    monkeypatch.setattr(profile, 'contract', contract)
    monkeypatch.setattr(profile, 'AotImage', Aot)
    monkeypatch.setattr(profile, 'parse', Module)
    if body and match:
        generated = profile.generate(b'pui', b'corlib', b'core')
        assert 'ARFOXIA_OWNER_PROFILE_PRESENT 1' in generated
        assert calls[-1][2] == {'get_IsMainThread': 'bool()'}
        assert calls[-1][3] == {'is_static': True}
    else:
        with pytest.raises(ValueError, match='Core ownership'):
            profile.generate(b'pui', b'corlib', b'core')


def test_profile_generation_cannot_contact_or_load_console():
    source = inspect.getsource(profile)
    assert ".open('x'," in source
    for forbidden in ('import socket', 'import ftplib', 'import ctypes', 'subprocess'):
        assert forbidden not in source


def test_candidate_source_guards_and_quarantine_stay_separate():
    root = Path(__file__).resolve().parents[1] / 'ports' / 'ps4'
    source = (root / 'native' / 'dispatch_probe.c').read_text()
    assert '#define ARFOXIA_PS4_DISPATCH_PROBE_ENABLED 0' in source
    assert source.index('PROFILE_MISMATCH') < source.index('mono_class_get(pui,')
    for forbidden in ('mono_class_from_name', 'mono_assembly_foreach', 'sceKernelGetThreadId', 'AssertRunningOnMainThread', 'CheckRunningOnMainThread'):
        assert forbidden not in source
    assert 'if (atomic_load(&posted)) return -1' in source
    assert '#define ARFOXIA_PS4_PROBE_QUARANTINED 1' in (root / 'native' / 'goldhen_abi.h').read_text()


def test_new_loader_is_disabled_and_does_not_reuse_failed_probe_or_logs():
    root = Path(__file__).resolve().parents[1] / 'ports' / 'ps4'
    source = (root / 'native' / 'dispatch_loader.c').read_text()
    assert '#define ARFOXIA_PS4_DISPATCH_LOADER_ENABLED 0' in source
    assert 'arfoxia_dispatch_candidate_v1.prx' in source
    assert 'arfoxia_probe.prx' not in source
    assert 'dispatch-load-v1.txt' in source and '0xa01' in source
    assert 'O_TRUNC' not in source and 'sleep(' not in source
    assert source.count('arfoxia_sdk(6, &request)') == 1


def test_enabled_and_disabled_build_objects_are_distinct():
    root = Path(__file__).resolve().parents[1] / 'ports' / 'ps4'
    source = (root / 'Makefile').read_text()
    assert 'dispatch_candidate.o:' in source and 'dispatch_probe.o:' in source
    assert 'dispatch_loader_candidate.o:' in source and 'dispatch_loader.o:' in source
    all_line = next(line for line in source.splitlines() if line.startswith('all:'))
    assert 'dispatch' not in all_line


def test_optional_owner_query_does_not_draw_or_disable_ui_checks():
    root = Path(__file__).resolve().parents[1] / 'ports' / 'ps4'
    source = (root / 'native' / 'dispatch_probe.c').read_text()
    assert '#define ARFOXIA_PS4_QUERY_UI_OWNER 0' in source
    assert 'CORE_IS_MAIN_THREAD' in source
    assert source.index('CORE_PROFILE_MISMATCH') < source.index('mono_class_get(core,')
    for forbidden in ('AssertRunningOnMainThread', 'CheckRunningOnMainThread', 'mprotect', 'ImageBox', 'Panel', 'Window'):
        assert forbidden not in source
