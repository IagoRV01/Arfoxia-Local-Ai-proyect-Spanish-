"""Regressions for the Linux pet without requiring GTK on the Windows host."""
import importlib.util
from pathlib import Path
import sys

import pytest


spec = importlib.util.spec_from_file_location("traveler_geometry", Path(__file__).parents[1] / "scripts/traveler_geometry.py")
geometry = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = geometry
spec.loader.exec_module(geometry)


def test_drag_uses_stable_canvas_coordinates_and_keeps_grab_offset():
    drag = geometry.Drag(400, 250, 420, 300)
    assert drag.move(410, 270) == (430, 320)
    assert drag.move(430, 280) == (450, 330)  # Not cumulative feedback from a moved surface.
    assert not drag.clicked


def test_drag_out_and_back_is_not_a_click():
    drag = geometry.Drag(100, 100, 120, 150)
    drag.move(300, 300)
    assert drag.move(100, 100) == (120, 150)
    assert not drag.clicked


def test_small_pointer_jitter_is_a_click():
    drag = geometry.Drag(100, 100, 120, 150)
    drag.move(102, 103)
    assert drag.clicked


@pytest.mark.parametrize("subject", ["pet", "bed", "lemon"])
def test_each_object_has_an_independent_drag_anchor(subject):
    drag = geometry.Drag(60, 30, 70, 80, subject)
    assert drag.subject == subject
    assert drag.move(160, 90) == (170, 140)


def test_anchor_stays_inside_monitor_with_full_sprite_extent():
    assert geometry.clamp_anchor(-500, -800, 1920, 1080, 200, 260) == (108, 268)
    assert geometry.clamp_anchor(9999, 9999, 1920, 1080, 200, 260) == (1812, 1072)


def test_oversized_asset_does_not_invert_bounds():
    assert geometry.clamp_anchor(0, 0, 100, 80, 200, 260) == (50, 80)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_corrupt_preferences_reject_non_finite_position(bad):
    with pytest.raises(ValueError):
        geometry.clamp_anchor(bad, 20, 1920, 1080, 200, 260)


def test_animation_dimensions_keep_same_feet_anchor():
    assert geometry.anchored_rect(400, 300, 100, 150) == (350, 150, 100, 150)
    assert geometry.anchored_rect(400, 300, 200, 260) == (300, 40, 200, 260)


def test_context_menu_has_real_missing_pet_options_and_stateful_labels():
    actions = dict(geometry.context_actions())
    assert actions["Dormir"] == "sleep"
    assert actions["Quedarse sentado (sin dormir)"] == "sit"
    assert actions["Jugar con el limón"] == "lemon"
    assert actions["Colocar / mover cama"] == "bed"
    assert actions["Hacer captura de este escritorio"] == "capture"
    assert actions["Volver al PC"] == "return"
    assert "Quitar cama" not in actions
    other = dict(geometry.context_actions(True, True, True, True))
    assert other["Despertar"] == "wake"
    assert other["Volver a pasear"] == "resume"
    assert other["Quitar cama"] == "remove-bed"
    assert other["Quitar limón"] == "remove-lemon"


def test_client_never_moves_wayland_surface_or_uses_synthetic_root_coordinates():
    source = (Path(__file__).parents[1] / "scripts/traveler_linux.py").read_text(encoding="utf-8")
    assert "event.x_root" not in source and "event.y_root" not in source
    assert "layer.set_margin" not in source
    assert "layer.Edge.RIGHT" in source and "layer.Edge.BOTTOM" in source
    assert "self.move_drag(event.x, event.y)" in source
    assert "self.drag.clicked" in source
    assert "menu.popup_at_rect(self.canvas.get_window(), anchor" in source
