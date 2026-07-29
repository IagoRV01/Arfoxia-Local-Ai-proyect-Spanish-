from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint

from glaceon_companion.codex_presence import ReservedRect
from glaceon_companion.config import PROJECT_ROOT
from glaceon_companion.desktop_interactions import (
    choose_reachable_x,
    foot_is_over_bed,
    item_position_from_ratios,
    normalized_item_position,
    parabolic_point,
    sleeping_window_position,
)


def test_fetch_target_stays_in_the_safe_segment_containing_arfoxia():
    ranges = [(0, 420), (900, 1500)]

    assert choose_reachable_x(200, 1200, ranges) == 420
    assert choose_reachable_x(1100, 100, ranges) == 900
    assert choose_reachable_x(200, 300, ranges) == 300


def test_fetch_target_recovers_to_nearest_segment_if_pet_starts_in_obstacle():
    assert choose_reachable_x(700, 1200, [(0, 420), (900, 1500)]) == 1200
    assert choose_reachable_x(10, 20, []) is None


def test_only_the_visible_foot_point_activates_the_bed():
    bed = ReservedRect(500, 600, 100, 200)

    assert foot_is_over_bed(ReservedRect(480, 560, 128, 120), bed)
    assert not foot_is_over_bed(ReservedRect(350, 560, 128, 120), bed)
    assert not foot_is_over_bed(ReservedRect(480, 300, 128, 120), bed)


def test_sleep_anchor_centres_the_pet_over_the_mattress():
    assert sleeping_window_position(
        ReservedRect(500, 600, 100, 200),
        window_width=420,
        window_height=420,
    ) == (340, 336)


def test_bed_position_round_trips_on_a_negative_coordinate_monitor():
    screen = ReservedRect(-1920, 0, 1920, 1040)
    bed = ReservedRect(-1500, 620, 100, 200)

    ratios = normalized_item_position(bed, screen)
    restored = item_position_from_ratios(
        screen,
        item_width=bed.width,
        item_height=bed.height,
        x_ratio=ratios[0],
        y_ratio=ratios[1],
    )

    assert restored == (bed.x, bed.y)


def test_lemon_throw_arc_preserves_endpoints_and_rises_at_midpoint():
    start = QPoint(100, 600)
    end = QPoint(700, 800)

    assert parabolic_point(start, end, 0.0) == start
    assert parabolic_point(start, end, 1.0) == end
    midpoint = parabolic_point(start, end, 0.5, arc_height=120)
    assert midpoint.x() == 400
    assert midpoint.y() == 580


def test_existing_interaction_assets_are_valid_transparent_pngs():
    expected = {
        "oran-berry.png": (30, 30),
        "lemon.png": (34, 34),
        "bed.png": (50, 100),
    }
    props = PROJECT_ROOT / "assets" / "external" / "props"

    for name, size in expected.items():
        path = props / name
        assert path.exists(), Path(name)
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == size
            assert "A" in image.convert("RGBA").getbands()
            assert image.convert("RGBA").getbbox() is not None
