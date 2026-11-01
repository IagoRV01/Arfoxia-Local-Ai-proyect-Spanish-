import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QEvent
from PySide6.QtGui import QColor, QPixmap, QCursor, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QTextBrowser
from PIL import Image

from glaceon_companion.desktop_scale import apply_window_scale, readability_scale, unscaled_stylesheet, logical_pixmap_mask
from glaceon_companion.desktop_interactions import DesktopPropWindow, PlacementOverlay
from glaceon_companion.ui import QuickChatPopup, SpeechBubble, image_to_pixmap


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def monitor(width, height, dpr=1.0, x=0, y=0):
    return SimpleNamespace(geometry=lambda: QRect(x, y, width, height),
        availableGeometry=lambda: QRect(x, y, width, height - 40),
        devicePixelRatio=lambda: dpr)


@pytest.mark.parametrize('logical,dpr,expected', [((1920,1080),1,1), ((3840,2160),1,2),
    ((2560,1440),1.5,4/3), ((1920,1080),2,1), ((3840,1080),1,1), ((7680,4320),1,4),
    ((1536,864),2.5,.8), ((1280,720),1.5,2/3)])
def test_scale_normalizes_physical_resolution_without_double_dpi(logical, dpr, expected):
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


@pytest.mark.parametrize('dpr', [1, 1.25, 1.5, 2, 2.5])
def test_all_elements_share_exact_1080p_to_4k_ratio(app, monkeypatch, tmp_path, dpr):
    screen = monitor(round(3840 / dpr), round(2160 / dpr), dpr)
    factor = readability_scale(screen)
    monkeypatch.setattr(QApplication, 'screenAt', lambda _: screen)
    image = Image.new('RGBA', (32, 40), 'cyan')
    image.putpixel((0, 0), (0, 0, 0, 0))
    source = image_to_pixmap(image)
    asset = tmp_path / 'prop.png'
    assert source.save(str(asset))
    prop = DesktopPropWindow(asset, (32, 40))
    overlay = PlacementOverlay()
    overlay.preview_source = source
    window = QDialog()
    window.resize(600, 400)
    window.setMinimumWidth(430)
    window.setStyleSheet('QLabel{font-size:14px;}')
    layout = QVBoxLayout(window)
    sidebar = QLabel('Conversaciones')
    sidebar.setMinimumWidth(205)
    sidebar.setMaximumWidth(280)
    browser = QTextBrowser()
    browser.document().setDefaultStyleSheet('td{padding:4px 7px;}')
    layout.addWidget(sidebar)
    layout.addWidget(browser)
    try:
        pet_frame = image_to_pixmap(image, 4 * factor, dpr)
        assert pet_frame.width() == 256  # twice the 128px Full HD reference
        assert pet_frame.height() == 320
        prop.refresh_scale(screen)
        assert prop.display_pixmap.width() == 64  # twice the 32px reference
        assert prop.display_pixmap.height() == 80
        assert prop.mask().boundingRect().width() == pytest.approx(64 / dpr, abs=1)
        anchor = prop.geometry().center()
        for _ in range(3):
            prop.refresh_scale(monitor(1920, 1080))
            assert prop.geometry().center() == anchor
            prop.refresh_scale(screen)
            assert prop.geometry().center() == anchor
        assert logical_pixmap_mask(pet_frame).boundingRect().width() == pytest.approx(256 / dpr, abs=1)
        overlay._move_preview(QPoint(100, 100))
        assert overlay.preview_pixmap.height() == 96  # twice the 48px cursor
        apply_window_scale(window, screen)
        assert window.width() * dpr == pytest.approx(1200, abs=dpr)
        assert window.minimumWidth() * dpr == pytest.approx(860, abs=dpr)
        assert sidebar.maximumWidth() * dpr == pytest.approx(560, abs=dpr)
        assert window.font().pointSizeF() * dpr == pytest.approx(20, abs=.02)
        assert f'{14 * factor:g}px' in window.styleSheet()
        assert f'{7 * factor:g}px' in browser.document().defaultStyleSheet()
        apply_window_scale(window, monitor(1920, 1080))
        assert window.width() == 600
        assert window.minimumWidth() == 430
        assert sidebar.maximumWidth() == 280
        assert browser.document().defaultStyleSheet() == 'td{padding:4px 7px;}'
    finally:
        window.close()
        prop.close()
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
        assert overlay.ui_scale == 4/3
        assert overlay.preview_pixmap.width() == 96
        assert overlay.preview_pixmap.deviceIndependentSize().width() == 64
    finally:
        overlay.close()


@pytest.mark.parametrize('mode', ['lemon', 'bed'])
def test_placement_tracks_each_screen_not_a_mixed_dpi_virtual_window(app, monkeypatch, mode):
    left = monitor(1920, 1080, 1, x=-1920, y=200)
    main = monitor(2560, 1440, 1.5)
    upper = monitor(1280, 720, 1.5, x=3840, y=-800)
    screens = [left, main, upper]
    monkeypatch.setattr(QApplication, 'screens', lambda: screens)
    monkeypatch.setattr(QApplication, 'primaryScreen', lambda: main)
    monkeypatch.setattr(QApplication, 'screenAt', lambda p: next(
        (screen for screen in screens if screen.geometry().contains(p)), None))
    overlay = PlacementOverlay()
    overlay.mode = mode
    overlay.preview_source = QPixmap(48, 48)
    overlay.preview_source.fill(QColor('yellow'))
    try:
        for screen in [main, left, upper, main]:
            point = screen.availableGeometry().center()
            monkeypatch.setattr(QCursor, 'pos', lambda value=point: value)
            overlay._sync_preview_to_cursor()
            assert overlay.geometry() == screen.availableGeometry()
            assert overlay.active_screen is screen
            assert overlay.mapToGlobal(overlay.preview_center) == point
            assert overlay.rect().contains(overlay.preview_center)
        # Qt Windows desktops can have logical gaps: don't jump to primary.
        overlay._move_preview(upper.availableGeometry().center())
        overlay._move_preview(QPoint(3200, -300))
        assert overlay.active_screen is upper
        assert overlay.geometry() == upper.availableGeometry()
        # Resolution/taskbar changes update the area even without a DPR change.
        upper.availableGeometry = lambda: QRect(3840, -800, 1200, 640)
        overlay._move_preview(upper.availableGeometry().center())
        assert overlay.geometry() == upper.availableGeometry()
        # Removal of the previous screen recovers to a remaining screen.
        screens.remove(upper)
        overlay._move_preview(main.availableGeometry().center())
        assert overlay.active_screen is main
    finally:
        overlay.shutdown()
        overlay.close()


@pytest.mark.parametrize('mode', ['lemon', 'bed'])
def test_placement_click_uses_the_local_preview_even_with_stale_global_event(app, mode):
    overlay = PlacementOverlay()
    overlay.setGeometry(QApplication.primaryScreen().availableGeometry())
    overlay.mode = mode
    selected = []
    overlay.selected.connect(lambda kind, point: selected.append((kind, point)))
    local = QPoint(220, 240)
    expected = overlay.mapToGlobal(local)
    # An event generated around a screen/DPI transition may carry stale global
    # coordinates. Its local position and native map are authoritative.
    event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(local), QPointF(-9999, -9999),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    try:
        QApplication.sendEvent(overlay, event)
        assert selected == [(mode, expected)]
        assert not overlay.isVisible()
        assert not overlay.preview_timer.isActive()
        assert not overlay.timeout.isActive()
        assert overlay.mode == ''
        assert not overlay.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
    finally:
        overlay.shutdown()
        overlay.close()
