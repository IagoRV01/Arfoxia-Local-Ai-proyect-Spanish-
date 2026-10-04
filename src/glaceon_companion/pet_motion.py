"""Small deterministic helpers for eight-direction desktop movement."""
from __future__ import annotations

import math


def direction_for_delta(dx: float, dy: float) -> int:
    """PMD rows: down, down-right, right, up-right, up, up-left, left, down-left."""
    return int(math.floor(math.atan2(dx, dy) / (math.pi / 4) + 0.5)) % 8


def step_towards(x: int, y: int, target_x: int, target_y: int, speed: float = 3) -> tuple[int, int]:
    dx, dy = target_x - x, target_y - y
    distance = math.hypot(dx, dy)
    if distance <= speed:
        return target_x, target_y
    return x + round(dx / distance * speed), y + round(dy / distance * speed)


EXPRESSION_LABELS = {
    "LookUp": "Curiosidad · mirar alrededor",
    "Nod": "Saludar · asentir",
    "TailWhip": "Contento · mover la cola",
    "Hop": "Alegría · saltito",
    "Wake": "Estirarse",
    "DeepBreath": "Respirar tranquilo",
    "Pose": "Posar",
    "Rotate": "Dar una vuelta",
}


def expression_choices(energy: float, hunger: float, happiness: float) -> tuple[str, ...]:
    if energy < 30 or hunger > 82:
        return ("LookUp", "DeepBreath", "Nod", "Wake")
    if happiness >= 65:
        return ("LookUp", "Nod", "TailWhip", "Hop", "Wake", "Pose", "Rotate")
    return ("LookUp", "Nod", "DeepBreath", "Wake", "TailWhip", "Pose")
