"""Detección pasiva del overlay de Eevee en Codex Desktop.

Este módulo solo consulta el proceso y archivos locales de Codex. No mueve
ventanas, no automatiza la interfaz y no modifica el estado que inspecciona.
Las coordenadas persistidas por Codex corresponden al cuadro visible de la
mascota. A partir de él también puede estimarse la ventana transparente completa
para que las burbujas de Arfoxia no tapen los controles de Eevee.
"""

from __future__ import annotations

import json
import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psutil


CHATGPT_PROCESS_NAME = "ChatGPT.exe"
DEFAULT_MASCOT_SIZE = (192, 208)
DEFAULT_OVERLAY_WINDOW_SIZE = (408, 400)
OVERLAY_BOTTOM_MARGIN = 8

_MAX_STATE_BYTES = 4 * 1024 * 1024
_MAX_PET_MANIFEST_BYTES = 64 * 1024
_MAX_CONFIG_BYTES = 512 * 1024
_MAX_ABS_COORDINATE = 100_000
_MAX_OVERLAY_DIMENSION = 4_096

ProcessChecker = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class ReservedRect:
    """Rectángulo de pantalla que Arfoxia debe dejar libre, en píxeles."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True, slots=True)
class CodexPresence:
    """Resultado seguro de la detección del overlay de Eevee.

    ``visible`` solo es verdadero cuando el proceso, la preferencia del overlay,
    el paquete de Eevee y el rectángulo han podido validarse. Por tanto, siempre
    que sea verdadero, ``reserved_rect`` contiene una zona utilizable.
    """

    visible: bool
    reserved_rect: ReservedRect | None = None


def overlay_window_rect(mascot: ReservedRect) -> ReservedRect:
    """Estimate Codex's full avatar window around its centred mascot.

    Codex keeps the v2 pet centred horizontally and eight pixels above the
    bottom of a 408×400 DIP transparent overlay.  Qt and Electron both expose
    these positions in desktop-independent pixels on Windows, so the result can
    be compared directly with Arfoxia's companion windows.
    """

    overlay_width = max(DEFAULT_OVERLAY_WINDOW_SIZE[0], mascot.width)
    overlay_height = max(
        DEFAULT_OVERLAY_WINDOW_SIZE[1], mascot.height + OVERLAY_BOTTOM_MARGIN
    )
    return ReservedRect(
        mascot.x - (overlay_width - mascot.width) // 2,
        mascot.bottom - overlay_height + OVERLAY_BOTTOM_MARGIN,
        overlay_width,
        overlay_height,
    )


def rectangles_overlap(
    first: ReservedRect,
    second: ReservedRect,
    *,
    padding: int = 0,
) -> bool:
    """Return whether two screen rectangles overlap, reserving extra space."""

    gap = max(0, int(padding))
    return not (
        first.right <= second.x - gap
        or first.x >= second.right + gap
        or first.bottom <= second.y - gap
        or first.y >= second.bottom + gap
    )


def horizontal_safe_ranges(
    minimum_x: int,
    maximum_x: int,
    *,
    window_width: int,
    window_y: int,
    window_height: int,
    obstacle: ReservedRect,
    padding: int = 0,
) -> list[tuple[int, int]]:
    """Return inclusive X ranges whose window will not cover ``obstacle``."""

    low, high = int(minimum_x), int(maximum_x)
    width = max(1, int(window_width))
    height = max(1, int(window_height))
    gap = max(0, int(padding))
    if low > high:
        low, high = high, low
    vertical_overlap = not (
        int(window_y) + height <= obstacle.y - gap
        or int(window_y) >= obstacle.bottom + gap
    )
    if not vertical_overlap:
        return [(low, high)]

    output: list[tuple[int, int]] = []
    left_end = min(high, obstacle.x - gap - width)
    if low <= left_end:
        output.append((low, left_end))
    right_start = max(low, obstacle.right + gap)
    if right_start <= high:
        output.append((right_start, high))
    return output


def nearest_safe_x(
    current_x: int,
    minimum_x: int,
    maximum_x: int,
    **range_arguments: Any,
) -> int | None:
    """Choose the smallest horizontal displacement outside Eevee's area."""

    ranges = horizontal_safe_ranges(minimum_x, maximum_x, **range_arguments)
    if not ranges:
        return None
    candidates = [max(start, min(int(current_x), end)) for start, end in ranges]
    return min(candidates, key=lambda value: (abs(value - int(current_x)), value))


def process_is_running(image_name: str) -> bool:
    """Comprueba un nombre de imagen sin solicitar acceso ni alterar procesos."""

    wanted = image_name.casefold()
    try:
        processes = psutil.process_iter(["name"])
        for process in processes:
            try:
                name = process.info.get("name")
                if isinstance(name, str) and name.casefold() == wanted:
                    return True
            except (psutil.Error, OSError):
                continue
    except (psutil.Error, OSError):
        return False
    return False


def detect_codex_presence(
    *,
    process_checker: ProcessChecker = process_is_running,
    codex_home: Path | str | None = None,
    overlay_size: tuple[int, int] | None = None,
) -> CodexPresence:
    """Detecta de forma pasiva si el overlay de Eevee está visible.

    ``process_checker`` es inyectable para mantener las pruebas independientes
    de los procesos reales. ``codex_home`` permite el mismo aislamiento para los
    archivos; de forma predeterminada apunta a ``%USERPROFILE%/.codex``.
    """

    try:
        if process_checker(CHATGPT_PROCESS_NAME) is not True:
            return CodexPresence(False)
    except Exception:
        # La detección es auxiliar: un inspector de procesos sin permisos no debe
        # impedir que Arfoxia siga funcionando.
        return CodexPresence(False)

    root = _codex_home(codex_home)
    state = _read_json_object(root / ".codex-global-state.json", _MAX_STATE_BYTES)
    if state is None or state.get("electron-avatar-overlay-open") is not True:
        return CodexPresence(False)

    manifest = _read_json_object(root / "pets" / "eevee" / "pet.json", _MAX_PET_MANIFEST_BYTES)
    if manifest is None or str(manifest.get("id") or "").casefold() != "eevee":
        return CodexPresence(False)

    config = _read_toml_object(root / "config.toml", _MAX_CONFIG_BYTES)
    desktop = config.get("desktop") if isinstance(config, dict) else None
    if not isinstance(desktop, dict):
        return CodexPresence(False)
    if str(desktop.get("selected-avatar-id") or "").casefold() != "custom:eevee":
        return CodexPresence(False)

    mascot_size = overlay_size or _configured_mascot_size(desktop)
    if mascot_size is None:
        return CodexPresence(False)

    bounds = state.get("electron-avatar-overlay-bounds")
    if not isinstance(bounds, dict):
        return CodexPresence(False)
    rect = _validated_rect(bounds, mascot_size)
    if rect is None:
        return CodexPresence(False)
    return CodexPresence(True, rect)


def _codex_home(override: Path | str | None) -> Path:
    if override is not None:
        return Path(override)
    user_profile = os.environ.get("USERPROFILE")
    return Path(user_profile) / ".codex" if user_profile else Path.home() / ".codex"


def _read_json_object(path: Path, maximum_bytes: int) -> dict[str, Any] | None:
    """Lee un objeto JSON pequeño con límites y sin propagar datos o errores."""

    try:
        size = path.stat().st_size
        if size <= 0 or size > maximum_bytes or not path.is_file():
            return None
        raw = path.read_bytes()
        if len(raw) > maximum_bytes:
            return None
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_toml_object(path: Path, maximum_bytes: int) -> dict[str, Any] | None:
    try:
        size = path.stat().st_size
        if size <= 0 or size > maximum_bytes or not path.is_file():
            return None
        raw = path.read_bytes()
        if len(raw) > maximum_bytes:
            return None
        payload = tomllib.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _configured_mascot_size(desktop: dict[str, Any]) -> tuple[int, int] | None:
    width = _integer(desktop.get("avatar-overlay-mascot-width-px"))
    if width is None:
        return DEFAULT_MASCOT_SIZE
    if not 32 <= width <= 512:
        return None
    # Codex v2 pets use a 192×208 mascot composition box.
    height = math.ceil(width * DEFAULT_MASCOT_SIZE[1] / DEFAULT_MASCOT_SIZE[0])
    return width, height


def _validated_rect(
    bounds: dict[str, Any], fallback_size: tuple[int, int]
) -> ReservedRect | None:
    x = _integer(bounds.get("x"))
    y = _integer(bounds.get("y"))
    if x is None or y is None:
        return None
    if abs(x) > _MAX_ABS_COORDINATE or abs(y) > _MAX_ABS_COORDINATE:
        return None

    # Solo se aceptan width/height del propio overlay. ``displayBounds`` describe
    # el monitor y no deben convertirse accidentalmente en la zona reservada.
    explicit_width = bounds.get("width")
    explicit_height = bounds.get("height")
    if (explicit_width is None) != (explicit_height is None):
        return None
    if explicit_width is None:
        try:
            raw_width, raw_height = fallback_size
        except (TypeError, ValueError):
            return None
    else:
        raw_width, raw_height = explicit_width, explicit_height

    width = _integer(raw_width)
    height = _integer(raw_height)
    if width is None or height is None:
        return None
    if not (1 <= width <= _MAX_OVERLAY_DIMENSION):
        return None
    if not (1 <= height <= _MAX_OVERLAY_DIMENSION):
        return None
    return ReservedRect(x, y, width, height)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None
