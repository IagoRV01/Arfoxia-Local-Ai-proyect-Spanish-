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


def test_eight_way_walk_and_expression_assets_are_present():
    from glaceon_companion.pet_motion import EXPRESSION_LABELS

    library = SpriteLibrary(PROJECT_ROOT / "assets" / "external" / "pmd" / "default")
    for name in ("Walk", *EXPRESSION_LABELS):
        for direction in range(8):
            frames, durations = library.frames(name, direction)
            assert len(frames) == len(durations) > 0
            assert all(frame.getbbox() for frame in frames)
