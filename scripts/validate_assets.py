#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def validate_variant(path: Path) -> list[str]:
    errors: list[str] = []
    xml = path / "AnimData.xml"
    if not xml.exists():
        return [f"Falta {xml}"]
    tree = ElementTree.parse(xml)
    for anim in tree.findall("./Anims/Anim"):
        name = anim.findtext("Name") or ""
        copy_of = anim.findtext("CopyOf")
        if copy_of:
            continue
        width = int(anim.findtext("FrameWidth") or "0")
        height = int(anim.findtext("FrameHeight") or "0")
        count = len(anim.findall("./Durations/Duration"))
        sheet = path / f"{name}-Anim.png"
        if not sheet.exists():
            errors.append(f"Falta {sheet.name}")
            continue
        with Image.open(sheet) as image:
            if image.width < width * count or image.height < height or image.height % height:
                errors.append(
                    f"{sheet.name}: {image.size}; ancho mínimo {width * count}, "
                    f"altura múltiplo de {height}"
                )
    return errors


def validate_cries(path: Path) -> list[str]:
    errors: list[str] = []
    for variant in ("latest", "legacy"):
        audio = path / f"glaceon-{variant}.ogg"
        if not audio.exists():
            errors.append(f"Falta {audio.name}")
        elif audio.stat().st_size < 1000 or audio.read_bytes()[:4] != b"OggS":
            errors.append(f"{audio.name}: OGG inválido o vacío")
    return errors


def validate_props(path: Path) -> list[str]:
    errors: list[str] = []
    for name in ("oran-berry.png", "lemon.png", "bed.png"):
        asset = path / name
        if not asset.exists():
            errors.append(f"Falta {name}")
            continue
        try:
            with Image.open(asset) as image:
                image.load()
                if image.format != "PNG" or image.width < 16 or image.height < 16:
                    errors.append(f"{name}: PNG inválido o demasiado pequeño")
                if image.mode not in {"RGBA", "LA", "P"}:
                    errors.append(f"{name}: falta transparencia utilizable")
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    return errors


def main() -> int:
    pmd = ROOT / "assets" / "external" / "pmd"
    results = {name: validate_variant(pmd / name) for name in ("default", "shiny", "altcolor")}
    results["cries"] = validate_cries(ROOT / "assets" / "external" / "pokeapi" / "cries")
    results["props"] = validate_props(ROOT / "assets" / "external" / "props")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
