"""Synthetic preview contracts; no Sony data, console contact or execution."""
import inspect
from pathlib import Path
import pytest
from ports.ps4 import sprite_profile as profile


def mocks(monkeypatch, *, missing=None, inconsistent=False):
    calls = []
    classes = {owner: f'0x020000{i+1:02x}' for i, owner in enumerate(profile.TYPES)}
    def contract(data, classname, names, *, is_static):
        calls.append((classname, names, is_static))
        owner = next(k for k, v in profile.TYPES.items() if v == classname)
        cls = classes[owner]
        if inconsistent and len(calls) == 2: cls = '0x020000ff'
        return cls, {name: f'0x060000{len(calls):02x}' for name in names}
    class Aot:
        def __init__(self, data): pass
        def body(self, token): return None if token == missing else 4096
    monkeypatch.setattr(profile, 'generate', lambda *args: '/* owner and GUID guards */\n')
    monkeypatch.setattr(profile, 'contract', contract)
    monkeypatch.setattr(profile, 'AotImage', Aot)
    return calls


def test_exact_overloads_staticness_and_native_bodies(monkeypatch):
    calls = mocks(monkeypatch)
    generated = profile.preview_profile(b'pui', b'corlib', b'core')
    assert len(calls) == 20
    for call, binding in zip(calls, profile.BINDINGS):
        key, owner, name, signature, static = binding
        assert call == (profile.TYPES[owner], {name: signature}, static)
        assert f'ARFOXIA_SPRITE_{key} ' in generated
    assert ('WIDGET_APPEND', 'WIDGET', 'AppendChild',
            'void(Sce.PlayStation.PUI.UI2.Widget)', False) in profile.BINDINGS
    assert 'ARFOXIA_PS4_SPRITE_PREVIEW' not in generated


@pytest.mark.parametrize('index', range(1, 21))
def test_each_missing_native_body_stops_generation(monkeypatch, index):
    mocks(monkeypatch, missing=f'0x060000{index:02x}')
    with pytest.raises(ValueError, match='native body'):
        profile.preview_profile(b'', b'', b'')


def test_inconsistent_owner_class_stops(monkeypatch):
    mocks(monkeypatch, inconsistent=True)
    with pytest.raises(ValueError, match='class token'):
        profile.preview_profile(b'', b'', b'')


def test_own_manager_uses_named_bounded_instance_only(monkeypatch):
    calls = mocks(monkeypatch)
    generated = profile.preview_profile(b'', b'', b'', own_image_manager=True)
    assert len(calls) == 24
    assert calls[-4] == (profile.TYPES['MANAGER'], {'.ctor': 'void(string, uint)'}, False)
    assert calls[-3] == (profile.TYPES['MANAGER'], {'LoadImageAsset': profile.PREFIX+'ImageAsset(string)'}, False)
    assert 'ARFOXIA_SPRITE_MANAGER_TYPE' in generated
    assert 'InitializeDefaultAssetManager' not in generated


@pytest.mark.parametrize('index', range(21, 25))
def test_own_manager_requires_each_native_body(monkeypatch, index):
    mocks(monkeypatch, missing=f'0x060000{index:02x}')
    with pytest.raises(ValueError, match='native body'):
        profile.preview_profile(b'', b'', b'', own_image_manager=True)


def test_requires_core_and_offline_exclusive_output():
    assert inspect.signature(profile.preview_profile).parameters['core'].default is inspect.Parameter.empty
    source = inspect.getsource(profile)
    assert ".open('x'," in source
    for forbidden in ('import socket', 'import ftplib', 'import ctypes', 'subprocess'):
        assert forbidden not in source


def test_preview_is_explicit_passive_owned_and_temporary():
    root = Path(__file__).resolve().parents[1] / 'ports/ps4'
    source = (root / 'native/dispatch_probe.c').read_text()
    header = (root / 'native/sprite_preview.h').read_text()
    build = (root / 'Makefile').read_text()
    assert '#define ARFOXIA_PS4_SPRITE_PREVIEW 0' in source
    assert '#error Sprite preview requires the UI owner query' in source
    assert source.index('CORE_PROFILE_MISMATCH') < source.index('preview_prepare(pui,')
    assert 'if (!*(const unsigned char *)value)' in source
    assert 'preview_WIDGET_TOUCH, box, 0' in header
    assert 'preview_WIDGET_FOCUS, box, 0' in header
    assert 'mono_object_isinst(scene, preview_scene_class)' in header
    assert '15000000' in header
    assert 'preview_WIDGET_REMOVE, box' in header
    assert 'PHASE_CLEANUP_UI_OWNER' in header
    assert 'CLEANUP_NOT_ON_UI_RETAIN_ROOTS' in header
    assert 'uint32_t limit = 262144' in header
    assert 'actual_limit != limit' in header
    assert 'PHASE_DISPOSE_OWN_MANAGER' in header
    for forbidden in ('InitializeDefaultAssetManager', 'InitializeSystemAssetManager', 'IgnoreAssetManagerSizeLimit'):
        assert forbidden not in header
    all_line = next(line for line in build.splitlines() if line.startswith('all:'))
    assert 'sprite' not in all_line
    assert 'build/dispatch_sprite_profile.h' in build
    for forbidden in ('mprotect', 'AssertRunningOnMainThread', 'CheckRunningOnMainThread', 'plugins.ini'):
        assert forbidden not in source + header
