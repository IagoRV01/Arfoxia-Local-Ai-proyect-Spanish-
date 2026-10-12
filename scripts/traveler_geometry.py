"""Logical coordinates on a stationary surface; independent of GTK/Wayland."""
from __future__ import annotations

from dataclasses import dataclass
import math


def clamp_anchor(x, y, width, height, object_width, object_height):
    """Feet-centred anchor, bounded to one monitor, including oversized assets."""
    if not all(math.isfinite(v) for v in (x, y, width, height, object_width, object_height)):
        raise ValueError("Las coordenadas deben ser finitas")
    left = min(width / 2, object_width / 2 + 8)
    right = max(left, width - left)
    top = min(height, object_height + 8)
    bottom = max(top, height - 8)
    return round(max(left, min(right, x))), round(max(top, min(bottom, y)))


def anchored_rect(x, y, width, height):
    return round(x - width / 2), round(y - height), width, height


@dataclass
class Drag:
    pointer_x: float
    pointer_y: float
    anchor_x: float
    anchor_y: float
    subject: str = "pet"
    max_distance: float = 0

    def move(self, pointer_x, pointer_y):
        dx, dy = pointer_x - self.pointer_x, pointer_y - self.pointer_y
        self.max_distance = max(self.max_distance, math.hypot(dx, dy))
        return self.anchor_x + dx, self.anchor_y + dy

    @property
    def clicked(self):
        # Returning to the starting point must not turn a drag into a caress.
        return self.max_distance < 6


def context_actions(asleep=False, seated=False, bed=False, lemon=False):
    """Labels and fixed action names, shared by the client and regression tests."""
    return [
        ("Acariciar", "pet"), ("Dar una Baya Aranja", "feed"),
        ("Jugar con el limón", "lemon"), ("Colocar / mover cama", "bed"),
        ("Despertar" if asleep else "Dormir", "wake" if asleep else "sleep"),
        ("Volver a pasear" if seated else "Quedarse sentado (sin dormir)", "resume" if seated else "sit"),
        *([("Quitar cama", "remove-bed")] if bed else []),
        *([("Quitar limón", "remove-lemon")] if lemon else []),
        ("Estado de Arfoxia", "status"), ("Hacer captura de este escritorio", "capture"),
        ("Volver al PC", "return"),
    ]
