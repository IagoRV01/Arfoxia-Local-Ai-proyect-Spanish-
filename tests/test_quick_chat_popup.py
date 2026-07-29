import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from glaceon_companion.ui import QuickChatPopup


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_escape_closes_quick_chat_even_while_input_has_focus(app):
    popup = QuickChatPopup("Arfoxia", inactivity_timeout_ms=500)
    popup.show_and_focus()
    app.processEvents()

    assert popup.isVisible()
    assert popup.input.hasFocus()

    QTest.keyClick(popup.input, Qt.Key.Key_Escape)
    app.processEvents()

    assert not popup.isVisible()
    assert not popup.inactivity_timer.isActive()
    popup.close()


def test_activity_restarts_timeout_then_popup_closes_after_inactivity(app):
    timeout_ms = 300
    popup = QuickChatPopup("Arfoxia", inactivity_timeout_ms=timeout_ms)
    popup.show_and_focus()
    app.processEvents()

    QTest.qWait(100)
    QTest.keyClicks(popup.input, "hola")
    QTest.qWait(100)
    assert popup.isVisible()

    QTest.mouseMove(popup.input, QPoint(4, 4))
    QTest.qWait(100)
    assert popup.isVisible()

    popup.send_button.setFocus()
    app.processEvents()
    QTest.qWait(100)
    assert popup.isVisible()

    QTest.qWait(timeout_ms)
    assert not popup.isVisible()
    popup.close()
