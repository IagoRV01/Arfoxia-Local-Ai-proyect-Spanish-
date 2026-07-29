from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image


DIRECTION_NAMES = (
    "down",
    "down_right",
    "right",
    "up_right",
    "up",
    "up_left",
    "left",
    "down_left",
)


@dataclass(frozen=True, slots=True)
class AnimationSpec:
    name: str
    width: int
    height: int
    durations: tuple[int, ...]
    copy_of: str | None = None

    @property
    def durations_ms(self) -> tuple[int, ...]:
        return tuple(max(34, round(value * 1000 / 60)) for value in self.durations)


class SpriteLibrary:
    def __init__(self, variant_dir: Path) -> None:
        self.variant_dir = variant_dir
        self.specs = self._load_specs(variant_dir / "AnimData.xml")

    @staticmethod
    def _load_specs(path: Path) -> dict[str, AnimationSpec]:
        root = ElementTree.parse(path).getroot()
        specs: dict[str, AnimationSpec] = {}
        pending: dict[str, str] = {}
        for node in root.findall("./Anims/Anim"):
            name = node.findtext("Name") or ""
            copy_of = node.findtext("CopyOf")
            if copy_of:
                pending[name] = copy_of
                continue
            durations = tuple(
                int(item.text or "1") for item in node.findall("./Durations/Duration")
            )
            specs[name] = AnimationSpec(
                name=name,
                width=int(node.findtext("FrameWidth") or "1"),
                height=int(node.findtext("FrameHeight") or "1"),
                durations=durations,
            )
        for name, source in pending.items():
            base = specs[source]
            specs[name] = AnimationSpec(
                name=name,
                width=base.width,
                height=base.height,
                durations=base.durations,
                copy_of=source,
            )
        return specs

    def available(self) -> list[str]:
        return sorted(
            name
            for name, spec in self.specs.items()
            if (self.variant_dir / f"{spec.copy_of or name}-Anim.png").exists()
        )

    def frames(self, name: str, direction: int = 0) -> tuple[list[Image.Image], tuple[int, ...]]:
        if name not in self.specs:
            raise KeyError(f"Animación desconocida: {name}")
        if direction not in range(8):
            raise ValueError("La dirección debe estar entre 0 y 7")
        spec = self.specs[name]
        sheet_name = spec.copy_of or name
        sheet_path = self.variant_dir / f"{sheet_name}-Anim.png"
        sheet = Image.open(sheet_path).convert("RGBA")
        frame_count = len(spec.durations)
        expected_width = spec.width * frame_count
        expected_height = spec.height
        if sheet.width < expected_width or sheet.height < expected_height:
            raise ValueError(
                f"Spritesheet inválido {sheet_path.name}: {sheet.size}; "
                f"mínimo esperado {expected_width}x{expected_height}"
            )
        direction_rows = max(1, sheet.height // spec.height)
        row = direction if direction < direction_rows else 0
        top = row * spec.height
        frames = [
            sheet.crop((index * spec.width, top, (index + 1) * spec.width, top + spec.height))
            for index in range(frame_count)
        ]
        return frames, spec.durations_ms
