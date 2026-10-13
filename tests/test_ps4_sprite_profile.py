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
        owner = 'BOX' if classname == profile.ANIMATION_BOX else next(k for k, v in profile.TYPES.items() if v == classname)
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


def test_image_disposal_contract_is_exact_and_native(monkeypatch):
    calls = mocks(monkeypatch)
    result = profile.preview_profile(b'', b'', b'', own_image_manager=True, dispose_image_asset=True)
    assert len(calls) == 25
    assert calls[-1] == (profile.TYPES['PROXY'], {'Dispose': 'void()'}, False)
    assert 'ARFOXIA_SPRITE_ASSET_DISPOSE' in result
    mocks(monkeypatch, missing='0x06000019')
    with pytest.raises(ValueError, match='native body'):
        profile.preview_profile(b'', b'', b'', own_image_manager=True, dispose_image_asset=True)


def test_explicit_image_disposal_requires_owned_manager():
    with pytest.raises(ValueError, match='own image manager'):
        profile.preview_profile(b'', b'', b'', dispose_image_asset=True)


def test_owned_image_is_disposed_before_releasing_roots_and_manager():
    root = Path(__file__).resolve().parents[1] / 'ports/ps4'
    cleanup = (root / 'native/sprite_preview.h').read_text().split('static void preview_cleanup')[1]
    assert cleanup.index('PHASE_DISPOSE_SPRITE') < cleanup.index('PHASE_DISPOSE_OWN_IMAGE')
    assert cleanup.index('PHASE_DISPOSE_OWN_IMAGE') < cleanup.index('mono_gchandle_free(preview_asset_handle)')
    assert cleanup.index('PHASE_DISPOSE_OWN_IMAGE') < cleanup.index('PHASE_DISPOSE_OWN_MANAGER')


def test_animated_box_replaces_static_box_and_checks_exact_methods(monkeypatch):
    calls = mocks(monkeypatch)
    result = profile.preview_profile(b'', b'', b'', own_image_manager=True, dispose_image_asset=True, animated=True)
    assert len(calls) == 31
    assert calls[6] == (profile.ANIMATION_BOX, {'.ctor': 'void()'}, False)
    assert calls[7] == (profile.ANIMATION_BOX, {'set_Image': 'void('+profile.PREFIX+'ImageAsset)'}, False)
    for call, (key, owner, name, signature, static) in zip(calls[-6:], profile.ANIMATION_BINDINGS):
        assert call == (profile.ANIMATION_BOX, {name: signature}, static)
        assert 'ARFOXIA_SPRITE_'+key in result


@pytest.mark.parametrize('index', range(26, 32))
def test_each_animation_body_must_exist(monkeypatch, index):
    mocks(monkeypatch, missing=f'0x060000{index:02x}')
    with pytest.raises(ValueError, match='native body'):
        profile.preview_profile(b'', b'', b'', own_image_manager=True, dispose_image_asset=True, animated=True)


@pytest.mark.parametrize('manager, disposal', [(False, False), (True, False)])
def test_animation_cannot_skip_owned_image_cleanup(manager, disposal):
    with pytest.raises(ValueError, match='Animation requires'):
        profile.preview_profile(b'', b'', b'', own_image_manager=manager, dispose_image_asset=disposal, animated=True)


def test_animation_uses_builtin_start_stop_without_per_frame_worker_calls():
    root = Path(__file__).resolve().parents[1] / 'ports/ps4'
    source = (root / 'native/dispatch_probe.c').read_text()
    header = (root / 'native/sprite_preview.h').read_text()
    assert '#define ARFOXIA_PS4_ANIMATED_PREVIEW 0' in source
    assert '#error Animation requires explicit owned image disposal' in source
    assert 'pixel_width != 128 || pixel_height != 320' in header
    assert 'frame_width = 32, frame_height = 40, frame_count = 4' in header
    assert 'preview_ANIM_INTERVAL, box, 1000.0f/6.0f' in header
    cleanup = header.split('static void preview_cleanup')[1]
    assert cleanup.index('PHASE_STOP_ANIMATION') < cleanup.index('PHASE_REMOVE_SPRITE')
    worker = header.split('static void *preview_wait_then_remove')[1]
    assert 'preview_ANIM_' not in worker


def test_scheduled_frames_use_the_proven_static_box(monkeypatch):
    calls = mocks(monkeypatch)
    profile.preview_profile(b'',b'',b'',own_image_manager=True,dispose_image_asset=True,scheduled_frames=True)
    assert len(calls) == 25
    assert calls[6][0] == profile.TYPES['BOX']


@pytest.mark.parametrize('manager, disposal, animated', [(False,False,False),(True,False,False),(True,True,True)])
def test_scheduled_mode_rejects_unsafe_or_conflicting_configuration(manager,disposal,animated):
    with pytest.raises(ValueError, match='Scheduled frames'):
        profile.preview_profile(b'',b'',b'',own_image_manager=manager,dispose_image_asset=disposal,
                                animated=animated,scheduled_frames=True)


def test_scheduled_mode_is_bounded_owner_checked_and_halts_before_cleanup():
    root = Path(__file__).resolve().parents[1]/'ports/ps4'
    header = (root/'native/sprite_preview.h').read_text()
    tick = header.split('static void preview_tick')[1].split('static int preview_show')[0]
    assert 'mono_runtime_invoke(owner_query' in tick
    assert tick.index('FRAME_NOT_ON_UI_HALTED') < tick.index('invoke(preview_BOX_IMAGE')
    assert 'atomic_load(&preview_frames_halted)' in tick
    assert 'atomic_store(&preview_tick_pending, 0)' in tick
    worker = header.split('static void *preview_wait_then_remove')[1]
    assert 'tick<90' in worker and 'sceKernelUsleep(166667)' in worker
    assert 'atomic_compare_exchange_strong(&preview_tick_pending' in worker
    assert 'preview_BOX_IMAGE' not in worker
    cleanup = header.split('static void preview_cleanup')[1].split('static void *preview_wait_then_remove')[0]
    assert cleanup.index('atomic_store(&preview_frames_halted, 1)') < cleanup.index('PHASE_REMOVE_SPRITE')
    assert cleanup.index('PHASE_DISPOSE_OWN_FRAME') < cleanup.index('PHASE_DISPOSE_OWN_MANAGER')


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
