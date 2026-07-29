from __future__ import annotations

import json
from pathlib import Path

import pytest

from glaceon_companion.codex_presence import (
    CHATGPT_PROCESS_NAME,
    CodexPresence,
    ReservedRect,
    detect_codex_presence,
    horizontal_safe_ranges,
    nearest_safe_x,
    overlay_window_rect,
    rectangles_overlap,
)


def write_codex_state(
    root: Path,
    *,
    open_overlay: object = True,
    bounds: object | None = None,
    pet_id: str = "eevee",
    selected_avatar: str = "custom:eevee",
    mascot_width: int | None = 155,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state = {
        "electron-avatar-overlay-open": open_overlay,
        "electron-avatar-overlay-bounds": bounds
        if bounds is not None
        else {
            "x": 441,
            "y": 613,
            "displayBounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
        },
    }
    (root / ".codex-global-state.json").write_text(json.dumps(state), encoding="utf-8")
    pet_dir = root / "pets" / "eevee"
    pet_dir.mkdir(parents=True)
    (pet_dir / "pet.json").write_text(
        json.dumps({"id": pet_id, "spriteVersionNumber": 2}), encoding="utf-8"
    )
    width_line = (
        f"avatar-overlay-mascot-width-px = {mascot_width}\n"
        if mascot_width is not None
        else ""
    )
    (root / "config.toml").write_text(
        f'[desktop]\n{width_line}selected-avatar-id = "{selected_avatar}"\n',
        encoding="utf-8",
    )


def test_visible_eevee_uses_selected_pet_and_configured_mascot_size(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home)
    checked: list[str] = []

    def running(name: str) -> bool:
        checked.append(name)
        return True

    result = detect_codex_presence(
        codex_home=codex_home,
        process_checker=running,
    )

    assert checked == [CHATGPT_PROCESS_NAME]
    assert result == CodexPresence(True, ReservedRect(441, 613, 155, 168))
    assert result.reserved_rect is not None
    assert result.reserved_rect.right == 596
    assert result.reserved_rect.bottom == 781


def test_direct_valid_size_in_state_overrides_fixed_size(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    write_codex_state(
        codex_home,
        bounds={"x": -320, "y": 25, "width": 300, "height": 360},
    )

    result = detect_codex_presence(codex_home=codex_home, process_checker=lambda _: True)

    assert result == CodexPresence(True, ReservedRect(-320, 25, 300, 360))


@pytest.mark.parametrize("open_value", [False, None, 1, "true"])
def test_overlay_flag_must_be_literal_true(tmp_path: Path, open_value: object):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home, open_overlay=open_value)

    result = detect_codex_presence(codex_home=codex_home, process_checker=lambda _: True)

    assert result == CodexPresence(False)


def test_chatgpt_process_is_required_and_checked_by_exact_image_name(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home)
    checked: list[str] = []

    result = detect_codex_presence(
        codex_home=codex_home,
        process_checker=lambda name: checked.append(name) is not None,
    )

    assert checked == ["ChatGPT.exe"]
    assert result == CodexPresence(False)


@pytest.mark.parametrize("pet_id", ["glaceon", "", "eevee-other"])
def test_valid_eevee_package_is_required(tmp_path: Path, pet_id: str):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home, pet_id=pet_id)

    result = detect_codex_presence(codex_home=codex_home, process_checker=lambda _: True)

    assert result == CodexPresence(False)


def test_eevee_must_be_the_current_selected_avatar(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home, selected_avatar="codex")

    assert detect_codex_presence(
        codex_home=codex_home, process_checker=lambda _: True
    ) == CodexPresence(False)


@pytest.mark.parametrize(
    "bounds",
    [
        {"x": "12", "y": 20},
        {"x": 12, "y": True},
        {"x": 100_001, "y": 20},
        {"x": 12, "y": 20, "width": 0, "height": 400},
        {"x": 12, "y": 20, "width": 384},
        {"x": 12, "y": 20, "width": 5000, "height": 400},
    ],
)
def test_invalid_coordinates_or_sizes_are_never_reserved(tmp_path: Path, bounds: object):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home, bounds=bounds)

    result = detect_codex_presence(codex_home=codex_home, process_checker=lambda _: True)

    assert result == CodexPresence(False)


def test_malformed_and_oversized_state_and_checker_failure_are_safe(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home)
    (codex_home / ".codex-global-state.json").write_text("{not-json", encoding="utf-8")

    malformed = detect_codex_presence(codex_home=codex_home, process_checker=lambda _: True)

    (codex_home / ".codex-global-state.json").write_bytes(b" " * (4 * 1024 * 1024 + 1))
    oversized = detect_codex_presence(codex_home=codex_home, process_checker=lambda _: True)

    def unavailable_checker(_: str) -> bool:
        raise PermissionError("access denied")

    unavailable = detect_codex_presence(
        codex_home=codex_home, process_checker=unavailable_checker
    )

    assert malformed == CodexPresence(False)
    assert oversized == CodexPresence(False)
    assert unavailable == CodexPresence(False)


def test_invalid_fallback_size_is_rejected(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    write_codex_state(codex_home)

    result = detect_codex_presence(
        codex_home=codex_home,
        process_checker=lambda _: True,
        overlay_size=(10_000, 400),
    )

    assert result == CodexPresence(False)


def test_overlap_and_safe_ranges_leave_padding_between_both_pets():
    eevee = ReservedRect(700, 600, 384, 400)
    arfoxia = ReservedRect(900, 640, 420, 420)

    assert rectangles_overlap(arfoxia, eevee, padding=24)
    assert horizontal_safe_ranges(
        0,
        1500,
        window_width=420,
        window_y=640,
        window_height=420,
        obstacle=eevee,
        padding=24,
    ) == [(0, 256), (1108, 1500)]
    assert nearest_safe_x(
        900,
        0,
        1500,
        window_width=420,
        window_y=640,
        window_height=420,
        obstacle=eevee,
        padding=24,
    ) == 1108


def test_horizontal_movement_is_unrestricted_when_vertical_bands_do_not_meet():
    assert horizontal_safe_ranges(
        -100,
        900,
        window_width=420,
        window_y=0,
        window_height=300,
        obstacle=ReservedRect(300, 600, 384, 400),
        padding=24,
    ) == [(-100, 900)]


def test_full_codex_overlay_is_derived_from_the_visible_mascot_box():
    mascot = ReservedRect(1152, 671, 155, 168)

    assert overlay_window_rect(mascot) == ReservedRect(1026, 447, 408, 400)
