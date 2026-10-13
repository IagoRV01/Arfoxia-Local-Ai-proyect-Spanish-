"""Extract unchanged PMD Walk pixels for the guarded PS4 frame experiment."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image


def export_walk(source, output):
    source, output = Path(source), Path(output)
    raw = source.read_bytes()
    with Image.open(source) as image:
        sheet = image.convert('RGBA')
    if sheet.size != (128, 320):
        raise ValueError('Expected existing four-frame/eight-direction 128x320 Walk sheet')
    frames = [sheet.crop((index*32, 0, (index+1)*32, 40)) for index in range(4)]
    if len({frame.tobytes() for frame in frames}) < 2:
        raise ValueError('Walk sheet has no distinct animation frames')
    # Exclusive output directory: never overwrite a previous asset package.
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for index, frame in enumerate(frames):
        name = f'walk-v7-{index}.png'
        frame.save(output / name, format='PNG')
        value = (output / name).read_bytes()
        records.append(dict(name=name, sha256=hashlib.sha256(value).hexdigest(), bytes=len(value)))
    manifest = dict(source_sha256=hashlib.sha256(raw).hexdigest(), width=32, height=40,
                    count=4, interval_us=166667, duration_seconds=15, frames=records)
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
    return manifest


def export_client(directory, output):
    """Existing right/left walk, sit and idle; preserve pixels in 32x40 cells."""
    from glaceon_companion.sprites import SpriteLibrary
    directory,output=Path(directory),Path(output)
    library=SpriteLibrary(directory)
    walk=library.specs['Walk']
    if (walk.width,walk.height,walk.durations,walk.copy_of) != (32,40,(10,10,10,10),None):
        raise ValueError('Unexpected existing Walk animation contract')
    for name,size in [('Sit',(32,32)),('Idle',(32,40))]:
        spec=library.specs[name]
        if (spec.width,spec.height) != size: raise ValueError('Unexpected pet pose dimensions')
    frames=library.frames('Walk',2)[0]+library.frames('Walk',6)[0]
    sitting=library.frames('Sit',0)[0][0]
    padded=Image.new('RGBA',(32,40)); padded.paste(sitting,(0,8))
    frames += [padded,library.frames('Idle',0)[0][0]]
    if len(frames) != 10 or any(frame.size != (32,40) for frame in frames):
        raise ValueError('Client frame package must contain ten 32x40 cells')
    output.mkdir(parents=True,exist_ok=False)
    records=[]
    for index,frame in enumerate(frames):
        name=f'pet-v9-{index}.png'
        frame.save(output/name,format='PNG')
        value=(output/name).read_bytes()
        records.append(dict(name=name,sha256=hashlib.sha256(value).hexdigest(),bytes=len(value)))
    manifest=dict(count=10,width=32,height=40,frames=records,
                  sources={name:hashlib.sha256((directory/(name+'-Anim.png')).read_bytes()).hexdigest()
                           for name in ('Walk','Sit','Idle')})
    with (output/'manifest.json').open('x',encoding='utf-8') as stream: json.dump(manifest,stream,indent=2)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--client-assets',action='store_true')
    args = parser.parse_args()
    try:
        (export_client if args.client_assets else export_walk)(args.source, args.output)
        print('Original-pixel frames exported. No console contact.')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Frame export stopped: {exc}\n')


if __name__ == '__main__': main()
