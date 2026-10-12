"""Generate an OWNED, private compile profile. Never enables or loads a probe."""
import argparse
from pathlib import Path

if __package__:
    from .offline_metadata import MAX_FILE, MetadataError, inspect, parse
    from .offline_aot import AotImage
else:
    from offline_metadata import MAX_FILE, MetadataError, inspect, parse
    from offline_aot import AotImage


def contract(data, classname, names, *, is_static=False):
    types = inspect(data, (classname,))['types']
    if len(types) != 1:
        raise MetadataError('Required exact type missing from profile input')
    cls = types[0]
    selected = {}
    for name, signature in names.items():
        methods = [m for m in cls['methods'] if m['name'] == name and m['signature'] == signature and m['static'] == is_static]
        if len(methods) != 1:
            raise MetadataError('Required unambiguous method signature/staticness missing')
        selected[name] = methods[0]['token']
    return cls['token'], selected


def generate(pui, corlib, core=None):
    pui_type, pui_methods = contract(pui, 'Sce.PlayStation.PUI.UISynchronizationContext',
        {'.ctor': 'void()', 'Post': 'void(System.Threading.SendOrPostCallback, object)'})
    callback_type, callback_methods = contract(corlib, 'System.Threading.SendOrPostCallback',
        {'.ctor': 'void(object, nint)'})
    pui_aot, corlib_aot = AotImage(pui), AotImage(corlib)
    for data, aot in ((pui, pui_aot), (corlib, corlib_aot)):
        if parse(data).module_guid() != aot.assembly_guid():
            raise MetadataError('AOT GUID does not match metadata Module MVID')
    for token in pui_methods.values():
        if pui_aot.body(token) is None:
            raise MetadataError('Required PUI method has no native AOT body')
    value = ('/* PRIVATE generated metadata contract; do not publish. Does NOT enable loading. */\n'
            '#define ARFOXIA_DISPATCH_PROFILE_PRESENT 1\n'
            f'#define ARFOXIA_PUI_GUID "{pui_aot.assembly_guid()}"\n'
            f'#define ARFOXIA_CORLIB_GUID "{corlib_aot.assembly_guid()}"\n'
            f'#define ARFOXIA_CONTEXT_TYPE {pui_type}u\n'
            f'#define ARFOXIA_CONTEXT_CTOR {pui_methods[".ctor"]}u\n'
            f'#define ARFOXIA_CONTEXT_POST {pui_methods["Post"]}u\n'
            f'#define ARFOXIA_CALLBACK_TYPE {callback_type}u\n'
            f'#define ARFOXIA_CALLBACK_CTOR {callback_methods[".ctor"]}u\n')
    if core is not None:
        owner_type, owner_methods = contract(core, 'Sce.PlayStation.Core.Runtime.Diagnostics',
            {'get_IsMainThread': 'bool()'}, is_static=True)
        core_aot = AotImage(core)
        if core_aot.assembly_guid() != parse(core).module_guid() or core_aot.body(owner_methods['get_IsMainThread']) is None:
            raise MetadataError('Core ownership query requires matching MVID/native AOT body')
        value += ('#define ARFOXIA_OWNER_PROFILE_PRESENT 1\n'
                  f'#define ARFOXIA_CORE_GUID "{core_aot.assembly_guid()}"\n'
                  f'#define ARFOXIA_OWNER_TYPE {owner_type}u\n'
                  f'#define ARFOXIA_OWNER_QUERY {owner_methods["get_IsMainThread"]}u\n')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pui', type=Path, required=True)
    parser.add_argument('--corlib', type=Path, required=True)
    parser.add_argument('--core', type=Path, help='Optional private Core library for the read-only ownership query')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        values = []
        for path in (args.pui, args.corlib) + ((args.core,) if args.core else ()):
            with path.open('rb') as source:
                values.append(source.read(MAX_FILE+1))
        value = generate(*values)
        # Generated artifact only; exclusive creation preserves earlier profiles.
        with args.output.open('x', encoding='utf-8') as target:
            target.write(value)
        print('Private profile generated. Probe remains disabled; no console contact.')
    except (OSError, MetadataError, UnicodeError) as exc:
        parser.exit(1, f'Profile generation stopped: {exc}\n')


if __name__ == '__main__':
    main()
