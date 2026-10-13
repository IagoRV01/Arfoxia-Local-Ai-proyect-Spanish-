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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        export_walk(args.source, args.output)
        print('Four original-pixel frames exported. No console contact.')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Frame export stopped: {exc}\n')


if __name__ == '__main__': main()
