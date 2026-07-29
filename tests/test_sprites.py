from pathlib import Path

import pytest

from glaceon_companion.config import PROJECT_ROOT
from glaceon_companion.sprites import SpriteLibrary


def test_default_sprite_library_has_core_animations():
    path = PROJECT_ROOT / "assets" / "external" / "pmd" / "default"
    if not (path / "AnimData.xml").exists():
        pytest.skip("Activos aún no descargados")
    library = SpriteLibrary(path)
    assert {"Idle", "Walk", "Sleep", "Eat", "Pose"} <= set(library.available())
    frames, durations = library.frames("Idle", 0)
    assert len(frames) == len(durations) >= 2
    assert all(frame.getbbox() for frame in frames)
    # Some PMD reactions are intentionally non-directional single-row strips.
    eat_frames, _ = library.frames("Eat", 6)
    assert all(frame.getbbox() for frame in eat_frames)
