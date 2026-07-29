from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from glaceon_companion.icons import SNOWFLAKE_ICON_SIZES, snowflake_icon


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_snowflake_icon_has_all_windows_native_sizes(app):
    del app
    icon = snowflake_icon()

    assert not icon.isNull()
    for size in SNOWFLAKE_ICON_SIZES:
        pixmap = icon.pixmap(size, size)
        assert not pixmap.isNull()
        assert pixmap.width() == size
        assert pixmap.height() == size
