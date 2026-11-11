from __future__ import annotations

from ctypes import wintypes
from types import SimpleNamespace

import pytest

from glaceon_companion.desktop_visibility import _blocked


@pytest.mark.parametrize("hit,style,visible,cloaked,contains,bed,expected", [
    (10, 0x80028, True, False, True, None, False),  # pet is already hittable
    (30, 0x80028, True, False, True, None, True),   # hit falls through to a window below
    (20, 0x80028, True, False, True, None, False),  # foreground window actually takes the hit
    (20, 0x8080088, True, False, True, 20, True),  # own mattress covers a sleeping pet
    (20, 0x8080088, True, False, True, 30, False),  # unrelated prop
    (30, 0x80008, True, False, True, None, False),  # not click-through
    (30, 0x8080028, True, False, True, None, False),  # passive system surface
    (30, 0x80028, False, False, True, None, False),
    (30, 0x80028, True, True, True, None, False),
    (30, 0x80028, True, False, False, None, False),
    (0, 0x80028, True, False, True, None, False),
])
def test_overlay_recovery_distinguishes_visual_layers_from_foreground_windows(
    hit, style, visible, cloaked, contains, bed, expected,
):
    def client_to_screen(_handle, point):
        point._obj.x -= 200  # negative physical desktop coordinates are valid
        return True

    def hit_test(point):
        assert (point.x, point.y) == (-150, 50)
        return hit

    def window_rect(_handle, out):
        out._obj.left = -300 if contains else 0
        out._obj.right = 500
        out._obj.top = 0
        out._obj.bottom = 300
        return True

    def cloak_attribute(_handle, _attr, out, _size):
        out._obj.value = cloaked
        return 0

    user32 = SimpleNamespace(
        ClientToScreen=client_to_screen,
        WindowFromPhysicalPoint=hit_test,
        GetAncestor=lambda handle, _: handle.value,
        GetWindow=lambda handle, _: 20 if handle.value == 10 else None,
        GetWindowLongW=lambda *_: style,
        IsWindowVisible=lambda _: visible,
        IsIconic=lambda _: False,
        GetWindowRect=window_rect,
    )
    dwmapi = SimpleNamespace(DwmGetWindowAttribute=cloak_attribute)
    assert _blocked(user32, dwmapi, 10, wintypes.POINT(50, 50), bed) is expected
