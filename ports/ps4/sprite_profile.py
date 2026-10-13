"""PRIVATE preview contract generation. No transport or console execution."""
import argparse
from pathlib import Path
if __package__:
    from .dispatch_profile import contract, generate
    from .offline_aot import AotImage
    from .offline_metadata import MAX_FILE, MetadataError
else:
    from dispatch_profile import contract, generate
    from offline_aot import AotImage
    from offline_metadata import MAX_FILE, MetadataError

PREFIX = 'Sce.PlayStation.PUI.'
TYPES = {'APP': PREFIX+'Application', 'SCENE': PREFIX+'UI2.Scene',
         'ASSET': PREFIX+'ImageAsset', 'BOX': PREFIX+'UI2.ImageBox',
         'WIDGET': PREFIX+'UI2.Widget', 'NODE': PREFIX+'UINode'}
TYPES['MANAGER'] = PREFIX+'AssetManager'
TYPES['PROXY'] = PREFIX+'AssetProxy'
DISPOSE_BINDINGS = (('ASSET_DISPOSE', 'PROXY', 'Dispose', 'void()', False),)
ANIMATION_BOX = PREFIX+'UI2.AnimationImageBox'
VISIBLE_BINDINGS = (('BOX_SCALE', 'BOX', 'set_ImageScaleType',
                     'void('+PREFIX+'UI2.ImageScaleType)', False),)
ANIMATION_BINDINGS = (
    ('ANIM_WIDTH', 'BOX', 'set_FrameWidth', 'void(int)', False),
    ('ANIM_HEIGHT', 'BOX', 'set_FrameHeight', 'void(int)', False),
    ('ANIM_COUNT', 'BOX', 'set_FrameCount', 'void(int)', False),
    ('ANIM_INTERVAL', 'BOX', 'set_FrameInterval', 'void(float)', False),
    ('ANIM_START', 'BOX', 'Start', 'void()', False),
    ('ANIM_STOP', 'BOX', 'Stop', 'void()', False),
)
MANAGER_BINDINGS = (
    ('MANAGER_CTOR', 'MANAGER', '.ctor', 'void(string, uint)', False),
    ('MANAGER_LOAD', 'MANAGER', 'LoadImageAsset', PREFIX+'ImageAsset(string)', False),
    ('MANAGER_LIMIT', 'MANAGER', 'get_MaxSize', 'uint()', False),
    ('MANAGER_DISPOSE', 'MANAGER', 'Dispose', 'void()', False),
)
BINDINGS = (
    ('APP_INSTANCE', 'APP', 'get_Instance', PREFIX+'Application()', True),
    ('APP_ROOT', 'APP', 'get_RootScene', PREFIX+'SceneBase()', False),
    ('SCENE_ROOT', 'SCENE', 'get_RootWidget', PREFIX+'UI2.Widget()', False),
    ('ASSET_CTOR', 'ASSET', '.ctor', 'void(string)', False),
    ('ASSET_WIDTH', 'ASSET', 'get_Width', 'int()', False),
    ('ASSET_HEIGHT', 'ASSET', 'get_Height', 'int()', False),
    ('BOX_CTOR', 'BOX', '.ctor', 'void()', False),
    ('BOX_IMAGE', 'BOX', 'set_Image', 'void('+PREFIX+'ImageAsset)', False),
    ('WIDGET_TOUCH', 'WIDGET', 'set_TouchResponse', 'void(bool)', False),
    ('WIDGET_FOCUS', 'WIDGET', 'set_Focusable', 'void(bool)', False),
    ('WIDGET_APPEND', 'WIDGET', 'AppendChild', 'void('+PREFIX+'UI2.Widget)', False),
    ('WIDGET_REMOVE', 'WIDGET', 'RemoveFromParent', 'void()', False),
    ('WIDGET_DISPOSE', 'WIDGET', 'Dispose', 'void()', False),
    ('NODE_X', 'NODE', 'set_X', 'void(float)', False),
    ('NODE_Y', 'NODE', 'set_Y', 'void(float)', False),
    ('NODE_WIDTH', 'NODE', 'set_Width', 'void(float)', False),
    ('NODE_HEIGHT', 'NODE', 'set_Height', 'void(float)', False),
    ('NODE_VISIBLE', 'NODE', 'set_Visible', 'void(bool)', False),
    ('NODE_GET_WIDTH', 'NODE', 'get_Width', 'float()', False),
    ('NODE_GET_HEIGHT', 'NODE', 'get_Height', 'float()', False),
)


def preview_profile(pui, corlib, core, *, own_image_manager=False, dispose_image_asset=False, animated=False, scheduled_frames=False, visible_test=False, resident_client=False):
    if dispose_image_asset and not own_image_manager:
        raise MetadataError('Explicit asset disposal requires the own image manager')
    if animated and not (dispose_image_asset and own_image_manager):
        raise MetadataError('Animation requires explicit disposal and own image manager')
    if scheduled_frames and (animated or not (dispose_image_asset and own_image_manager)):
        raise MetadataError('Scheduled frames require static box, explicit disposal and own manager')
    if visible_test and not scheduled_frames:
        raise MetadataError('Visible test requires bounded scheduled frames')
    if resident_client and not visible_test:
        raise MetadataError('Resident client requires owner-controlled scaled frame mode')
    # Owner query and all three assembly GUID/MVID guards are mandatory.
    value = generate(pui, corlib, core)
    aot = AotImage(pui)
    classes, methods = {}, {}
    types = dict(TYPES, BOX=ANIMATION_BOX) if animated else TYPES
    bindings = (BINDINGS + (MANAGER_BINDINGS if own_image_manager else ()) +
                (DISPOSE_BINDINGS if dispose_image_asset else ()) +
                (ANIMATION_BINDINGS if animated else ()) +
                (VISIBLE_BINDINGS if visible_test else ()))
    for key, owner, name, signature, static in bindings:
        cls, matches = contract(pui, types[owner], {name: signature}, is_static=static)
        if owner in classes and classes[owner] != cls:
            raise MetadataError('Inconsistent preview class token')
        classes[owner] = cls
        token = matches[name]
        if aot.body(token) is None:
            raise MetadataError('Preview method has no verified native body')
        methods[key] = token
    value += '#define ARFOXIA_SPRITE_PROFILE_PRESENT 1\n'
    for key, token in classes.items():
        value += f'#define ARFOXIA_SPRITE_{key}_TYPE {token}u\n'
    for key, token in methods.items():
        value += f'#define ARFOXIA_SPRITE_{key} {token}u\n'
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pui', 'corlib', 'core', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--own-image-manager', action='store_true')
    parser.add_argument('--dispose-image-asset', action='store_true')
    parser.add_argument('--animated', action='store_true')
    parser.add_argument('--scheduled-frames', action='store_true')
    parser.add_argument('--visible-test', action='store_true')
    parser.add_argument('--resident-client',action='store_true')
    args = parser.parse_args()
    try:
        values = []
        for path in (args.pui, args.corlib, args.core):
            with path.open('rb') as stream: values.append(stream.read(MAX_FILE+1))
        value = preview_profile(*values, own_image_manager=args.own_image_manager,
                                dispose_image_asset=args.dispose_image_asset, animated=args.animated,
                                scheduled_frames=args.scheduled_frames, visible_test=args.visible_test,
                                resident_client=args.resident_client)
        with args.output.open('x', encoding='utf-8') as stream: stream.write(value)
        print('Private UI2 sprite contract generated. No console contact or enabling.')
    except (OSError, MetadataError, UnicodeError) as exc:
        parser.exit(1, f'Preview profile stopped: {exc}\n')


if __name__ == '__main__': main()
