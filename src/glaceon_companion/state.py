from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime


WAKE_ENERGY_FLOOR = 18.0


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


@dataclass(slots=True)
class PetState:
    hunger: float = 18.0
    happiness: float = 78.0
    energy: float = 84.0
    trust: float = 55.0
    curiosity: float = 72.0
    asleep: bool = False
    last_interaction: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(UTC).isoformat()
        self.last_interaction = self.last_interaction or now
        self.updated_at = self.updated_at or now

    @property
    def mood(self) -> str:
        if self.asleep:
            return "dormido"
        if self.energy < 18:
            return "agotado"
        if self.hunger > 78:
            return "hambriento"
        if self.happiness < 30:
            return "triste"
        if self.curiosity > 82:
            return "curioso"
        if self.happiness > 82:
            return "feliz"
        return "tranquilo"

    def advance(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        previous = datetime.fromisoformat(self.updated_at)
        hours = max(0.0, min((current - previous).total_seconds() / 3600.0, 168.0))
        if not hours:
            return
        self.hunger = _clamp(self.hunger + 2.4 * hours)
        if self.asleep:
            self.energy = _clamp(self.energy + 10.0 * hours)
            if self.energy >= 96:
                self.asleep = False
        else:
            self.energy = _clamp(self.energy - 1.8 * hours)
            if self.energy <= 4:
                self.asleep = True
        neglect = max(0.0, (current - datetime.fromisoformat(self.last_interaction)).total_seconds() / 3600.0 - 4)
        self.happiness = _clamp(self.happiness - min(hours * 0.4 + neglect * 0.08, 8.0))
        self.curiosity = _clamp(self.curiosity + 0.7 * hours)
        self.updated_at = current.isoformat()

    def feed(self) -> None:
        self.hunger = _clamp(self.hunger - 34)
        self.happiness = _clamp(self.happiness + 7)
        self.trust = _clamp(self.trust + 1.5)
        self.curiosity = _clamp(self.curiosity - 5)
        self._touch()

    def pet(self) -> None:
        self.happiness = _clamp(self.happiness + 9)
        self.trust = _clamp(self.trust + 2.5)
        self.energy = _clamp(self.energy + 1)
        self._touch()

    def play(self) -> None:
        self.happiness = _clamp(self.happiness + 13)
        self.curiosity = _clamp(self.curiosity - 18)
        self.energy = _clamp(self.energy - 8)
        self.hunger = _clamp(self.hunger + 4)
        self._touch()

    def sleep(self) -> None:
        self.asleep = True
        self._touch(wake=False)

    def wake(self) -> None:
        self._touch()

    def _touch(self, *, wake: bool = True) -> None:
        if wake and self.asleep:
            self.asleep = False
            # Keep an explicit wake above the UI's automatic sleep threshold.
            self.energy = _clamp(max(self.energy, WAKE_ENERGY_FLOOR))
        now = datetime.now(UTC).isoformat()
        self.last_interaction = now
        self.updated_at = now

    def as_public_dict(self) -> dict[str, float | str | bool]:
        result = asdict(self)
        result["mood"] = self.mood
        return result
