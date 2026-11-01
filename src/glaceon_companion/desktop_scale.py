"""Per-monitor readability in Qt logical pixels; never changes Windows settings."""
from __future__ import annotations

import re
from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QFont, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QWidget, QLayout, QTextEdit


def readability_scale(screen) -> float:
    if screen is None:
        return 1.0
    geometry = screen.geometry()
    dpr = screen.devicePixelRatio() if hasattr(screen, 'devicePixelRatio') else 1.0
    # One 1080p reference for every element. Undo Qt's native DPR exactly;
    # never round the scale factor (4K/150% is 4/3, not 1.333 or 6/4).
    physical_ratio = max(1.0, min(4.0, geometry.width() * dpr / 1920,
                                  geometry.height() * dpr / 1080))
    return physical_ratio / dpr


def logical_pixmap_size(pixmap):
    return pixmap.deviceIndependentSize().toSize()


def logical_pixmap_mask(pixmap):
    dpr = pixmap.devicePixelRatio()
    return QTransform().scale(1 / dpr, 1 / dpr).map(QRegion(pixmap.mask()))


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
    size_before = window.size()
    font = QFont(QApplication.font())
    font.setPointSizeF(max(10.0, font.pointSizeF()) * scale)
    window.setFont(font)
    styles = getattr(window, '_readability_styles', {})
    constraints = getattr(window, '_readability_constraints', {})
    document_styles = getattr(window, '_readability_document_styles', {})
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
        current_limits = (widget.minimumSize(), widget.maximumSize())
        original_limits, last_limits = constraints.get(widget, (current_limits, current_limits))
        if current_limits != last_limits:
            original_limits = current_limits
        minimum, maximum = original_limits
        # Qt's unlimited sentinel must remain unlimited, not become a 4K limit.
        def dimension(value):
            return value if value == 16777215 else min(16777215, round(value * scale))
        widget.setMinimumSize(dimension(minimum.width()), dimension(minimum.height()))
        widget.setMaximumSize(dimension(maximum.width()), dimension(maximum.height()))
        constraints[widget] = (original_limits, (widget.minimumSize(), widget.maximumSize()))
        if isinstance(widget, QTextEdit):
            document = widget.document()
            current_style = document.defaultStyleSheet()
            base_style, last_style = document_styles.get(widget, (current_style, current_style))
            if current_style != last_style:
                base_style = current_style
            updated_style = scaled_stylesheet(base_style, scale)
            if updated_style != current_style:
                document.setDefaultStyleSheet(updated_style)
            document_styles[widget] = (base_style, updated_style)
    window._readability_styles = styles
    window._readability_constraints = constraints
    window._readability_document_styles = document_styles
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
        window.resize(min(round(size_before.width() * scale / previous), area.width()),
                      min(round(size_before.height() * scale / previous), area.height()))
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
