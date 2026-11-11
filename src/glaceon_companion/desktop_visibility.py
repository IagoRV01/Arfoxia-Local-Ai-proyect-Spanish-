"""Win32 checks for a topmost sprite masked by a click-through desktop overlay."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache


@lru_cache(maxsize=1)
def _window_apis():
    user32 = ctypes.WinDLL("user32")
    for name in ("WindowFromPhysicalPoint", "GetAncestor", "GetWindow"):
        getattr(user32, name).restype = wintypes.HWND
    return user32, ctypes.WinDLL("dwmapi")


def blocked_by_desktop_overlay(hwnd: int, x: int, y: int, bed_hwnd: int | None = None) -> bool:
    """Check a known painted pixel, supplied in native client coordinates."""
    user32, dwmapi = _window_apis()
    return _blocked(user32, dwmapi, hwnd, wintypes.POINT(x, y), bed_hwnd)


def _blocked(user32, dwmapi, hwnd: int, point: wintypes.POINT, bed_hwnd: int | None = None) -> bool:
    handle = wintypes.HWND(hwnd)
    if not user32.ClientToScreen(handle, ctypes.byref(point)):
        return False
    hit = user32.WindowFromPhysicalPoint(point)
    if not hit:
        return False
    hit = user32.GetAncestor(wintypes.HWND(hit), 2) or hit  # GA_ROOT
    if hit == hwnd:
        return False

    # Layered, click-through, topmost. Ignore passive OS/prop surfaces.
    overlay_style = 0x80000 | 0x20 | 0x8
    no_activate = 0x08000000
    covering_overlay = False
    visited = {hwnd}
    # Only consider windows genuinely above the pet in the topmost band.
    for _ in range(128):
        higher = user32.GetWindow(handle, 3)  # GW_HWNDPREV
        if not higher:
            return covering_overlay
        if higher in visited:
            return False
        if higher == hit:
            # Interactive windows are intentional, except our own mattress
            # when the pet is meant to be drawn on top of it.
            return higher == bed_hwnd
        visited.add(higher)
        handle = wintypes.HWND(higher)
        style = user32.GetWindowLongW(handle, -20)  # GWL_EXSTYLE
        if (style & overlay_style) != overlay_style or style & no_activate:
            continue
        if not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
            continue
        rect = wintypes.RECT()
        cloaked = wintypes.DWORD()
        if (user32.GetWindowRect(handle, ctypes.byref(rect))
                and rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom
                and dwmapi.DwmGetWindowAttribute(handle, 14, ctypes.byref(cloaked),
                                                ctypes.sizeof(cloaked)) == 0
                and not cloaked.value):
            covering_overlay = True
    return False  # Incomplete or changing z-order: leave it alone.
