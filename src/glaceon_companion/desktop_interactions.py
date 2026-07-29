from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from .codex_presence import ReservedRect


def choose_reachable_x(
    current_x: int,
    desired_x: int,
    ranges: Iterable[tuple[int, int]],
) -> int | None:
    """Clamp a target to the safe segment containing the pet.

    Staying inside the current segment prevents a fetch route from crossing an
    obstacle such as Eevee. If the current point is already outside every
    segment, the closest segment is used as a recovery path.
    """

    normalized = [(min(int(a), int(b)), max(int(a), int(b))) for a, b in ranges]
    if not normalized:
        return None
    current = int(current_x)
    desired = int(desired_x)
    containing = [bounds for bounds in normalized if bounds[0] <= current <= bounds[1]]
    if containing:
        low, high = containing[0]
    else:
        low, high = min(
            normalized,
            key=lambda bounds: min(abs(current - bounds[0]), abs(current - bounds[1])),
        )
    return max(low, min(desired, high))


def foot_is_over_bed(sprite: ReservedRect, bed: ReservedRect) -> bool:
    """Return whether the visible pet's foot point is on the mattress area."""

    foot_x = sprite.x + sprite.width // 2
    foot_y = sprite.bottom - 1
    horizontal_margin = max(4, round(bed.width * 0.12))
    top_margin = max(4, round(bed.height * 0.08))
    return (
        bed.x + horizontal_margin <= foot_x < bed.right - horizontal_margin
        and bed.y + top_margin <= foot_y < bed.bottom
    )


def sleeping_window_position(
    bed: ReservedRect,
    *,
    window_width: int,
    window_height: int,
    sprite_bottom_margin: int = 12,
) -> tuple[int, int]:
    """Place the centred pet sprite over the lower part of the mattress."""

    target_center_x = bed.x + bed.width // 2
    target_sprite_bottom = bed.y + round(bed.height * 0.72)
    return (
        target_center_x - int(window_width) // 2,
        target_sprite_bottom - int(window_height) + int(sprite_bottom_margin),
    )


def normalized_item_position(
    item: ReservedRect,
    screen: ReservedRect,
) -> tuple[float, float]:
    """Store an item's top-left as resolution-independent screen ratios."""

    span_x = max(1, screen.width - item.width)
    span_y = max(1, screen.height - item.height)
    x_ratio = (item.x - screen.x) / span_x
    y_ratio = (item.y - screen.y) / span_y
    return max(0.0, min(1.0, x_ratio)), max(0.0, min(1.0, y_ratio))


def item_position_from_ratios(
    screen: ReservedRect,
    *,
    item_width: int,
    item_height: int,
    x_ratio: float,
    y_ratio: float,
) -> tuple[int, int]:
    """Restore and clamp an item inside a screen's available geometry."""

    safe_x = max(0.0, min(1.0, float(x_ratio)))
    safe_y = max(0.0, min(1.0, float(y_ratio)))
    span_x = max(0, screen.width - int(item_width))
    span_y = max(0, screen.height - int(item_height))
    return (
        screen.x + round(span_x * safe_x),
        screen.y + round(span_y * safe_y),
    )


def parabolic_point(
    start: QPoint,
    end: QPoint,
    progress: float,
    *,
    arc_height: int = 120,
) -> QPoint:
    """Interpolate a screen point along a simple throw arc."""

    value = max(0.0, min(1.0, float(progress)))
    x = start.x() + (end.x() - start.x()) * value
    baseline_y = start.y() + (end.y() - start.y()) * value
    y = baseline_y - math.sin(math.pi * value) * max(0, int(arc_height))
    return QPoint(round(x), round(y))


class DesktopPropWindow(QWidget):
    """Transparent window used by physical pet objects.

    Animated props stay click-through, while persistent props such as the bed
    can opt into direct dragging without taking keyboard focus.
    """

    dragged = Signal(QPoint)
    drag_finished = Signal(QPoint)

    def __init__(
        self,
        asset_path: Path,
        display_size: tuple[int, int],
        *,
        pixelated: bool = True,
        draggable: bool = False,
    ) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if not draggable:
            flags |= Qt.WindowType.WindowTransparentForInput
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.draggable = bool(draggable)
        self.drag_pointer_origin: QPoint | None = None
        self.drag_window_origin: QPoint | None = None
        if self.draggable:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.source = QPixmap(str(asset_path))
        if self.source.isNull():
            raise FileNotFoundError(f"No se pudo cargar el recurso visual: {asset_path}")
        self.pixelated = pixelated
        self.display_pixmap = QPixmap()
        self.set_display_size(*display_size)

    def set_display_size(self, width: int, height: int) -> None:
        transform = (
            Qt.TransformationMode.FastTransformation
            if self.pixelated
            else Qt.TransformationMode.SmoothTransformation
        )
        self.display_pixmap = self.source.scaled(
            max(1, int(width)),
            max(1, int(height)),
            Qt.AspectRatioMode.KeepAspectRatio,
            transform,
        )
        self.setFixedSize(self.display_pixmap.size())
        try:
            self.setMask(QRegion(self.display_pixmap.mask()))
        except TypeError:
            self.clearMask()
        self.update()

    def screen_rect(self) -> ReservedRect:
        return ReservedRect(self.x(), self.y(), self.width(), self.height())

    def move_center_to(self, point: QPoint) -> None:
        self.move(point.x() - self.width() // 2, point.y() - self.height() // 2)

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, not self.pixelated)
        painter.drawPixmap(0, 0, self.display_pixmap)

    def mousePressEvent(self, event: object) -> None:
        if self.draggable and event.button() == Qt.MouseButton.LeftButton:
            self.drag_pointer_origin = event.globalPosition().toPoint()
            self.drag_window_origin = self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: object) -> None:
        if (
            self.draggable
            and self.drag_pointer_origin is not None
            and self.drag_window_origin is not None
        ):
            point = event.globalPosition().toPoint()
            self.move(self.drag_window_origin + point - self.drag_pointer_origin)
            self.dragged.emit(self.pos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: object) -> None:
        if (
            self.draggable
            and event.button() == Qt.MouseButton.LeftButton
            and self.drag_pointer_origin is not None
        ):
            self.drag_pointer_origin = None
            self.drag_window_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.drag_finished.emit(self.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PlacementOverlay(QWidget):
    """Temporary desktop layer for a lemon throw or bed placement."""

    selected = Signal(str, QPoint)
    cancelled = Signal(str)

    def __init__(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.mode = ""
        self.instruction = ""
        self.preview_pixmap = QPixmap()
        self.preview_center = QPoint()
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(16)
        self.preview_timer.timeout.connect(self._sync_preview_to_cursor)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.cancel)

    @staticmethod
    def virtual_available_geometry() -> QRect:
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1, 1)
        geometry = QRect(screens[0].availableGeometry())
        for screen in screens[1:]:
            geometry = geometry.united(screen.availableGeometry())
        return geometry

    def begin(
        self,
        mode: str,
        cursor_pixmap: QPixmap,
        instruction: str,
        *,
        timeout_ms: int = 30_000,
    ) -> None:
        self.mode = str(mode)
        self.instruction = str(instruction)
        self.setGeometry(self.virtual_available_geometry())
        self.preview_pixmap = cursor_pixmap.scaled(
            48,
            48,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.preview_center = QCursor.pos() - self.geometry().topLeft()
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.grabKeyboard()
        self.preview_timer.start()
        self.timeout.start(max(1_000, int(timeout_ms)))
        self.update()

    def finish(self, point: QPoint) -> None:
        if not self.mode:
            return
        mode = self.mode
        self._cleanup()
        self.selected.emit(mode, point)

    def cancel(self) -> None:
        if not self.mode:
            return
        mode = self.mode
        self._cleanup()
        self.cancelled.emit(mode)

    def _cleanup(self) -> None:
        self.preview_timer.stop()
        self.timeout.stop()
        self.releaseKeyboard()
        self.unsetCursor()
        self.hide()
        self.mode = ""
        self.instruction = ""
        self.preview_pixmap = QPixmap()
        self.preview_center = QPoint()

    def shutdown(self) -> None:
        """Release any native input grab without emitting a user cancellation."""

        if self.mode or self.isVisible():
            self._cleanup()

    def keyPressEvent(self, event: object) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._move_preview(event.globalPosition().toPoint())
            self.finish(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.cancel()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: object) -> None:
        if self.mode:
            self._move_preview(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _move_preview(self, global_point: QPoint) -> None:
        self.preview_center = global_point - self.geometry().topLeft()
        self.update()

    def _sync_preview_to_cursor(self) -> None:
        if self.mode:
            self._move_preview(QCursor.pos())

    def paintEvent(self, event: object) -> None:
        del event
        if not self.instruction:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # A nearly transparent fill keeps the native layered window
        # mouse-active over its complete geometry on Windows.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        if not self.preview_pixmap.isNull():
            painter.drawPixmap(
                self.preview_center.x() - self.preview_pixmap.width() // 2,
                self.preview_center.y() - self.preview_pixmap.height() // 2,
                self.preview_pixmap,
            )
        panel_width = min(520, max(300, self.fontMetrics().horizontalAdvance(self.instruction) + 48))
        panel = QRect((self.width() - panel_width) // 2, 24, panel_width, 54)
        painter.setPen(QColor(145, 232, 255, 230))
        painter.setBrush(QColor(7, 24, 41, 235))
        painter.drawRoundedRect(panel, 15, 15)
        painter.setPen(QColor(237, 250, 255))
        painter.drawText(panel, Qt.AlignmentFlag.AlignCenter, self.instruction)
