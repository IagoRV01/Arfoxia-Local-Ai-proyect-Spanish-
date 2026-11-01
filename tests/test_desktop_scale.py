import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout

from glaceon_companion.desktop_scale import apply_window_scale, readability_scale, unscaled_stylesheet
from glaceon_companion.desktop_interactions import PlacementOverlay
from glaceon_companion.ui import QuickChatPopup, SpeechBubble


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def monitor(width, height, dpr=1.0, x=0, y=0):
    return SimpleNamespace(geometry=lambda: QRect(x, y, width, height),
        availableGeometry=lambda: QRect(x, y, width, height - 40),
        devicePixelRatio=lambda: dpr)


@pytest.mark.parametrize('logical,dpr,expected', [((1920,1080),1,1), ((3840,2160),1,2),
    ((2560,1440),1.5,1.333), ((1920,1080),2,1), ((3840,1080),1,1), ((7680,4320),1,2.5)])
def test_scale_uses_logical_resolution_without_double_dpi(logical, dpr, expected):
    assert readability_scale(monitor(*logical, dpr)) == expected


def test_window_scale_is_reversible_and_never_accumulates(app):
    window = QDialog()
    window.resize(600, 400)
    window.setStyleSheet('QLabel{font-size:14px;padding:8px;}')
    layout = QVBoxLayout(window)
    label = QLabel('Texto legible')
    layout.addWidget(label)
    original = window.styleSheet()
    try:
        apply_window_scale(window, monitor(3840,2160))
        assert window.size().width() == 1200
        assert '28px' in window.styleSheet()
        apply_window_scale(window, monitor(3840,2160))
        assert window.size().width() == 1200
        assert unscaled_stylesheet(window) == original
        apply_window_scale(window, monitor(1920,1080,2))
        assert window.size().width() == 600
        assert window.styleSheet() == original
    finally:
        window.close()


def test_parent_scaling_does_not_touch_nested_dialog_styles(app):
    parent = QDialog()
    child = QDialog(parent)
    label = QLabel('Child', child)
    label.setStyleSheet('font-size:14px;')
    try:
        apply_window_scale(parent, monitor(3840,2160))
        assert label.styleSheet() == 'font-size:14px;'
        apply_window_scale(child, monitor(3840,2160))
        assert label.styleSheet() == 'font-size:28px;'
    finally:
        child.close()
        parent.close()


def test_overlay_scales_cursor_and_hint_on_active_monitor_without_coordinate_drift(app, monkeypatch):
    fullhd = monitor(1920,1080,1,x=-1920)
    fourk = monitor(3840,2160)
    retina = monitor(1920,1080,2,x=3840)
    monkeypatch.setattr(QApplication, 'screens', lambda: [fullhd, fourk, retina])
    monkeypatch.setattr(QApplication, 'screenAt', lambda p: fullhd if p.x() < 0 else retina if p.x() >= 3840 else fourk)
    overlay = PlacementOverlay()
    overlay.setGeometry(-1920,0,7680,2160)
    overlay.instruction = 'Mueve el limón y haz clic para lanzarlo · Esc cancela'
    source = QPixmap(48,48)
    source.fill(QColor('yellow'))
    overlay.preview_source = source
    try:
        for point, logical_edge in [(QPoint(1000,300),96), (QPoint(-500,300),48), (QPoint(4200,300),48)]:
            overlay._move_preview(point)
            assert overlay.preview_center + overlay.geometry().topLeft() == point
            assert overlay.preview_pixmap.deviceIndependentSize().width() == logical_edge
            panel = overlay.instruction_panel().translated(overlay.geometry().topLeft())
            assert overlay.active_screen.availableGeometry().contains(panel)
        assert overlay.preview_pixmap.width() == 96  # 48 logical at 200%, crisp not double-sized
        selected = []
        overlay.selected.connect(lambda mode, point: selected.append((mode, point)))
        overlay.mode = 'lemon'
        overlay.finish(QPoint(4200,300))
        assert selected == [('lemon', QPoint(4200,300))]
    finally:
        overlay.shutdown()
        overlay.close()


def test_floating_text_and_quick_chat_are_readable_on_4k(app):
    bubble = SpeechBubble()
    popup = QuickChatPopup('Arfoxia')
    try:
        bubble.show_message('Hola, este texto debe ser legible.', 2500, monitor(3840,2160))
        assert '28px' in bubble.label.styleSheet()
        apply_window_scale(popup, monitor(3840,2160))
        assert popup.width() >= 780
        assert popup.font().pointSizeF() >= 20
    finally:
        bubble.close()
        popup.close()


def test_4k_at_150_percent_uses_crisp_96_physical_pixel_pointer(app, monkeypatch):
    screen = monitor(2560,1440,1.5)
    monkeypatch.setattr(QApplication, 'screenAt', lambda _: screen)
    overlay = PlacementOverlay()
    overlay.preview_source = QPixmap(48,48)
    overlay.preview_source.fill(QColor('yellow'))
    try:
        overlay._move_preview(QPoint(1000,500))
        assert overlay.ui_scale == 1.333
        assert overlay.preview_pixmap.width() == 96
        assert overlay.preview_pixmap.deviceIndependentSize().width() == 64
    finally:
        overlay.close()
