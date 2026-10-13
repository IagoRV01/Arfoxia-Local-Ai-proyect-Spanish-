import hashlib
import json
from PIL import Image
import pytest
from ports.ps4.frame_assets import export_walk


def sheet(path, size=(128,320)):
    image = Image.new('RGBA', size)
    for index in range(4):
        if size[0] >= (index+1)*32:
            image.paste((index*30, 100, 200, 255), (index*32,0,(index+1)*32,min(size[1],40)))
    image.save(path)
    return image


def test_export_preserves_pixels_order_and_source(tmp_path):
    source = tmp_path/'Walk.png'
    original = sheet(source)
    before = source.read_bytes()
    output = tmp_path/'frames'
    manifest = export_walk(source, output)
    assert source.read_bytes() == before
    assert manifest['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert manifest['count'] == 4 and manifest['interval_us'] == 166667
    for index, record in enumerate(manifest['frames']):
        frame = Image.open(output/record['name'])
        assert frame.size == (32,40)
        assert frame.tobytes() == original.crop((index*32,0,(index+1)*32,40)).tobytes()
        assert hashlib.sha256((output/record['name']).read_bytes()).hexdigest() == record['sha256']
    assert json.loads((output/'manifest.json').read_text()) == manifest


def test_export_never_overwrites_existing_directory(tmp_path):
    source = tmp_path/'Walk.png'
    sheet(source)
    output = tmp_path/'frames'
    output.mkdir()
    sentinel = output/'keep.txt'
    sentinel.write_text('preserve')
    with pytest.raises(FileExistsError): export_walk(source, output)
    assert sentinel.read_text() == 'preserve'


@pytest.mark.parametrize('size', [(32,40),(128,40),(128,321),(129,320)])
def test_invalid_sheet_dimensions_stop_before_output(tmp_path, size):
    source = tmp_path/'Walk.png'
    sheet(source, size)
    output = tmp_path/'frames'
    with pytest.raises(ValueError, match='128x320'): export_walk(source, output)
    assert not output.exists()


def test_identical_frames_rejected(tmp_path):
    source = tmp_path/'Walk.png'
    Image.new('RGBA',(128,320)).save(source)
    with pytest.raises(ValueError, match='distinct'): export_walk(source,tmp_path/'frames')

def test_client_frames_preserve_walk_pixels_and_bottom_align_sit(tmp_path,monkeypatch):
    import glaceon_companion.sprites as sprites
    from types import SimpleNamespace
    from ports.ps4.frame_assets import export_client
    class Library:
        def __init__(self,directory):
            self.specs={'Walk':SimpleNamespace(width=32,height=40,durations=(10,10,10,10),copy_of=None),
                        'Sit':SimpleNamespace(width=32,height=32),'Idle':SimpleNamespace(width=32,height=40)}
        def frames(self,name,direction):
            size=(32,32) if name=='Sit' else (32,40)
            return [Image.new('RGBA',size,(direction*20,index*40,100,255)) for index in range(4 if name=='Walk' else 1)],(167,)
    monkeypatch.setattr(sprites,'SpriteLibrary',Library)
    for name in ('Walk','Sit','Idle'): (tmp_path/(name+'-Anim.png')).write_bytes(b'owned')
    output=tmp_path/'client'
    result=export_client(tmp_path,output)
    assert result['count']==10
    assert Image.open(output/'pet-v9-0.png').getpixel((0,0))==(40,0,100,255)
    assert Image.open(output/'pet-v9-4.png').getpixel((0,0))==(120,0,100,255)
    sitting=Image.open(output/'pet-v9-8.png')
    assert sitting.getpixel((0,0))==(0,0,0,0) and sitting.getpixel((0,8))==(0,0,100,255)
