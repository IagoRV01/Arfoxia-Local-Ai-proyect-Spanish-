"""Per-monitor readability in Qt logical pixels; never changes Windows settings."""
from __future__ import annotations

import re
from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget, QLayout


def readability_scale(screen) -> float:
    if screen is None:
        return 1.0
    # Qt has already divided geometry by Windows' display scaling. Using
    # logical dimensions avoids multiplying a 4K/200% desktop a second time.
    geometry = screen.geometry()
    return round(max(1.0, min(2.5, geometry.width() / 1920, geometry.height() / 1080)), 3)


def screen_for_widget(widget: QWidget):
    return QApplication.screenAt(widget.frameGeometry().center()) or widget.screen() or QApplication.primaryScreen()


def scaled_stylesheet(value: str, scale: float) -> str:
    return re.sub(r'(?<![\w.-])(\d+(?:\.\d+)?)px\b',
                  lambda match: f'{float(match[1]) * scale:g}px', value)


def unscaled_stylesheet(widget: QWidget) -> str:
    return getattr(widget, '_readability_styles', {}).get(widget, (widget.styleSheet(), ''))[0]


def apply_window_scale(window: QWidget, screen=None) -> float:
    screen = screen or screen_for_widget(window)
    scale = readability_scale(screen)
    previous = getattr(window, '_readability_scale', 1.0)
    if getattr(window, '_scale_initialized', False) and scale == previous:
        return scale
    window._scale_initialized = True
    window._readability_scale = scale
    font = QFont(QApplication.font())
    font.setPointSizeF(max(10.0, font.pointSizeF()) * scale)
    window.setFont(font)
    styles = getattr(window, '_readability_styles', {})
    for widget in [window, *window.findChildren(QWidget)]:
        if widget.window() is not window:
            continue
        current = widget.styleSheet()
        base, last = styles.get(widget, (current, current))
        if current != last:
            base = current  # a later state-button style is still authored at 1x
        updated = scaled_stylesheet(base, scale)
        if updated != current:
            widget.setStyleSheet(updated)
        styles[widget] = (base, updated)
    window._readability_styles = styles
    margins = getattr(window, '_readability_layouts', {})
    for layout in window.findChildren(QLayout):
        if layout.parentWidget() is not None and layout.parentWidget().window() is not window:
            continue
        if layout not in margins:
            m = layout.contentsMargins()
            margins[layout] = ((m.left(), m.top(), m.right(), m.bottom()), layout.spacing())
        original, spacing = margins[layout]
        layout.setContentsMargins(*(round(value * scale) for value in original))
        if spacing >= 0:
            layout.setSpacing(round(spacing * scale))
    window._readability_layouts = margins
    if screen is not None and not window.isMaximized() and not window.isFullScreen():
        area = screen.availableGeometry().adjusted(12, 12, -12, -12)
        window.resize(min(round(window.width() * scale / previous), area.width()),
                      min(round(window.height() * scale / previous), area.height()))
        window.move(max(area.left(), min(window.x(), area.right() + 1 - window.width())),
                    max(area.top(), min(window.y(), area.bottom() + 1 - window.height())))
    return scale


class WindowScaleController(QObject):
    """Keep a visible dialog readable while it moves between mixed-DPI screens."""
    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window = window
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        window.installEventFilter(self)

    def refresh(self):
        if self.window.isVisible():
            apply_window_scale(self.window)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show:
            self.refresh()
            self.timer.start()
        elif event.type() in {QEvent.Type.Hide, QEvent.Type.Close}:
            self.timer.stop()
        return False


def install_window_scaling(window: QWidget) -> None:
    window._readability_controller = WindowScaleController(window)
