import math

import pytest

from glaceon_companion.pet_motion import direction_for_delta, expression_choices, step_towards


@pytest.mark.parametrize("delta,expected", [
    ((0, 10), 0), ((10, 10), 1), ((10, 0), 2), ((10, -10), 3),
    ((0, -10), 4), ((-10, -10), 5), ((-10, 0), 6), ((-10, 10), 7),
])
def test_walk_direction_matches_sprite_rows(delta, expected):
    assert direction_for_delta(*delta) == expected


@pytest.mark.parametrize("target", [(0, 60), (70, 0), (90, 90), (-90, -45), (-2, 1)])
def test_motion_arrives_without_overshoot_and_diagonal_speed_is_normalized(target):
    x = y = 0
    for _ in range(200):
        next_x, next_y = step_towards(x, y, *target)
        assert math.hypot(next_x - x, next_y - y) <= 3.7
        assert math.dist((next_x, next_y), target) <= math.dist((x, y), target)
        x, y = next_x, next_y
        if (x, y) == target:
            break
    assert (x, y) == target


def test_tired_and_hungry_expression_pools_are_calm():
    assert "Hop" not in expression_choices(20, 20, 90)
    assert "Hop" not in expression_choices(90, 90, 90)
    assert "Hop" in expression_choices(90, 20, 90)
