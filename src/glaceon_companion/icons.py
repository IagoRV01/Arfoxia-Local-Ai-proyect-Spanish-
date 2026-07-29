from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QRadialGradient


SNOWFLAKE_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _snowflake_pixmap(size: int) -> QPixmap:
    """Render Arfoxia's Windows icon at one native size."""

    side = max(16, int(size))
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    inset = max(1.0, side * 0.035)
    bounds = QRectF(inset, inset, side - (2 * inset), side - (2 * inset))
    radius = side * 0.22
    gradient = QRadialGradient(
        QPointF(side * 0.42, side * 0.34),
        side * 0.72,
    )
    gradient.setColorAt(0.0, QColor("#174b6a"))
    gradient.setColorAt(0.62, QColor("#0b2c45"))
    gradient.setColorAt(1.0, QColor("#061927"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(bounds, radius, radius)

    center = QPointF(side / 2.0, side / 2.0)
    arm_length = side * 0.345
    branch_start = arm_length * 0.57
    branch_length = arm_length * 0.32
    pen = QPen(
        QColor("#b9f3ff"),
        max(1.35, side * 0.065),
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    for degrees in range(0, 360, 60):
        angle = math.radians(degrees)
        direction = QPointF(math.cos(angle), math.sin(angle))
        tip = center + direction * arm_length
        painter.drawLine(center, tip)
        branch_root = center + direction * branch_start
        for branch_degrees in (-42, 42):
            branch_angle = angle + math.radians(branch_degrees)
            branch_tip = branch_root + QPointF(
                math.cos(branch_angle) * branch_length,
                math.sin(branch_angle) * branch_length,
            )
            painter.drawLine(branch_root, branch_tip)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#edfaff"))
    painter.drawEllipse(center, max(1.0, side * 0.048), max(1.0, side * 0.048))
    painter.end()
    return pixmap


def snowflake_icon() -> QIcon:
    """Return a multi-resolution snowflake icon for Windows and Qt."""

    icon = QIcon()
    for size in SNOWFLAKE_ICON_SIZES:
        icon.addPixmap(_snowflake_pixmap(size))
    return icon
