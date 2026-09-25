from __future__ import annotations

import asyncio
import ctypes
import html
import json
import random
import shutil
import socket
import subprocess
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import qrcode
from PIL import Image
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSignalBlocker,
    QUrl,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
    QRegion,
    QTextCharFormat,
    QTextBlockFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSystemTrayIcon,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .config import PROJECT_ROOT
from .codex_presence import (
    CodexPresence,
    ReservedRect,
    detect_codex_presence,
    horizontal_safe_ranges,
    nearest_safe_x,
    overlay_window_rect,
    rectangles_overlap,
)
from .desktop_interactions import (
    DesktopPropWindow,
    PlacementOverlay,
    choose_reachable_x,
    foot_is_over_bed,
    item_position_from_ratios,
    normalized_item_position,
    parabolic_point,
    sleeping_window_position,
)
from .icons import snowflake_icon
from .services import CompanionService
from .sprites import SpriteLibrary


MOBILE_UI_REVISION = "10"

SAFE_MARKDOWN_FEATURES = (
    QTextDocument.MarkdownFeature.MarkdownDialectGitHub
    | QTextDocument.MarkdownFeature.MarkdownNoHTML
)
MARKDOWN_PUNCTUATION = frozenset(r"\`*_{}[]<>()#+-.!|>")


CRY_PROFILES: dict[str, tuple[str, float, float]] = {
    "feed": ("legacy", 0.94, 0.72),
    "pet": ("legacy", 1.08, 0.78),
    "play": ("latest", 1.12, 1.00),
    "sleep": ("legacy", 0.82, 0.52),
    "wake": ("latest", 1.04, 0.90),
    "chat": ("latest", 0.96, 0.46),
    "eevee": ("latest", 1.04, 0.58),
}

INTERACTION_SPEECH: dict[str, tuple[str, ...]] = {
    "feed": ("¡Gla! Qué rico.", "Ceon~ ❄", "¡Gla-gla!"),
    "pet": ("Ceon~", "*agita la cola* ¡Gla!", "Glace… ❄"),
    "play": ("¡Gla-ceon! ✨", "¡Gla-gla!", "*da un pequeño salto*"),
    "sleep": ("Gla… zzz", "Ceon… ❄", "*se acurruca*"),
    "wake": ("¡Glaceon! ❄", "¡Gla!", "*estira las patas*"),
}

EEVEE_GREETING_SPEECH = (
    "¡Gla! Eevee está aquí. ❄",
    "*saluda a Eevee con la cola* Ceon~",
    "¡Gla-ceon! Hola, Eevee.",
)

EEVEE_COMPANION_SPEECH = (
    "*mira a Eevee con curiosidad* Glace…",
    "¡Gla! Eevee, ¿jugamos?",
    "*se sienta junto a Eevee sin invadir su espacio* Ceon~",
    "Gla-ceon… *responde al movimiento de Eevee* ❄",
)

PROP_DIR = PROJECT_ROOT / "assets" / "external" / "props"
BERRY_SIZE = (90, 90)
LEMON_SIZE = (68, 68)
BED_SIZE = (100, 200)


def is_short_dialogue(text: str, max_chars: int = 180) -> bool:
    value = text.strip()
    return bool(value) and "\n" not in value and len(value) <= max_chars


def escape_markdown_text(value: str) -> str:
    return "".join(
        f"\\{character}" if character in MARKDOWN_PUNCTUATION else character
        for character in value
    )


def is_safe_https_url(value: QUrl | str) -> bool:
    raw = value if isinstance(value, str) else value.toString()
    if not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return False
    url = QUrl(value)
    return (
        url.isValid()
        and not url.isRelative()
        and url.scheme().casefold() == "https"
        and bool(url.host())
        and not url.userName()
        and not url.password()
    )


class SafeMarkdownBrowser(QTextBrowser):
    """Rich chat transcript that never fetches resources from Markdown."""

    def loadResource(self, resource_type: int, name: QUrl) -> Any:
        if resource_type == QTextDocument.ResourceType.ImageResource:
            return QImage()
        return super().loadResource(resource_type, name)


def image_to_pixmap(image: Image.Image, scale: int = 1) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
    pixmap = QPixmap.fromImage(qimage)
    if scale != 1:
        pixmap = pixmap.scaled(
            rgba.width * scale,
            rgba.height * scale,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
    return pixmap


class CryPlayer(QObject):
    def __init__(self, service: CompanionService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.last_played_at = 0.0

    def play(self, interaction: str) -> bool:
        config = self.service.config
        profile = CRY_PROFILES.get(interaction)
        if not config.sound_enabled or not profile:
            return False
        now = time.monotonic()
        if (now - self.last_played_at) * 1000 < config.sound_cooldown_ms:
            return False
        variant, playback_rate, gain = profile
        path = PROJECT_ROOT / "assets" / "external" / "pokeapi" / "cries" / f"glaceon-{variant}.ogg"
        if not path.exists():
            return False
        self.player.stop()
        self.output.setVolume(max(0.0, min(1.0, config.sound_volume * gain)))
        self.player.setPlaybackRate(playback_rate)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.last_played_at = now
        return True


class SpeechBubble(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.label.setStyleSheet("color:#edfaff;background:transparent;font-size:14px;")
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def show_message(self, text: str, duration_ms: int) -> None:
        value = " ".join(text.strip().split())
        metrics = self.label.fontMetrics()
        content_width = max(120, min(300, metrics.horizontalAdvance(value) + 8))
        bounds = metrics.boundingRect(
            QRect(0, 0, content_width, 1000),
            int(Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs),
            value,
        )
        content_height = max(metrics.height() + 4, bounds.height() + 4)
        self.label.setText(value)
        self.label.setGeometry(16, 10, content_width, content_height)
        self.setFixedSize(content_width + 32, content_height + 32)
        self.show()
        self.raise_()
        self.hide_timer.start(max(2200, duration_ms))

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(1, 1, self.width() - 2, self.height() - 12)
        path = QPainterPath()
        path.addRoundedRect(body, 15, 15)
        tail_x = self.width() * 0.68
        path.moveTo(tail_x - 10, body.bottom() - 1)
        path.lineTo(tail_x, self.height() - 1)
        path.lineTo(tail_x + 13, body.bottom() - 1)
        path.closeSubpath()
        painter.fillPath(path, QColor(7, 24, 41, 242))
        painter.setPen(QColor(145, 232, 255, 210))
        painter.drawPath(path)


class QuickChatPopup(QWidget):
    submitted = Signal(str)
    DEFAULT_INACTIVITY_TIMEOUT_MS = 15_000

    def __init__(
        self,
        name: str,
        parent: QWidget | None = None,
        inactivity_timeout_ms: int = DEFAULT_INACTIVITY_TIMEOUT_MS,
    ) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setObjectName("quickChat")
        self.setStyleSheet(
            "QLineEdit{background:transparent;color:#edfaff;border:0;padding:8px;}"
            "QPushButton{background:#235a7c;color:white;border:0;border-radius:9px;padding:8px 12px;}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 17)
        self.input = QLineEdit()
        self.input.setPlaceholderText(f"Hablar con {name}…")
        self.send_button = QPushButton("Enviar")
        layout.addWidget(self.input, 1)
        layout.addWidget(self.send_button)
        self.input.returnPressed.connect(self.submit)
        self.send_button.clicked.connect(self.submit)
        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.setSingleShot(True)
        self.inactivity_timer.setInterval(max(1, inactivity_timeout_ms))
        self.inactivity_timer.timeout.connect(self.hide)
        for widget in (self, self.input, self.send_button):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        self.resize(390, 62)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.hide()
            return True
        if event.type() in {
            QEvent.Type.KeyPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusIn,
        }:
            self._record_activity()
        return super().eventFilter(watched, event)

    def _record_activity(self) -> None:
        if self.isVisible():
            self.inactivity_timer.start()

    def submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.hide()
        self.submitted.emit(text)

    def show_and_focus(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        self.inactivity_timer.start()

    def hideEvent(self, event: Any) -> None:
        self.inactivity_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(1, 1, self.width() - 2, self.height() - 12)
        path = QPainterPath()
        path.addRoundedRect(body, 14, 14)
        tail_x = self.width() * 0.68
        path.moveTo(tail_x - 10, body.bottom() - 1)
        path.lineTo(tail_x, self.height() - 1)
        path.lineTo(tail_x + 13, body.bottom() - 1)
        path.closeSubpath()
        painter.fillPath(path, QColor(7, 24, 41, 248))
        painter.setPen(QColor(145, 232, 255, 225))
        painter.drawPath(path)


class Bridge(QObject):
    chat_ready = Signal(object)
    chat_error = Signal(object)
    authorization_ready = Signal(object)
    authorization_error = Signal(str)
    model_mode_ready = Signal(object)
    model_mode_error = Signal(str)
    model_status_ready = Signal(object)
    model_status_error = Signal(str)
    model_unload_ready = Signal()
    model_unload_error = Signal(str)

    def __init__(self, service: CompanionService) -> None:
        super().__init__()
        self.service = service
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arfoxia-chat")

    def chat(
        self,
        text: str,
        attachment_ids: list[str] | None = None,
        *,
        conversation_id: str | None = None,
        research_mode: bool = False,
    ) -> str:
        request_id = uuid.uuid4().hex
        future = self.pool.submit(
            asyncio.run,
            self.service.chat(
                text,
                attachment_ids=attachment_ids or [],
                conversation_id=conversation_id,
                research_mode=research_mode,
            ),
        )

        def finished(item: Any) -> None:
            try:
                self.chat_ready.emit(
                    {
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "result": item.result(),
                    }
                )
            except Exception as exc:
                self.chat_error.emit(
                    {
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "message": str(exc),
                    }
                )

        future.add_done_callback(finished)
        return request_id

    def authorize(self, challenge_id: str, password: str) -> None:
        future = self.pool.submit(
            self.service.authorize_action, challenge_id, password
        )

        def finished(item: Any) -> None:
            try:
                self.authorization_ready.emit(item.result())
            except Exception as exc:
                self.authorization_error.emit(str(exc))

        future.add_done_callback(finished)

    def set_model_mode(self, mode: str) -> None:
        future = self.pool.submit(
            asyncio.run,
            self.service.set_model_mode(mode),
        )

        def finished(item: Any) -> None:
            try:
                self.model_mode_ready.emit(item.result())
            except Exception as exc:
                self.model_mode_error.emit(str(exc))

        future.add_done_callback(finished)

    def request_model_status(self) -> None:
        future = self.pool.submit(asyncio.run, self.service.model_status())

        def finished(item: Any) -> None:
            try:
                self.model_status_ready.emit(item.result())
            except Exception as exc:
                self.model_status_error.emit(str(exc))

        future.add_done_callback(finished)

    def unload_models(self) -> None:
        future = self.pool.submit(asyncio.run, self.service.unload_model())

        def finished(item: Any) -> None:
            try:
                item.result()
                self.model_unload_ready.emit()
            except Exception as exc:
                self.model_unload_error.emit(str(exc))

        future.add_done_callback(finished)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


class AuthorizationDialog(QDialog):
    """Collect a local password without sending it through chat or Ollama."""

    def __init__(
        self,
        summary: str,
        *,
        setup: bool = False,
        error: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setup = setup
        self.setWindowTitle("Seguridad de Arfoxia")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setStyleSheet(
            "QDialog{background:#0b2336;color:#edfaff;}"
            "QLineEdit{background:#071829;color:#edfaff;border:1px solid #27516b;"
            "border-radius:8px;padding:9px;} QPushButton{background:#235a7c;color:white;"
            "border:0;border-radius:9px;padding:9px 14px;} QLabel{color:#dff7ff;}"
        )
        layout = QVBoxLayout(self)
        title = QLabel("Configurar contraseña local" if setup else "Autorizar acción importante")
        title.setStyleSheet("font-size:17px;font-weight:600;color:#91e8ff;")
        detail = QLabel(summary)
        detail.setTextFormat(Qt.TextFormat.PlainText)
        detail.setWordWrap(True)
        notice = QLabel(
            "La contraseña se comprueba aquí, en el PC. No se envía al chat, a Ollama ni al historial."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color:#9fc4d4;")
        if setup:
            warning = QLabel(
                "Mínimo 4 caracteres. Como la clave elegida apareció en esta conversación, "
                "es más seguro configurar una frase nueva."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color:#ffd38a;")
            layout.addWidget(warning)
        self.error_label = QLabel(error)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#ff9daf;")
        self.password_input = self._password_field("Contraseña local")
        self.confirm_input = self._password_field("Repite la contraseña") if setup else None
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancelar")
        authorize = QPushButton("Guardar y autorizar" if setup else "Autorizar")
        authorize.setStyleSheet("background:#2c7897;")
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(authorize)
        layout.insertWidget(0, title)
        layout.addWidget(detail)
        layout.addWidget(notice)
        layout.addWidget(self.error_label)
        layout.addWidget(self.password_input)
        if self.confirm_input is not None:
            layout.addWidget(self.confirm_input)
        layout.addLayout(buttons)
        cancel.clicked.connect(self.reject)
        authorize.clicked.connect(self.accept)
        self.password_input.returnPressed.connect(
            self.confirm_input.setFocus if self.confirm_input is not None else self.accept
        )
        if self.confirm_input is not None:
            self.confirm_input.returnPressed.connect(self.accept)

    @staticmethod
    def _password_field(placeholder: str) -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setMaxLength(128)
        field.setClearButtonEnabled(False)
        field.setInputMethodHints(
            Qt.InputMethodHint.ImhHiddenText
            | Qt.InputMethodHint.ImhSensitiveData
            | Qt.InputMethodHint.ImhNoPredictiveText
        )
        return field

    def accept(self) -> None:
        value = self.password_input.text()
        if len(value) < 4:
            self.error_label.setText("La contraseña debe tener al menos 4 caracteres.")
            return
        if self.confirm_input is not None and value != self.confirm_input.text():
            self.error_label.setText("Las dos contraseñas no coinciden.")
            self.confirm_input.clear()
            self.confirm_input.setFocus()
            return
        super().accept()

    def take_password(self) -> str:
        value = self.password_input.text()
        self.password_input.clear()
        if self.confirm_input is not None:
            self.confirm_input.clear()
        return value

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        try:
            # WDA_EXCLUDEFROMCAPTURE keeps this native window out of supported
            # Windows capture APIs while the sensitive field is visible.
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11)
        except (AttributeError, OSError, TypeError):
            pass
        self.password_input.setFocus()


class PasswordSettingsDialog(QDialog):
    def __init__(self, service: CompanionService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        configured = service.authorization.is_configured
        self.setWindowTitle("Contraseña de seguridad")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(True)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Cambia la contraseña que protege apagado, reinicio, archivos y ejecución de programas. "
            "Nunca la escribas en el chat."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.current_input = (
            AuthorizationDialog._password_field("Contraseña actual") if configured else None
        )
        self.new_input = AuthorizationDialog._password_field("Nueva contraseña")
        self.confirm_input = AuthorizationDialog._password_field("Repite la nueva contraseña")
        if self.current_input is not None:
            layout.addWidget(self.current_input)
        layout.addWidget(self.new_input)
        layout.addWidget(self.confirm_input)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color:#b32342;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancelar")
        save = QPushButton("Guardar")
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save_password)

    def save_password(self) -> None:
        new_password = self.new_input.text()
        if len(new_password) < 4:
            self.error_label.setText("La nueva contraseña debe tener al menos 4 caracteres.")
            return
        if new_password != self.confirm_input.text():
            self.error_label.setText("Las dos contraseñas nuevas no coinciden.")
            self.confirm_input.clear()
            return
        current = self.current_input.text() if self.current_input is not None else None
        self.new_input.clear()
        self.confirm_input.clear()
        if self.current_input is not None:
            self.current_input.clear()
        try:
            if current is None:
                self.service.authorization.configure(new_password)
            else:
                self.service.authorization.change_password(current, new_password)
        except Exception as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11)
        except (AttributeError, OSError, TypeError):
            pass


class ChatWindow(QDialog):
    confirm_action = Signal(str, object)
    LEGACY_CONVERSATION_ID = "__legacy__"
    MESSAGE_PAGE_SIZE = 100

    def __init__(self, service: CompanionService, bridge: Bridge) -> None:
        super().__init__()
        self.service = service
        self.bridge = bridge
        self.current_conversation_id: str | None = None
        self._conversation_items: dict[str, QListWidgetItem] = {}
        self._loaded_messages: list[dict[str, Any]] = []
        self._oldest_message_id: Any = None
        self._drafts: dict[str, dict[str, Any]] = {}
        self._switching_conversation = False
        self.pending_requests: dict[str, str] = {}
        self.pending_authorization: dict[str, Any] | None = None
        self.authorization_queue: deque[dict[str, Any]] = deque()
        self.authorization_dialog_open = False
        self.authorization_in_flight = False
        self._authorization_draft_conversation_id: str | None = None
        self.pending_attachments: list[dict[str, Any]] = []
        self.model_labels: dict[str, str] = {}
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowTitle(f"Hablar con {service.config.name}")
        self.setWindowIcon(snowflake_icon())
        self.resize(790, 600)
        self.setStyleSheet(
            "QDialog{background:#0b2336;color:#edfaff;}"
            "QTextBrowser,QLineEdit{background:#071829;color:#edfaff;border:1px solid #27516b;"
            "border-radius:10px;padding:9px;} QPushButton{background:#235a7c;color:white;"
            "border:0;border-radius:10px;padding:9px 14px;} QLabel{color:#9edff5;}"
            "QListWidget{background:#071829;color:#edfaff;border:1px solid #27516b;"
            "border-radius:10px;padding:5px;outline:0;}"
            "QListWidget::item{padding:9px 7px;border-radius:7px;}"
            "QListWidget::item:selected{background:#235a7c;color:white;}"
        )
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        sidebar = QWidget()
        sidebar.setMinimumWidth(205)
        sidebar.setMaximumWidth(280)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 5, 0)
        sidebar_title = QLabel("Conversaciones")
        sidebar_title.setStyleSheet("font-size:16px;font-weight:600;color:#91e8ff;")
        self.new_conversation_button = QPushButton("+ Nueva")
        self.rename_conversation_button = QPushButton("Renombrar")
        self.delete_conversation_button = QPushButton("Eliminar")
        self.delete_conversation_button.setStyleSheet("background:#713849;")
        self.conversation_list = QListWidget()
        conversation_actions = QHBoxLayout()
        conversation_actions.addWidget(self.rename_conversation_button)
        conversation_actions.addWidget(self.delete_conversation_button)
        sidebar_layout.addWidget(sidebar_title)
        sidebar_layout.addWidget(self.new_conversation_button)
        sidebar_layout.addWidget(self.conversation_list, 1)
        sidebar_layout.addLayout(conversation_actions)
        splitter.addWidget(sidebar)

        chat_panel = QWidget()
        layout = QVBoxLayout(chat_panel)
        layout.setContentsMargins(5, 0, 0, 0)
        self.conversation_title = QLabel("Conversación")
        self.conversation_title.setTextFormat(Qt.TextFormat.PlainText)
        self.conversation_title.setStyleSheet(
            "font-size:16px;font-weight:600;color:#dff7ff;"
        )
        self.power_button = QPushButton()
        self.power_button.setToolTip(
            "Carga Qwen3.6 27B en la GPU de 16 GB o vuelve al perfil normal."
        )
        self.gpu_button = QPushButton("GPU")
        self.gpu_button.setToolTip(
            "Abre el gestor de las dos GPU y del servidor Ollama de 8 GB."
        )
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.load_older_button = QPushButton("Cargar mensajes anteriores")
        self.load_older_button.hide()
        self.transcript = SafeMarkdownBrowser()
        self.transcript.setOpenLinks(False)
        self.transcript.setOpenExternalLinks(False)
        self.transcript.anchorClicked.connect(self._open_markdown_link)
        self.transcript.document().setDefaultStyleSheet(
            "a{color:#91e8ff;text-decoration:underline;}"
            "code,pre{background-color:#102f45;color:#edfaff;}"
            "blockquote{color:#c8eaf5;border-left:3px solid #4b88a7;"
            "margin-left:8px;padding-left:10px;}"
            "table{border-collapse:collapse;margin:6px 0;}"
            "th,td{border:1px solid #3b657d;padding:4px 7px;}"
        )
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe un mensaje u orden…")
        self.send_button = QPushButton("Enviar")
        self.attach_button = QPushButton("Adjuntar…")
        self.clear_attachments_button = QPushButton("Quitar adjuntos")
        self.clear_attachments_button.hide()
        self.attachment_label = QLabel()
        self.attachment_label.setTextFormat(Qt.TextFormat.PlainText)
        self.attachment_label.setWordWrap(True)
        self.confirm_button = QPushButton("Autorizar acción…")
        self.confirm_button.setStyleSheet("background:#9b4052;")
        self.confirm_button.hide()
        buttons = QHBoxLayout()
        buttons.addWidget(self.input, 1)
        buttons.addWidget(self.send_button)
        attachment_buttons = QHBoxLayout()
        attachment_buttons.addWidget(self.attach_button)
        attachment_buttons.addWidget(self.clear_attachments_button)
        attachment_buttons.addStretch(1)
        title_row = QHBoxLayout()
        title_row.addWidget(self.conversation_title, 1)
        title_row.addWidget(self.gpu_button)
        title_row.addWidget(self.power_button)
        layout.addLayout(title_row)
        layout.addWidget(self.status)
        layout.addWidget(self.load_older_button)
        layout.addWidget(self.transcript, 1)
        layout.addWidget(self.attachment_label)
        layout.addLayout(attachment_buttons)
        layout.addLayout(buttons)
        layout.addWidget(self.confirm_button)
        splitter.addWidget(chat_panel)
        splitter.setSizes([220, 560])

        self.new_conversation_button.clicked.connect(self.new_conversation)
        self.rename_conversation_button.clicked.connect(
            self.rename_current_conversation
        )
        self.delete_conversation_button.clicked.connect(
            self.delete_current_conversation
        )
        self.conversation_list.currentItemChanged.connect(
            self._on_conversation_item_changed
        )
        self.load_older_button.clicked.connect(self.load_older_messages)
        self.send_button.clicked.connect(self.send)
        self.attach_button.clicked.connect(self.choose_attachments)
        self.clear_attachments_button.clicked.connect(self.clear_attachments)
        self.input.returnPressed.connect(self.send)
        self.confirm_button.clicked.connect(self.authorize_pending)
        self.power_button.clicked.connect(self.toggle_power_mode)
        self.gpu_button.clicked.connect(self.show_gpu_manager)
        self.bridge.chat_ready.connect(self.on_reply)
        self.bridge.chat_error.connect(self.on_error)
        self.bridge.authorization_ready.connect(self.on_authorization_result)
        self.bridge.authorization_error.connect(self.on_authorization_error)
        model_mode_ready = getattr(self.bridge, "model_mode_ready", None)
        model_mode_error = getattr(self.bridge, "model_mode_error", None)
        if model_mode_ready is not None:
            model_mode_ready.connect(self.on_model_mode_ready)
        if model_mode_error is not None:
            model_mode_error.connect(self.on_model_mode_error)
        self.gpu_manager = GpuManagerDialog(service, bridge, self)
        self.refresh_conversations()
        self.refresh_state()
        self.refresh_power_button()

    def refresh_state(self) -> None:
        value = self.service.state_dict()
        model_label = self.model_labels.get(self.current_conversation_id or "", "")
        model = f"  ·  {model_label}" if model_label else ""
        self.status.setText(
            f"{self.service.config.name} ♂  ·  {value['mood'].capitalize()}  ·  "
            f"hambre {value['hunger']:.0f}  ·  "
            f"energía {value['energy']:.0f}  ·  felicidad {value['happiness']:.0f}{model}"
        )

    def refresh_power_button(self) -> None:
        power = (
            getattr(getattr(self.service, "ollama", None), "requested_mode", "normal")
            in {"power", "dual"}
        )
        self.power_button.setEnabled(True)
        self.power_button.setText(
            "❄ Volver a Normal" if power else "⚡ Activar Potencia"
        )
        self.power_button.setStyleSheet(
            "background:#36536b;" if power else "background:#8a4ec2;font-weight:600;"
        )

    def toggle_power_mode(self) -> None:
        target = (
            "normal"
            if getattr(
                getattr(self.service, "ollama", None),
                "requested_mode",
                "normal",
            )
            in {"power", "dual"}
            else "power"
        )
        self.power_button.setEnabled(False)
        self.power_button.setText(
            "Volviendo a Normal…" if target == "normal" else "Cargando Qwen3.6…"
        )
        setter = getattr(self.bridge, "set_model_mode", None)
        if setter is None:
            self.on_model_mode_error("El selector de modelos no está disponible.")
            return
        setter(target)

    def on_model_mode_ready(self, status: Any) -> None:
        self.refresh_power_button()
        self.refresh_state()

    def on_model_mode_error(self, message: str) -> None:
        self.refresh_power_button()
        QMessageBox.warning(self, "Modelo de Arfoxia", message)

    def show_gpu_manager(self) -> None:
        self.gpu_manager.show()
        self.gpu_manager.raise_()
        self.gpu_manager.activateWindow()

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            result = to_dict()
            if isinstance(result, dict):
                return dict(result)
        return {}

    @classmethod
    def _conversation_from_payload(cls, value: Any) -> dict[str, Any]:
        payload = cls._as_dict(value)
        nested = payload.get("conversation")
        if isinstance(nested, dict):
            return dict(nested)
        return payload

    @staticmethod
    def _conversation_identifier(conversation: dict[str, Any]) -> str:
        return str(
            conversation.get("id")
            or conversation.get("conversation_id")
            or ""
        )

    @staticmethod
    def _conversation_name(conversation: dict[str, Any]) -> str:
        return str(conversation.get("title") or "Nueva conversación").strip()[
            :120
        ] or "Nueva conversación"

    def _service_conversations(self) -> list[dict[str, Any]]:
        list_conversations = getattr(self.service, "list_conversations", None)
        if not callable(list_conversations):
            return [
                {
                    "id": self.LEGACY_CONVERSATION_ID,
                    "title": "Conversación",
                }
            ]
        value = list_conversations()
        if isinstance(value, dict):
            candidates = value.get("conversations", value.get("items", []))
            if isinstance(candidates, dict):
                candidates = candidates.get(
                    "conversations", candidates.get("items", [])
                )
        else:
            candidates = value
        if not isinstance(candidates, (list, tuple)):
            return []
        conversations: list[dict[str, Any]] = []
        for candidate in candidates:
            conversation = self._conversation_from_payload(candidate)
            if self._conversation_identifier(conversation):
                conversations.append(conversation)
        return conversations

    def _service_messages(
        self,
        conversation_id: str,
        *,
        before_id: Any = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        conversation_messages = getattr(
            self.service, "conversation_messages", None
        )
        if not callable(conversation_messages):
            if conversation_id != self.LEGACY_CONVERSATION_ID:
                return [], False
            return (
                [
                    dict(item)
                    for item in self.service.database.recent_messages(
                        self.MESSAGE_PAGE_SIZE
                    )
                ],
                False,
            )
        value = conversation_messages(
            conversation_id,
            limit=self.MESSAGE_PAGE_SIZE,
            before_id=before_id,
        )
        if isinstance(value, dict):
            candidates = value.get("messages", value.get("items", []))
            has_more = bool(
                value.get(
                    "has_more",
                    value.get("more", value.get("next_cursor")),
                )
            )
        else:
            candidates = value
            has_more = False
        if not isinstance(candidates, (list, tuple)):
            return [], False
        messages = [
            self._as_dict(candidate)
            for candidate in candidates
            if self._as_dict(candidate)
        ]
        if not isinstance(value, dict):
            has_more = len(messages) >= self.MESSAGE_PAGE_SIZE
        return messages, has_more

    def refresh_conversations(
        self,
        *,
        select_id: str | None = None,
        reload_current: bool = False,
    ) -> None:
        conversations = self._service_conversations()

        preferred = select_id or self.current_conversation_id
        self._switching_conversation = True
        try:
            blocker = QSignalBlocker(self.conversation_list)
            self.conversation_list.clear()
            self._conversation_items.clear()
            selected_item: QListWidgetItem | None = None
            for conversation in conversations:
                conversation_id = self._conversation_identifier(conversation)
                item = QListWidgetItem(self._conversation_name(conversation))
                item.setData(Qt.ItemDataRole.UserRole, conversation_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, conversation)
                preview = str(
                    conversation.get("last_message_preview")
                    or conversation.get("preview")
                    or ""
                ).strip()
                if preview:
                    item.setToolTip(preview[:300])
                self.conversation_list.addItem(item)
                self._conversation_items[conversation_id] = item
                if conversation_id == preferred:
                    selected_item = item
            if selected_item is None and self.conversation_list.count():
                selected_item = self.conversation_list.item(0)
            self.conversation_list.setCurrentItem(selected_item)
            del blocker
        finally:
            self._switching_conversation = False

        selected_id = (
            str(selected_item.data(Qt.ItemDataRole.UserRole))
            if selected_item is not None
            else None
        )
        if selected_id != self.current_conversation_id:
            self._activate_conversation(selected_id)
        elif selected_id:
            conversation = self._as_dict(
                selected_item.data(Qt.ItemDataRole.UserRole + 1)
            )
            self._update_conversation_heading(conversation)
            if reload_current:
                self.load_conversation_messages()
        else:
            self.current_conversation_id = None
            self._loaded_messages = []
            self._render_no_conversation_hint()
            self._update_conversation_heading({})
            self._update_composer_state()

    def _on_conversation_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if self._switching_conversation:
            return
        conversation_id = (
            str(current.data(Qt.ItemDataRole.UserRole)) if current else None
        )
        self._activate_conversation(conversation_id)

    def _activate_conversation(self, conversation_id: str | None) -> None:
        if conversation_id == self.current_conversation_id:
            return
        self._save_current_draft()
        self.current_conversation_id = conversation_id
        item = (
            self._conversation_items.get(conversation_id)
            if conversation_id
            else None
        )
        conversation = (
            self._as_dict(item.data(Qt.ItemDataRole.UserRole + 1))
            if item is not None
            else {}
        )
        self._update_conversation_heading(conversation)
        self._restore_current_draft()
        self.load_conversation_messages()
        self.refresh_state()
        self._update_composer_state()

    def _update_conversation_heading(
        self, conversation: dict[str, Any]
    ) -> None:
        title = (
            self._conversation_name(conversation)
            if self.current_conversation_id
            else "Sin conversaciones"
        )
        self.conversation_title.setTextFormat(Qt.TextFormat.PlainText)
        self.conversation_title.setText(title)
        self.setWindowTitle(f"Hablar con {self.service.config.name} · {title}")
        enabled = self.current_conversation_id is not None
        self.rename_conversation_button.setEnabled(enabled)
        self.delete_conversation_button.setEnabled(enabled)

    def _save_current_draft(self) -> None:
        if not self.current_conversation_id:
            return
        if (
            self.pending_authorization is not None
            and self.current_conversation_id
            == self._authorization_draft_conversation_id
            and not self.input.isEnabled()
        ):
            return
        text = self.input.text()
        attachments = list(self.pending_attachments)
        if text or attachments:
            self._drafts[self.current_conversation_id] = {
                "text": text,
                "attachments": attachments,
            }
        else:
            self._drafts.pop(self.current_conversation_id, None)

    def _restore_current_draft(self) -> None:
        draft = self._drafts.get(self.current_conversation_id or "", {})
        self.input.setText(str(draft.get("text") or ""))
        attachments = draft.get("attachments", [])
        self.pending_attachments = (
            [dict(item) for item in attachments if isinstance(item, dict)]
            if isinstance(attachments, list)
            else []
        )
        self._refresh_attachments()

    def ensure_conversation(self) -> str | None:
        """Return the explicit desktop selection without creating or selecting one."""

        return self.current_conversation_id

    def _render_no_conversation_hint(self) -> None:
        self.transcript.setPlainText(
            "No hay ninguna conversación seleccionada.\n\n"
            "Pulsa «+ Nueva» para crear un chat antes de escribir a Arfoxia."
        )

    def _notify_no_conversation(self) -> None:
        self._render_no_conversation_hint()
        self.status.setText(
            "El mensaje no se ha enviado. Pulsa «+ Nueva» para crear un chat."
        )
        self._update_composer_state()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def new_conversation(
        self,
        checked: bool = False,
        *,
        title: str | None = None,
    ) -> None:
        del checked
        create_conversation = getattr(self.service, "create_conversation", None)
        if not callable(create_conversation):
            return
        try:
            created = self._conversation_from_payload(
                create_conversation(title=title)
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "Nueva conversación", str(exc)
            )
            return
        conversation_id = self._conversation_identifier(created)
        self.refresh_conversations(
            select_id=conversation_id or None,
            reload_current=True,
        )
        self.input.setFocus()

    def rename_current_conversation(
        self,
        checked: bool = False,
        *,
        title: str | None = None,
    ) -> None:
        del checked
        conversation_id = self.current_conversation_id
        item = self._conversation_items.get(conversation_id or "")
        if not conversation_id or item is None:
            return
        current_title = item.text()
        if title is None:
            title, accepted = QInputDialog.getText(
                self,
                "Renombrar conversación",
                "Nuevo nombre:",
                text=current_title,
            )
            if not accepted:
                return
        title = str(title).strip()
        if not title or title == current_title:
            return
        rename_conversation = getattr(
            self.service, "rename_conversation", None
        )
        if not callable(rename_conversation):
            return
        try:
            rename_conversation(conversation_id, title)
        except Exception as exc:
            QMessageBox.warning(
                self, "Renombrar conversación", str(exc)
            )
            return
        self.refresh_conversations(select_id=conversation_id)

    def _conversation_has_pending_authorization(
        self, conversation_id: str
    ) -> bool:
        pending = [self.pending_authorization, *self.authorization_queue]
        return any(
            item is not None
            and str(item.get("conversation_id") or "") == conversation_id
            for item in pending
        )

    def delete_current_conversation(self, checked: bool = False) -> None:
        del checked
        conversation_id = self.current_conversation_id
        if not conversation_id:
            return
        if conversation_id in self.pending_requests.values():
            QMessageBox.information(
                self,
                "Conversación en uso",
                "Espera a que Arfoxia termine de responder antes de eliminarla.",
            )
            return
        if self._conversation_has_pending_authorization(conversation_id):
            QMessageBox.information(
                self,
                "Acción pendiente",
                "Resuelve o cancela la autorización pendiente antes de eliminar esta conversación.",
            )
            return
        item = self._conversation_items.get(conversation_id)
        title = item.text() if item is not None else "esta conversación"
        answer = QMessageBox.question(
            self,
            "Eliminar conversación",
            (
                f"¿Eliminar «{title}» en el PC y el móvil?\n\n"
                "Su historial dejará de estar disponible."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_conversation = getattr(
            self.service, "delete_conversation", None
        )
        if not callable(delete_conversation):
            return
        try:
            deleted = delete_conversation(conversation_id)
        except Exception as exc:
            QMessageBox.warning(
                self, "Eliminar conversación", str(exc)
            )
            return
        self._discard_draft(conversation_id)
        deleted_payload = self._as_dict(deleted)
        replacement = self._conversation_from_payload(
            deleted_payload.get("replacement", deleted_payload)
        )
        replacement_id = self._conversation_identifier(replacement)
        if replacement_id == conversation_id:
            replacement_id = ""
        self.current_conversation_id = None
        self.refresh_conversations(
            select_id=replacement_id or None,
            reload_current=True,
        )

    def _discard_draft(self, conversation_id: str) -> None:
        draft = self._drafts.pop(conversation_id, {})
        attachments = list(draft.get("attachments", []))
        if conversation_id == self.current_conversation_id:
            attachments.extend(self.pending_attachments)
        identifiers = [
            str(item.get("attachment_id") or "")
            for item in attachments
            if isinstance(item, dict)
        ]
        if identifiers:
            self.service.attachments.discard(identifiers)
        if conversation_id == self.current_conversation_id:
            self.pending_attachments.clear()
            self.input.clear()
            self._refresh_attachments()

    @staticmethod
    def _message_key(message: dict[str, Any]) -> str:
        identifier = message.get("id", message.get("message_id"))
        if identifier is not None:
            return f"id:{identifier}"
        return "|".join(
            (
                str(message.get("role") or ""),
                str(message.get("created_at") or ""),
                str(message.get("content") or message.get("text") or ""),
            )
        )

    def load_conversation_messages(self) -> None:
        conversation_id = self.current_conversation_id
        if not conversation_id:
            self._loaded_messages = []
            self._oldest_message_id = None
            self.load_older_button.hide()
            self.transcript.clear()
            return
        messages, has_more = self._service_messages(conversation_id)
        self._loaded_messages = messages
        self._oldest_message_id = (
            messages[0].get("id", messages[0].get("message_id"))
            if messages
            else None
        )
        self.load_older_button.setVisible(has_more)
        self._render_loaded_messages(scroll_to_bottom=True)

    def load_older_messages(self, checked: bool = False) -> None:
        del checked
        if not self.current_conversation_id or self._oldest_message_id is None:
            self.load_older_button.hide()
            return
        messages, has_more = self._service_messages(
            self.current_conversation_id,
            before_id=self._oldest_message_id,
        )
        existing = {
            self._message_key(message) for message in self._loaded_messages
        }
        older = [
            message
            for message in messages
            if self._message_key(message) not in existing
        ]
        self._loaded_messages = [*older, *self._loaded_messages]
        if self._loaded_messages:
            first = self._loaded_messages[0]
            self._oldest_message_id = first.get(
                "id", first.get("message_id")
            )
        self.load_older_button.setVisible(has_more)
        self._render_loaded_messages(scroll_to_bottom=False)

    def _render_loaded_messages(self, *, scroll_to_bottom: bool) -> None:
        self.transcript.clear()
        for message in self._loaded_messages:
            role = str(message.get("role") or "").casefold()
            who = {
                "assistant": self.service.config.name,
                "user": self.service.config.owner_name,
                "system": "Sistema",
                "tool": "Herramienta",
            }.get(role, role.capitalize() or "Mensaje")
            content = str(
                message.get("content")
                or message.get("text")
                or message.get("display_text")
                or ""
            )
            raw_attachments = message.get("attachments", [])
            if isinstance(raw_attachments, list):
                attachment_names = [
                    str(
                        attachment.get("name")
                        or attachment.get("original_name")
                        or attachment.get("filename")
                        or ""
                    ).strip()
                    for attachment in raw_attachments
                    if isinstance(attachment, dict)
                ]
                attachment_names = [
                    name for name in attachment_names if name
                ]
                if attachment_names:
                    attachment_line = "📎 " + " · ".join(
                        escape_markdown_text(name)
                        for name in attachment_names
                    )
                    content = (
                        f"{content}\n{attachment_line}"
                        if content
                        else attachment_line
                    )
            if content:
                self.append(who, content)
        scrollbar = self.transcript.verticalScrollBar()
        if scroll_to_bottom:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(scrollbar.minimum())

    def handle_service_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type not in {
            "chat_received",
            "speech",
            "conversation_changed",
            "conversation_created",
            "conversation_renamed",
            "conversation_deleted",
        }:
            return
        conversation_id = str(event.get("conversation_id") or "")
        if not conversation_id:
            return
        if (
            event_type == "conversation_deleted"
            or (
                event_type == "conversation_changed"
                and str(event.get("action") or "") == "deleted"
            )
        ):
            self._discard_draft(conversation_id)
        current_id = self.current_conversation_id
        self.refresh_conversations(
            select_id=current_id,
            reload_current=conversation_id == current_id,
        )

    def _update_composer_state(self) -> None:
        conversation_id = self.current_conversation_id
        awaiting_reply = bool(
            conversation_id
            and conversation_id in self.pending_requests.values()
        )
        blocked = (
            not conversation_id
            or awaiting_reply
            or self.pending_authorization is not None
        )
        self.input.setEnabled(not blocked)
        self.send_button.setEnabled(not blocked)
        self.attach_button.setEnabled(not blocked)
        self.input.setPlaceholderText(
            "Escribe un mensaje u orden…"
            if conversation_id
            else "Pulsa «+ Nueva» para crear una conversación"
        )

    def _open_markdown_link(self, url: QUrl) -> None:
        if is_safe_https_url(url):
            QDesktopServices.openUrl(url)

    def _style_markdown_links(self, start: int, end: int) -> None:
        document = self.transcript.document()
        block = document.findBlock(start)
        link_ranges: list[tuple[int, int, QTextCharFormat]] = []
        while block.isValid() and block.position() <= end:
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                fragment_start = fragment.position()
                fragment_end = fragment_start + fragment.length()
                char_format = fragment.charFormat()
                if (
                    fragment.isValid()
                    and fragment_end > start
                    and fragment_start < end
                    and char_format.isAnchor()
                ):
                    link_ranges.append(
                        (fragment_start, fragment.length(), char_format)
                    )
                iterator += 1
            block = block.next()
        for position, length, char_format in link_ranges:
            selection = QTextCursor(document)
            selection.setPosition(position)
            selection.setPosition(
                position + length,
                QTextCursor.MoveMode.KeepAnchor,
            )
            safe_format = QTextCharFormat(char_format)
            if is_safe_https_url(char_format.anchorHref()):
                # Qt's Markdown importer ignores the HTML anchor stylesheet.
                safe_format.setForeground(QColor("#91e8ff"))
                safe_format.setFontUnderline(True)
            else:
                safe_format.setAnchor(False)
                safe_format.setAnchorHref("")
                safe_format.setAnchorNames([])
                safe_format.setForeground(QColor("#edfaff"))
                safe_format.setFontUnderline(False)
            selection.setCharFormat(safe_format)

    def append(self, who: str, text: str) -> None:
        color = "#91e8ff" if who == self.service.config.name else "#b8c8d5"
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.transcript.document().isEmpty():
            cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        cursor.setBlockFormat(QTextBlockFormat())
        cursor.setCharFormat(QTextCharFormat())

        speaker_format = QTextCharFormat()
        speaker_format.setForeground(QColor(color))
        speaker_format.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(who, speaker_format)
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        cursor.setCharFormat(QTextCharFormat())

        markdown_start = cursor.position()
        cursor.insertMarkdown(text, SAFE_MARKDOWN_FEATURES)
        markdown_end = cursor.position()
        self._style_markdown_links(markdown_start, markdown_end)
        # insertMarkdown may leave the cursor in the last table cell/list/code
        # block. Exit the fragment before creating the next message boundary.
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    def send(self) -> None:
        text = self.input.text().strip()
        if not text and not self.pending_attachments:
            return
        if not self.current_conversation_id:
            self._notify_no_conversation()
            return
        attachments = list(self.pending_attachments)
        attachment_ids = [
            str(item["attachment_id"]) for item in attachments
        ]
        names = ", ".join(
            escape_markdown_text(str(item["name"]))
            for item in attachments
        )
        self.input.clear()
        self.pending_attachments.clear()
        self._refresh_attachments()
        shown = text or "Analiza estos archivos adjuntos."
        if names:
            shown = f"{shown}\n📎 {names}"
        self._submit_message(text, attachment_ids, shown)

    def submit_quick_message(self, text: str) -> str | None:
        value = text.strip()
        if not value:
            return None
        return self._submit_message(value, [], value)

    def _submit_message(
        self,
        text: str,
        attachment_ids: list[str],
        shown: str,
    ) -> str | None:
        conversation_id = self.ensure_conversation()
        if not conversation_id:
            self._notify_no_conversation()
            return None
        self._drafts.pop(conversation_id, None)
        self.append(self.service.config.owner_name, shown)
        request_id = self.bridge.chat(
            text,
            attachment_ids,
            conversation_id=conversation_id,
        )
        self.pending_requests[request_id] = conversation_id
        self._update_composer_state()
        return request_id

    def choose_attachments(self) -> None:
        remaining = 4 - len(self.pending_attachments)
        if remaining <= 0:
            QMessageBox.information(
                self,
                "Adjuntos de Arfoxia",
                "Puedes enviar como máximo 4 adjuntos por mensaje.",
            )
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Elige archivos para Arfoxia",
            "",
            (
                "Archivos compatibles (*.png *.jpg *.jpeg *.webp *.pdf *.txt *.md "
                "*.csv *.json *.jsonl *.py *.js *.ts *.tsx *.html *.css *.xml "
                "*.yaml *.yml *.toml *.ini *.cfg *.log *.sql *.ps1 *.bat);;"
                "Todos los archivos (*)"
            ),
        )
        for raw_path in paths[:remaining]:
            try:
                info = self.service.add_attachment_path(Path(raw_path))
            except Exception as exc:
                QMessageBox.warning(self, "Adjunto no válido", str(exc))
                continue
            self.pending_attachments.append(info.to_dict())
        self._refresh_attachments()

    def clear_attachments(self) -> None:
        identifiers = [
            str(item.get("attachment_id") or "")
            for item in self.pending_attachments
        ]
        self.service.attachments.discard(identifiers)
        self.pending_attachments.clear()
        self._refresh_attachments()

    def _refresh_attachments(self) -> None:
        if not self.pending_attachments:
            self.attachment_label.clear()
            self.clear_attachments_button.hide()
            return
        names = " · ".join(str(item["name"]) for item in self.pending_attachments)
        self.attachment_label.setText(f"📎 {names}")
        self.clear_attachments_button.show()

    def _finish_request(
        self,
        request_id: str,
        conversation_id: str | None,
    ) -> None:
        if request_id:
            self.pending_requests.pop(request_id, None)
            return
        if conversation_id:
            for candidate, candidate_conversation in list(
                self.pending_requests.items()
            ):
                if candidate_conversation == conversation_id:
                    self.pending_requests.pop(candidate, None)
                    return

    def on_reply(self, payload: dict[str, Any]) -> None:
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("result"), dict)
            and (
                "request_id" in payload
                or "conversation_id" in payload
            )
        ):
            request_id = str(payload.get("request_id") or "")
            conversation_id = str(payload.get("conversation_id") or "") or None
            result = dict(payload["result"])
        else:
            request_id = ""
            conversation_id = self.current_conversation_id
            result = dict(payload)
        self._finish_request(request_id, conversation_id)
        message = str(result.get("message", "¡Gla! Estoy aquí."))
        mode = str(result.get("model_mode") or "")
        model = str(result.get("model") or "")
        if (
            conversation_id
            and mode in {"small", "large", "power", "gaming_gpu", "dual"}
            and model
        ):
            label = (
                "modelo Dual" if mode == "dual" else "modelo Potencia"
                if mode == "power"
                else "modelo en GPU de 8 GB"
                if mode == "gaming_gpu"
                else "modelo grande"
                if mode == "large"
                else "modelo ligero"
            )
            self.model_labels[conversation_id] = f"{label}: {model}"
        if conversation_id == self.current_conversation_id:
            if callable(
                getattr(self.service, "conversation_messages", None)
            ):
                self.refresh_conversations(
                    select_id=conversation_id,
                    reload_current=True,
                )
            else:
                self.append(self.service.config.name, message)
        else:
            self.refresh_conversations(select_id=self.current_conversation_id)
        if (
            conversation_id == self.current_conversation_id
            and not is_short_dialogue(
                message, self.service.config.bubble_max_chars
            )
        ):
            self.show()
            self.raise_()
            self.activateWindow()
        if result.get("requires_authorization"):
            self.request_authorization(
                str(result.get("challenge_id") or ""),
                str(result.get("authorization_summary") or result.get("message") or ""),
                bool(result.get("password_configured", False)),
                auto_prompt=True,
                conversation_id=conversation_id,
            )
        self.refresh_state()
        self._update_composer_state()
        if (
            self.pending_authorization is None
            and self.input.isEnabled()
        ):
            self.input.setFocus()

    def on_error(self, payload: Any) -> None:
        if isinstance(payload, dict):
            request_id = str(payload.get("request_id") or "")
            conversation_id = str(payload.get("conversation_id") or "") or None
            message = str(payload.get("message") or "")
        else:
            request_id = ""
            conversation_id = self.current_conversation_id
            message = str(payload)
        self._finish_request(request_id, conversation_id)
        if conversation_id == self.current_conversation_id:
            self.append(
                self.service.config.name,
                f"Gla… no he podido responder: {message}",
            )
        self._update_composer_state()

    def request_authorization(
        self,
        challenge_id: str,
        summary: str,
        configured: bool,
        *,
        auto_prompt: bool = True,
        conversation_id: str | None = None,
    ) -> None:
        if not challenge_id:
            return
        identifiers = {
            str(item.get("challenge_id") or "") for item in self.authorization_queue
        }
        if self.pending_authorization is not None:
            identifiers.add(str(self.pending_authorization.get("challenge_id") or ""))
        if challenge_id in identifiers:
            return
        request = {
            "challenge_id": challenge_id,
            "summary": summary,
            "configured": configured,
            "auto_prompt": auto_prompt,
            "error": "",
            "conversation_id": conversation_id,
        }
        if self.pending_authorization is not None:
            self.authorization_queue.append(request)
            return
        self.pending_authorization = request
        self._show_pending_authorization()

    def _show_pending_authorization(self) -> None:
        if self.pending_authorization is None:
            return
        if self._authorization_draft_conversation_id is None:
            self._save_current_draft()
            self._authorization_draft_conversation_id = (
                self.current_conversation_id
            )
        self.confirm_button.show()
        self.confirm_button.setEnabled(True)
        self.confirm_button.setText("Autorizar acción…")
        self.input.clear()
        self.input.setPlaceholderText("No escribas la contraseña aquí; usa el diálogo privado.")
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.attach_button.setEnabled(False)
        self.show()
        self.raise_()
        self.activateWindow()
        if bool(self.pending_authorization.get("auto_prompt", True)):
            QTimer.singleShot(0, self.authorize_pending)

    def authorize_pending(self) -> None:
        if (
            not self.pending_authorization
            or self.authorization_dialog_open
            or self.authorization_in_flight
        ):
            return
        pending = dict(self.pending_authorization)
        challenge_id = str(pending["challenge_id"])
        self.authorization_dialog_open = True
        try:
            setup = not self.service.authorization.is_configured
            dialog = AuthorizationDialog(
                str(pending["summary"]),
                setup=setup,
                error=str(pending.get("error") or ""),
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.service.cancel_authorization(challenge_id)
                self._finish_pending_authorization()
                return
            password = dialog.take_password()
            try:
                if setup:
                    self.service.authorization.configure(password)
            except Exception as exc:
                password = ""
                if self.pending_authorization is not None:
                    self.pending_authorization["error"] = str(exc)
                self.confirm_button.setText("Reintentar autorización…")
                return
            self.authorization_in_flight = True
            self.confirm_button.setEnabled(False)
            self.confirm_button.setText("Ejecutando acción autorizada…")
            try:
                self.bridge.authorize(challenge_id, password)
            finally:
                password = ""
        finally:
            self.authorization_dialog_open = False

    def on_authorization_result(self, result: Any) -> None:
        self.authorization_in_flight = False
        self.confirm_button.setEnabled(True)
        conversation_id = (
            str(self.pending_authorization.get("conversation_id") or "")
            if self.pending_authorization is not None
            else ""
        ) or self.current_conversation_id
        if result.requires_authorization:
            if self.pending_authorization is not None:
                self.pending_authorization["error"] = result.message
            self.confirm_button.setText("Reintentar autorización…")
            if conversation_id == self.current_conversation_id:
                self.append(self.service.config.name, result.message)
            return
        if conversation_id == self.current_conversation_id:
            self.append(self.service.config.name, result.message)
        self.refresh_state()
        self._finish_pending_authorization()

    def on_authorization_error(self, message: str) -> None:
        self.authorization_in_flight = False
        self.confirm_button.setEnabled(True)
        conversation_id = (
            str(self.pending_authorization.get("conversation_id") or "")
            if self.pending_authorization is not None
            else ""
        ) or self.current_conversation_id
        if self.pending_authorization is not None:
            self.pending_authorization["error"] = (
                "No pude completar la autorización de forma segura."
            )
        self.confirm_button.setText("Reintentar autorización…")
        if conversation_id == self.current_conversation_id:
            self.append(
                self.service.config.name,
                "Gla… no pude completar esa acción de forma segura. Inténtalo de nuevo.",
            )

    def _finish_pending_authorization(self) -> None:
        self.pending_authorization = None
        self.authorization_in_flight = False
        if self.authorization_queue:
            self.pending_authorization = self.authorization_queue.popleft()
            self._show_pending_authorization()
            return
        self.confirm_button.hide()
        self.confirm_button.setEnabled(True)
        self.confirm_button.setText("Autorizar acción…")
        self.input.setPlaceholderText("Escribe un mensaje u orden…")
        draft_conversation_id = self._authorization_draft_conversation_id
        self._authorization_draft_conversation_id = None
        if draft_conversation_id == self.current_conversation_id:
            self._restore_current_draft()
        self._update_composer_state()
        if self.input.isEnabled():
            self.input.setFocus()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.refresh_conversations(
            select_id=self.current_conversation_id,
            reload_current=True,
        )

    def closeEvent(self, event: Any) -> None:
        self._save_current_draft()
        identifiers = {
            str(item.get("attachment_id") or "")
            for draft in self._drafts.values()
            for item in draft.get("attachments", [])
            if isinstance(item, dict)
        }
        if identifiers:
            self.service.attachments.discard(list(identifiers))
        self._drafts.clear()
        self.pending_attachments.clear()
        self._refresh_attachments()
        super().closeEvent(event)


class PairingDialog(QDialog):
    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.setWindowTitle("Emparejar iPhone")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        label = QLabel("Escanea este QR desde el iPhone conectado a la misma red privada.")
        label.setWordWrap(True)
        qr = qrcode.make(url).convert("RGBA")
        qr_label = QLabel()
        qr_label.setPixmap(image_to_pixmap(qr, 1).scaled(280, 280))
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_label = QLineEdit(url)
        url_label.setReadOnly(True)
        copy_button = QPushButton("Copiar enlace")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(url))
        layout.addWidget(label)
        layout.addWidget(qr_label)
        layout.addWidget(url_label)
        layout.addWidget(copy_button)
        self.resize(430, 410)


class GpuManagerDialog(QDialog):
    """Local, typed controls for Arfoxia's two isolated Ollama GPU profiles."""

    REFRESH_INTERVAL_MS = 3_000

    def __init__(
        self,
        service: CompanionService,
        bridge: Bridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.bridge = bridge
        self.last_status: dict[str, Any] = {}
        self.busy = False
        self.refresh_pending = False
        self.setWindowTitle("Gestor de GPU de Arfoxia")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(690, 620)
        self.setStyleSheet(
            "QDialog{background:#081b2b;color:#edfaff;}"
            "QTextBrowser{background:#061522;color:#edfaff;border:1px solid #285570;"
            "border-radius:12px;padding:12px;}"
            "QPushButton{background:#235a7c;color:white;border:0;border-radius:10px;"
            "padding:10px 13px;font-weight:600;}"
            "QLabel{color:#9edff5;}"
        )

        layout = QVBoxLayout(self)
        title = QLabel("Control completo de las GPU")
        title.setStyleSheet("font-size:20px;font-weight:700;color:#dff8ff;")
        subtitle = QLabel(
            "Cada servidor usa sus GPU por UUID. El modo Ligero libera la GPU al jugar; "
            "Dual solo avisa cada 20 s y debes descargarlo manualmente."
        )
        subtitle.setWordWrap(True)
        self.state_label = QLabel("Consultando las GPU…")
        self.state_label.setWordWrap(True)
        self.telemetry = QTextBrowser()
        self.telemetry.setOpenLinks(False)
        self.telemetry.setOpenExternalLinks(False)

        first_row = QHBoxLayout()
        self.gaming_button = QPushButton("🎮 Usar modelo pequeño en GPU 8 GB")
        self.normal_button = QPushButton("❄ Perfil normal · GPU 16 GB")
        first_row.addWidget(self.gaming_button, 1)
        first_row.addWidget(self.normal_button, 1)

        second_row = QHBoxLayout()
        self.power_button = QPushButton("⚡ Potencia · GPU 16 GB")
        self.dual_button = QPushButton("✦ Dual · Qwen3.8 Extra High · 16 + 5,5 GB")
        self.unload_button = QPushButton("Liberar toda la VRAM")
        self.refresh_button = QPushButton("Actualizar")
        second_row.addWidget(self.power_button, 1)
        second_row.addWidget(self.unload_button)
        second_row.addWidget(self.refresh_button)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.state_label)
        layout.addWidget(self.telemetry, 1)
        layout.addLayout(first_row)
        layout.addLayout(second_row)
        layout.addWidget(self.dual_button)

        self.gaming_button.clicked.connect(
            lambda: self._set_mode("gaming_gpu")
        )
        self.normal_button.clicked.connect(lambda: self._set_mode("normal"))
        self.power_button.clicked.connect(lambda: self._set_mode("power"))
        self.dual_button.clicked.connect(lambda: self._set_mode("dual"))
        self.unload_button.clicked.connect(self._unload_models)
        self.refresh_button.clicked.connect(self.refresh)

        status_ready = getattr(bridge, "model_status_ready", None)
        status_error = getattr(bridge, "model_status_error", None)
        mode_ready = getattr(bridge, "model_mode_ready", None)
        mode_error = getattr(bridge, "model_mode_error", None)
        unload_ready = getattr(bridge, "model_unload_ready", None)
        unload_error = getattr(bridge, "model_unload_error", None)
        if status_ready is not None:
            status_ready.connect(self._on_status)
        if status_error is not None:
            status_error.connect(self._on_status_error)
        if mode_ready is not None:
            mode_ready.connect(self._on_mode_ready)
        if mode_error is not None:
            mode_error.connect(self._on_action_error)
        if unload_ready is not None:
            unload_ready.connect(self._on_unloaded)
        if unload_error is not None:
            unload_error.connect(self._on_action_error)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self.refresh_timer.timeout.connect(self.refresh)
        self._update_controls()

    @staticmethod
    def _number(value: Any, digits: int = 1) -> str:
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return "—"

    @classmethod
    def status_html(cls, status: dict[str, Any]) -> str:
        mode = str(status.get("requested_mode") or "normal")
        mode_labels = {
            "normal": "Normal · GPU de IA",
            "power": "Potencia · GPU de IA",
            "dual": "Dual · Qwen3.8 Extra High · ambas GPU",
            "gaming_gpu": "Modelo pequeño · GPU de juego",
        }
        model = html.escape(str(status.get("model") or "Sin modelo seleccionado"))
        loaded = status.get("dual_loaded_models") if mode == "dual" else status.get("loaded_models")
        loaded_count = len(loaded) if isinstance(loaded, list) else 0
        loaded_label = "Modelos activos en modo Dual" if mode == "dual" else "Modelos activos en GPU de IA"
        sections = [
            (
                "<div style='margin-bottom:12px'>"
                f"<b>Perfil:</b> {html.escape(mode_labels.get(mode, mode))}<br>"
                f"<b>Modelo seleccionado:</b> {model}<br>"
                f"<b>Permisos del PC:</b> {'Administrador' if status.get('pc_administrator') else 'Usuario'}<br>"
                f"<b>{loaded_label}:</b> {loaded_count}"
                "</div>"
            )
        ]
        if mode == "dual":
            sections.append("<div><b>Razonamiento:</b> Extra High · vigilancia cada 20 s · descarga manual</div>")
            if status.get("dual_warning"):
                sections.append(f"<div style='color:#ffc56b'>{html.escape(str(status['dual_warning']))}</div>")
        gpus = status.get("gpus")
        if not isinstance(gpus, list) or not gpus:
            sections.append(
                "<div><b>Telemetría no disponible.</b> Pulsa Actualizar.</div>"
            )
            return "".join(sections)

        role_labels = {
            "gaming": "GPU de juego · 8 GB",
            "ai": "GPU de IA · 16 GB",
            "unassigned": "GPU disponible",
        }
        for raw_gpu in sorted(
            (item for item in gpus if isinstance(item, dict)),
            key=lambda item: int(item.get("index", 999)),
        ):
            role = str(raw_gpu.get("role") or "unassigned")
            name = html.escape(str(raw_gpu.get("name") or "GPU NVIDIA"))
            uuid_value = html.escape(str(raw_gpu.get("uuid") or "—"))
            total = cls._number(
                raw_gpu.get("total_gb", raw_gpu.get("total_vram_gb"))
            )
            free = cls._number(
                raw_gpu.get("free_gb", raw_gpu.get("free_vram_gb"))
            )
            used_value = raw_gpu.get("used_gb", raw_gpu.get("used_vram_gb"))
            if used_value is None:
                try:
                    used_value = float(total) - float(free)
                except (TypeError, ValueError):
                    used_value = None
            used = cls._number(used_value)
            utilization = cls._number(raw_gpu.get("utilization_percent"), 0)
            temperature = cls._number(raw_gpu.get("temperature_c"), 0)
            gpu_model = raw_gpu.get("model")
            model_line = (
                f"<br><b>Modelo cargado:</b> {html.escape(str(gpu_model))}"
                if gpu_model
                else ""
            )
            sections.append(
                "<div style='background:#0d3048;border:1px solid #34708f;"
                "border-radius:10px;padding:10px;margin:8px 0'>"
                f"<b>{html.escape(role_labels.get(role, role))}</b> · índice "
                f"{html.escape(str(raw_gpu.get('index', '—')))}<br>"
                f"{name}<br><span style='color:#8fb8ca'>{uuid_value}</span><br>"
                f"<b>VRAM:</b> {used} usada · {free} libre · {total} GB total<br>"
                f"<b>Uso:</b> {utilization} % · <b>Temperatura:</b> {temperature} °C"
                f"{model_line}</div>"
            )

        gaming_loaded = status.get("gaming_gpu_loaded_models")
        if isinstance(gaming_loaded, list) and gaming_loaded:
            names = ", ".join(
                html.escape(str(item.get("name") or "modelo"))
                for item in gaming_loaded
                if isinstance(item, dict)
            )
            sections.append(
                f"<div><b>Servidor privado de 8 GB:</b> activo · {names}</div>"
            )
        elif (
            status.get("gaming_gpu_server_running") is True
            and status.get("gaming_gpu_server_owned") is False
        ):
            sections.append(
                "<div style='color:#ffc56b'><b>Puerto 11435 ocupado:</b> "
                "Arfoxia no tocará ese proceso porque no le pertenece.</div>"
            )
        return "".join(sections)

    def refresh(self) -> None:
        if self.busy or self.refresh_pending:
            return
        requester = getattr(self.bridge, "request_model_status", None)
        if requester is None:
            self._on_status_error("La telemetría de GPU no está disponible.")
            return
        self.refresh_pending = True
        self.state_label.setText("Actualizando telemetría…")
        self._update_controls()
        requester()

    def _set_mode(self, mode: str) -> None:
        if self.busy or self.refresh_pending:
            return
        game = self.last_status.get("game") or {}
        if mode in {"gaming_gpu", "dual"} and (
            bool(game.get("active"))
            or bool(game.get("error"))
            or self.last_status.get("gaming_gpu_blocked_by_game") is True
        ):
            QMessageBox.warning(
                self,
                "GPU de juego ocupada",
                "La GPU de 8 GB está en uso o no puedo verificarla. "
                "Arfoxia no cargará ningún modelo en ella.",
            )
            return
        setter = getattr(self.bridge, "set_model_mode", None)
        if setter is None:
            self._on_action_error("El selector de GPU no está disponible.")
            return
        self.busy = True
        labels = {
            "normal": "Volviendo al perfil normal…",
            "power": "Cargando Qwen3.6 en la GPU de 16 GB…",
            "dual": "Cargando Qwen3.8 en ambas GPU; comprobando VRAM…",
            "gaming_gpu": "Iniciando Ollama privado en la GPU de 8 GB…",
        }
        self.state_label.setText(labels.get(mode, "Cambiando perfil…"))
        self._update_controls()
        setter(mode)

    def _unload_models(self) -> None:
        if self.busy or self.refresh_pending:
            return
        unload = getattr(self.bridge, "unload_models", None)
        if unload is None:
            self._on_action_error("No se puede liberar la VRAM desde esta ventana.")
            return
        self.busy = True
        self.state_label.setText("Descargando los modelos de ambas GPU…")
        self._update_controls()
        unload()

    def _on_status(self, value: Any) -> None:
        self.refresh_pending = False
        self._apply_status(value)

    def _apply_status(self, value: Any) -> None:
        self.last_status = dict(value) if isinstance(value, dict) else {}
        self.telemetry.setHtml(self.status_html(self.last_status))
        mode = str(self.last_status.get("requested_mode") or "normal")
        if mode == "dual":
            self.state_label.setText(str(self.last_status.get("dual_warning") or
                "Dual Extra High activo. Avisos cada 20 s; libera la VRAM manualmente antes de jugar."))
        elif mode == "gaming_gpu":
            self.state_label.setText(
                "Modelo pequeño activo exclusivamente en la GPU de 8 GB."
            )
        elif mode == "power":
            self.state_label.setText(
                "Modo Potencia activo exclusivamente en la GPU de 16 GB."
            )
        else:
            self.state_label.setText(
                "Perfil normal activo en la GPU de 16 GB."
            )
        self._update_controls()

    def _on_mode_ready(self, value: Any) -> None:
        self.busy = False
        self._apply_status(value)

    def _on_unloaded(self) -> None:
        self.busy = False
        self.state_label.setText("VRAM liberada. El perfil se cargará al volver a hablar.")
        self._update_controls()
        self.refresh()

    def _on_status_error(self, message: str) -> None:
        self.refresh_pending = False
        self.state_label.setText(str(message))
        self._update_controls()

    def _on_action_error(self, message: str) -> None:
        self.busy = False
        self.state_label.setText(str(message))
        self._update_controls()
        if self.isVisible():
            QMessageBox.warning(self, "Gestor de GPU", str(message))

    def _update_controls(self) -> None:
        mode = str(self.last_status.get("requested_mode") or "normal")
        game = self.last_status.get("game") or {}
        game_active = (
            bool(game.get("active"))
            or bool(game.get("error"))
            or self.last_status.get("gaming_gpu_blocked_by_game") is True
        )
        gaming_installed = self.last_status.get("gaming_gpu_model_installed")
        power_installed = self.last_status.get("power_model_installed")
        gaming_server_conflict = (
            self.last_status.get("gaming_gpu_server_running") is True
            and self.last_status.get("gaming_gpu_server_owned") is False
        )
        controls_available = not self.busy and not self.refresh_pending
        self.gaming_button.setEnabled(
            controls_available
            and not game_active
            and not gaming_server_conflict
            and gaming_installed is not False
            and mode != "gaming_gpu"
        )
        self.normal_button.setEnabled(controls_available and mode != "normal")
        self.dual_button.setEnabled(controls_available and not game_active
            and self.last_status.get("dual_model_installed") is True and mode != "dual")
        self.dual_button.setText("✦ Dual activo · ambas GPU" if mode == "dual"
            else "✦ Dual · Qwen3.8 Extra High · 16 + 5,5 GB")
        self.power_button.setEnabled(
            controls_available
            and power_installed is not False
            and mode != "power"
        )
        self.unload_button.setEnabled(controls_available)
        self.refresh_button.setEnabled(controls_available)
        self.gaming_button.setText(
            "🎮 GPU 8 GB activa"
            if mode == "gaming_gpu"
            else "🎮 Usar modelo pequeño en GPU 8 GB"
        )
        self.normal_button.setText(
            "❄ Perfil normal activo"
            if mode == "normal"
            else "❄ Perfil normal · GPU 16 GB"
        )
        self.power_button.setText(
            "⚡ Potencia activa"
            if mode == "power"
            else "⚡ Potencia · GPU 16 GB"
        )

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.refresh_timer.start()
        self.refresh()

    def hideEvent(self, event: Any) -> None:
        self.refresh_timer.stop()
        super().hideEvent(event)


class PetWindow(QWidget):
    def __init__(self, service: CompanionService, token: str) -> None:
        super().__init__()
        self.service = service
        self.token = token
        variant = service.config.sprite_variant
        self.library = SpriteLibrary(PROJECT_ROOT / "assets" / "external" / "pmd" / variant)
        self.scale = service.config.sprite_scale
        self.frames: list[QPixmap] = []
        self.durations: tuple[int, ...] = ()
        self.frame_index = 0
        self.loop_animation = True
        self.current_animation = "Idle"
        self.direction = 0
        self.drag_origin: QPoint | None = None
        self.window_origin: QPoint | None = None
        self.pet_distance = 0
        self.pet_triggered = False
        self.wander_target: int | None = None
        self.movement_purpose = "idle"
        self.interaction_mode = "idle"
        self.feed_stage = 0
        self.fetch_home_x: int | None = None
        self.lemon_target_window_x = 0
        self.fetch_just_completed = False
        self.lemon_flight_start = QPoint()
        self.lemon_flight_end = QPoint()
        self.sleeping_on_bed = False
        self.eevee_presence = CodexPresence(False)
        self.eevee_missed_polls = 0

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if service.config.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 420)

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.next_frame)
        self.movement_timer = QTimer(self)
        self.movement_timer.setInterval(35)
        self.movement_timer.timeout.connect(self.move_step)
        self.behavior_timer = QTimer(self)
        self.behavior_timer.setInterval(26000)
        self.behavior_timer.timeout.connect(self.autonomous_behavior)
        self.event_timer = QTimer(self)
        self.event_timer.setInterval(120)
        self.event_timer.timeout.connect(self.poll_events)
        self.eevee_presence_timer = QTimer(self)
        self.eevee_presence_timer.setInterval(
            max(1_000, min(int(service.config.eevee_presence_poll_ms), 30_000))
        )
        self.eevee_presence_timer.timeout.connect(self.update_eevee_presence)
        self.eevee_interaction_timer = QTimer(self)
        self.eevee_interaction_timer.setSingleShot(True)
        self.eevee_interaction_timer.timeout.connect(self.interact_with_eevee)
        self.feed_timer = QTimer(self)
        self.feed_timer.setSingleShot(True)
        self.feed_timer.timeout.connect(self.advance_feed_sequence)
        self.lemon_flight = QVariantAnimation(self)
        self.lemon_flight.setStartValue(0.0)
        self.lemon_flight.setEndValue(1.0)
        self.lemon_flight.setDuration(760)
        self.lemon_flight.valueChanged.connect(self.move_lemon_in_flight)
        self.lemon_flight.finished.connect(self.start_lemon_chase)

        self.bridge = Bridge(service)
        self.chat_window = ChatWindow(service, self.bridge)
        self.speech_bubble = SpeechBubble(self)
        quick_chat_timeout = max(
            1_000,
            min(int(service.config.quick_chat_inactivity_ms), 300_000),
        )
        self.quick_chat = QuickChatPopup(
            service.config.name,
            self,
            inactivity_timeout_ms=quick_chat_timeout,
        )
        self.quick_chat.submitted.connect(self.send_quick_message)
        self.bridge.chat_error.connect(self.on_quick_chat_error)
        self.bridge.model_mode_ready.connect(self.on_model_mode_ready)
        self.bridge.model_mode_error.connect(self.on_quick_chat_error)
        self.cry_player = CryPlayer(service, self)
        self.berry_prop = DesktopPropWindow(
            PROP_DIR / "oran-berry.png", BERRY_SIZE, pixelated=True
        )
        self.lemon_prop = DesktopPropWindow(
            PROP_DIR / "lemon.png", LEMON_SIZE, pixelated=True
        )
        self.bed_prop = DesktopPropWindow(
            PROP_DIR / "bed.png", BED_SIZE, pixelated=True, draggable=True
        )
        self.bed_prop.dragged.connect(self.on_bed_dragged)
        self.bed_prop.drag_finished.connect(self.on_bed_drag_finished)
        self.placement_overlay = PlacementOverlay()
        self.placement_overlay.selected.connect(self.on_placement_selected)
        self.placement_overlay.cancelled.connect(self.on_placement_cancelled)
        self.pair_dialog: PairingDialog | None = None
        self.play("Idle", loop=True)
        self.behavior_timer.start()
        self.event_timer.start()
        self._place_initially()
        self.restore_bed()
        if self.service.state_dict()["asleep"]:
            if self.bed_prop.isVisible():
                self.snap_to_bed()
                self.sleeping_on_bed = True
            self.play("Sleep", loop=True)
        elif self.service.state_dict().get("seated"):
            self.play("Sit", loop=True)
        if service.config.eevee_companion_enabled:
            self.eevee_presence_timer.start()
            QTimer.singleShot(900, self.update_eevee_presence)

    def _place_initially(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 40, screen.bottom() - self.height() - 18)

    @staticmethod
    def _reserved_geometry(rect: QRect) -> ReservedRect:
        return ReservedRect(rect.x(), rect.y(), rect.width(), rect.height())

    def _screen_for_pet(self) -> Any:
        return QApplication.screenAt(self._arfoxia_center()) or QApplication.primaryScreen()

    def _arfoxia_center(self) -> QPoint:
        sprite = self._arfoxia_rect()
        return QPoint(sprite.x + sprite.width // 2, sprite.y + sprite.height // 2)

    def _movement_ranges_on_screen(self, screen: Any) -> list[tuple[int, int]]:
        available = screen.availableGeometry()
        minimum = available.left() + 8
        maximum = max(minimum, available.left() + available.width() - self.width() - 8)
        sprite = self._arfoxia_rect()
        offset_x = sprite.x - self.x()
        obstacle = self._eevee_rect()
        if obstacle is None:
            return [(minimum, maximum)]
        ranges = horizontal_safe_ranges(
            minimum + offset_x,
            maximum + offset_x,
            window_width=sprite.width,
            window_y=sprite.y,
            window_height=sprite.height,
            obstacle=obstacle,
            padding=max(0, int(self.service.config.eevee_avoidance_padding)),
        )
        return [(start - offset_x, end - offset_x) for start, end in ranges]

    # --- Persistent bed -------------------------------------------------

    def restore_bed(self) -> None:
        config = self.service.config
        if not config.bed_enabled:
            self.bed_prop.hide()
            return
        screens = QApplication.screens()
        screen = next(
            (candidate for candidate in screens if candidate.name() == config.bed_screen_name),
            QApplication.primaryScreen(),
        )
        geometry = self._reserved_geometry(screen.availableGeometry())
        x, y = item_position_from_ratios(
            geometry,
            item_width=self.bed_prop.width(),
            item_height=self.bed_prop.height(),
            x_ratio=config.bed_x_ratio,
            y_ratio=config.bed_y_ratio,
        )
        self.bed_prop.move(x, y)
        self.bed_prop.show()
        self.bed_prop.raise_()
        self.ensure_bed_separation(save=False)
        self.save_bed_position()

    def save_bed_position(self) -> None:
        if not self.bed_prop.isVisible():
            return
        center = QPoint(
            self.bed_prop.x() + self.bed_prop.width() // 2,
            self.bed_prop.y() + self.bed_prop.height() // 2,
        )
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        geometry = self._reserved_geometry(screen.availableGeometry())
        x_ratio, y_ratio = normalized_item_position(self.bed_prop.screen_rect(), geometry)
        config = self.service.config
        config.bed_enabled = True
        config.bed_screen_name = screen.name()
        config.bed_x_ratio = x_ratio
        config.bed_y_ratio = y_ratio
        self.service.store.save(config)

    def begin_bed_placement(self) -> None:
        if self.interaction_mode != "idle":
            self.show_speech("Gla… termina primero lo que estamos haciendo.")
            return
        self.interaction_mode = "placing_bed"
        self.placement_overlay.begin(
            "bed",
            self.bed_prop.source,
            "Haz clic para colocar la cama · Esc cancela",
        )

    def place_bed(self, point: QPoint) -> None:
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        minimum_x = available.left()
        maximum_x = max(minimum_x, available.left() + available.width() - self.bed_prop.width())
        minimum_y = available.top()
        maximum_y = max(minimum_y, available.top() + available.height() - self.bed_prop.height())
        x = max(minimum_x, min(point.x() - self.bed_prop.width() // 2, maximum_x))
        y = max(minimum_y, min(point.y() - self.bed_prop.height() // 2, maximum_y))
        self.bed_prop.move(x, y)
        self.bed_prop.show()
        self.bed_prop.raise_()
        self.interaction_mode = "idle"
        self.ensure_bed_separation(save=False)
        if self.sleeping_on_bed:
            self.snap_to_bed()
        self.save_bed_position()
        self.raise_()
        self.show_speech("¡Gla! La cama está lista. ❄")

    def on_bed_dragged(self, position: QPoint) -> None:
        del position
        if self.sleeping_on_bed:
            self.snap_to_bed()

    def on_bed_drag_finished(self, position: QPoint) -> None:
        del position
        center = QPoint(
            self.bed_prop.x() + self.bed_prop.width() // 2,
            self.bed_prop.y() + self.bed_prop.height() // 2,
        )
        screen = (
            QApplication.screenAt(center)
            or QApplication.screenAt(QCursor.pos())
            or QApplication.primaryScreen()
        )
        available = screen.availableGeometry()
        maximum_x = max(
            available.left(),
            available.left() + available.width() - self.bed_prop.width(),
        )
        maximum_y = max(
            available.top(),
            available.top() + available.height() - self.bed_prop.height(),
        )
        self.bed_prop.move(
            max(available.left(), min(self.bed_prop.x(), maximum_x)),
            max(available.top(), min(self.bed_prop.y(), maximum_y)),
        )
        self.ensure_bed_separation(save=False)
        if self.sleeping_on_bed:
            self.snap_to_bed()
        self.save_bed_position()

    def remove_bed(self) -> None:
        if self.sleeping_on_bed:
            self.sleeping_on_bed = False
            if self.service.state_dict()["asleep"]:
                self.service.interact("wake")
        self.bed_prop.hide()
        config = self.service.config
        config.bed_enabled = False
        config.bed_screen_name = ""
        self.service.store.save(config)
        self.show_speech("Ceon~ cama guardada.")

    def ensure_bed_separation(self, *, save: bool = True) -> None:
        mascot = self._eevee_rect()
        if mascot is None or not self.bed_prop.isVisible():
            return
        obstacle = overlay_window_rect(mascot)
        bed = self.bed_prop.screen_rect()
        if not rectangles_overlap(bed, obstacle, padding=12):
            return
        center = QPoint(bed.x + bed.width // 2, bed.y + bed.height // 2)
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        minimum = available.left()
        maximum = max(minimum, available.left() + available.width() - bed.width)
        safe_x = nearest_safe_x(
            bed.x,
            minimum,
            maximum,
            window_width=bed.width,
            window_y=bed.y,
            window_height=bed.height,
            obstacle=obstacle,
            padding=12,
        )
        if safe_x is None:
            return
        self.bed_prop.move(safe_x, bed.y)
        if self.sleeping_on_bed:
            self.snap_to_bed()
        if save:
            self.save_bed_position()

    def snap_to_bed(self) -> None:
        if not self.bed_prop.isVisible():
            return
        x, y = sleeping_window_position(
            self.bed_prop.screen_rect(),
            window_width=self.width(),
            window_height=self.height(),
        )
        self.move(x, y)
        self.bed_prop.raise_()
        self.raise_()

    def sleep_on_bed(self) -> None:
        self.wander_target = None
        self.movement_purpose = "idle"
        self.movement_timer.stop()
        self.sleeping_on_bed = True
        self.play("Sleep", loop=True)
        self.snap_to_bed()
        if not self.service.state_dict()["asleep"]:
            self.service.interact("sleep")

    # --- Food sequence --------------------------------------------------

    def request_feed(self) -> None:
        if self.interaction_mode != "idle":
            self.show_speech("Gla… dame un momento.")
            return
        self.service.interact("feed")

    def start_feed_sequence(self) -> None:
        if self.placement_overlay.mode == "lemon":
            self.cancel_fetch_game()
        elif self.placement_overlay.mode:
            self.placement_overlay.cancel()
        if self.interaction_mode not in {"idle", "feeding"}:
            self.cancel_fetch_game()
        self.interaction_mode = "feeding"
        self.wander_target = None
        self.movement_purpose = "idle"
        self.movement_timer.stop()
        self.feed_stage = 0
        self.berry_prop.set_display_size(*BERRY_SIZE)
        self.position_berry()
        self.berry_prop.show()
        self.berry_prop.raise_()
        self.play("LookUp", loop=False)
        self.feed_timer.start(320)

    def position_berry(self) -> None:
        sprite = self._arfoxia_rect()
        center = QPoint(
            sprite.x + sprite.width // 2,
            sprite.bottom - self.berry_prop.height() // 2 - 8,
        )
        self.berry_prop.move_center_to(center)

    def advance_feed_sequence(self) -> None:
        if self.interaction_mode != "feeding":
            return
        sizes = (72, 52, 30)
        if self.feed_stage == 0:
            self.play("Eat", loop=True)
        if self.feed_stage < len(sizes):
            size = sizes[self.feed_stage]
            self.berry_prop.set_display_size(size, size)
            self.position_berry()
            self.feed_stage += 1
            self.feed_timer.start(240)
            return
        self.berry_prop.hide()
        self.interaction_mode = "idle"
        self.play("Sleep" if self.service.state_dict()["asleep"] else "Idle", loop=True)
        reaction = random.choice(INTERACTION_SPEECH["feed"])
        self.show_speech(reaction)
        self.cry_player.play("feed")

    # --- Lemon fetch game ---------------------------------------------

    def begin_fetch_game(self) -> None:
        if self.interaction_mode != "idle":
            self.show_speech("Gla… termina primero lo que estamos haciendo.")
            return
        if self.service.state_dict().get("seated"):
            self.service.interact("resume")
        if self.service.state_dict()["asleep"]:
            self.sleeping_on_bed = False
            self.service.interact("wake")
        self.wander_target = None
        self.movement_purpose = "idle"
        self.movement_timer.stop()
        self.fetch_home_x = self.x()
        self.interaction_mode = "aiming_lemon"
        self.placement_overlay.begin(
            "lemon",
            self.lemon_prop.source,
            "Mueve el limón y haz clic para lanzarlo · Esc cancela",
        )

    def on_placement_selected(self, mode: str, point: QPoint) -> None:
        if mode == "bed" and self.interaction_mode == "placing_bed":
            self.place_bed(point)
        elif mode == "lemon" and self.interaction_mode == "aiming_lemon":
            self.throw_lemon(point)

    def on_placement_cancelled(self, mode: str) -> None:
        expected = "placing_bed" if mode == "bed" else "aiming_lemon"
        if self.interaction_mode == expected:
            self.interaction_mode = "idle"
            self.show_speech("Ceon~ cancelado.")

    def throw_lemon(self, point: QPoint) -> None:
        screen = self._screen_for_pet()
        available = screen.availableGeometry()
        ranges = self._movement_ranges_on_screen(screen)
        desired_window_x = point.x() - self.width() // 2
        target_window_x = choose_reachable_x(self.x(), desired_window_x, ranges)
        if target_window_x is None:
            self.cancel_fetch_game("Gla… no encuentro un camino seguro.")
            return
        landing_center_x = target_window_x + self.width() // 2
        sprite = self._arfoxia_rect()
        end = QPoint(
            landing_center_x - self.lemon_prop.width() // 2,
            sprite.bottom - self.lemon_prop.height() + 4,
        )
        start_center_x = max(
            available.left() + self.lemon_prop.width() // 2,
            min(point.x(), available.right() - self.lemon_prop.width() // 2 + 1),
        )
        start_center_y = max(
            available.top() + self.lemon_prop.height() // 2,
            min(point.y(), available.bottom() - self.lemon_prop.height() // 2 + 1),
        )
        self.lemon_flight_start = QPoint(
            start_center_x - self.lemon_prop.width() // 2,
            start_center_y - self.lemon_prop.height() // 2,
        )
        self.lemon_flight_end = end
        self.lemon_target_window_x = target_window_x
        self.interaction_mode = "lemon_flying"
        self.lemon_prop.move(self.lemon_flight_start)
        self.lemon_prop.show()
        self.lemon_prop.raise_()
        self.lemon_flight.start()

    def move_lemon_in_flight(self, value: Any) -> None:
        if self.interaction_mode != "lemon_flying":
            return
        point = parabolic_point(
            self.lemon_flight_start,
            self.lemon_flight_end,
            float(value),
            arc_height=120,
        )
        self.lemon_prop.move(point)

    def start_lemon_chase(self) -> None:
        if self.interaction_mode != "lemon_flying":
            return
        self.interaction_mode = "fetching"
        self.movement_purpose = "fetch"
        self.wander_target = self.lemon_target_window_x
        if abs(self.wander_target - self.x()) <= 3:
            self.collect_lemon()
            return
        self.play("Walk", direction=2 if self.wander_target > self.x() else 6, loop=True)
        self.movement_timer.start()

    def collect_lemon(self) -> None:
        if self.interaction_mode != "fetching":
            return
        self.interaction_mode = "returning"
        self.movement_purpose = "return"
        self.position_carried_lemon()
        self.lemon_prop.show()
        screen = self._screen_for_pet()
        cursor = QCursor.pos()
        desired = self.fetch_home_x if self.fetch_home_x is not None else self.x()
        if screen.availableGeometry().contains(cursor):
            desired = cursor.x() - self.width() // 2
        target = choose_reachable_x(self.x(), desired, self._movement_ranges_on_screen(screen))
        self.wander_target = self.x() if target is None else target
        if abs(self.wander_target - self.x()) <= 3:
            self.finish_fetch_game()
            return
        self.play("Walk", direction=2 if self.wander_target > self.x() else 6, loop=True)
        self.movement_timer.start()

    def position_carried_lemon(self) -> None:
        sprite = self._arfoxia_rect()
        x = sprite.right - 12 if self.direction in {1, 2, 3} else sprite.x + 12
        y = sprite.y + round(sprite.height * 0.58)
        self.lemon_prop.move_center_to(QPoint(x, y))

    def finish_fetch_game(self) -> None:
        if self.interaction_mode != "returning":
            return
        self.lemon_prop.hide()
        self.wander_target = None
        self.movement_purpose = "idle"
        self.movement_timer.stop()
        self.interaction_mode = "idle"
        self.fetch_home_x = None
        self.fetch_just_completed = True
        self.service.interact("play")

    def cancel_fetch_game(self, message: str = "") -> None:
        if self.placement_overlay.mode == "lemon":
            self.placement_overlay.cancel()
        self.lemon_flight.stop()
        self.lemon_prop.hide()
        self.wander_target = None
        self.movement_purpose = "idle"
        self.movement_timer.stop()
        if self.interaction_mode in {
            "aiming_lemon",
            "lemon_flying",
            "fetching",
            "returning",
        }:
            self.interaction_mode = "idle"
        self.fetch_home_x = None
        if message:
            self.show_speech(message)
        self.play("Sleep" if self.service.state_dict()["asleep"] else "Idle", loop=True)

    def _eevee_rect(self) -> ReservedRect | None:
        return self.eevee_presence.reserved_rect if self.eevee_presence.visible else None

    def _arfoxia_rect(self, x: int | None = None, y: int | None = None) -> ReservedRect:
        """Return the visible sprite box rather than the transparent 420px host."""

        if self.frames:
            sprite_width = max(frame.width() for frame in self.frames)
            sprite_height = max(frame.height() for frame in self.frames)
        else:
            sprite_width, sprite_height = 128, 160
        window_x = self.x() if x is None else int(x)
        window_y = self.y() if y is None else int(y)
        return ReservedRect(
            window_x + (self.width() - sprite_width) // 2,
            window_y + self.height() - sprite_height - 12,
            sprite_width,
            sprite_height,
        )

    def _horizontal_limits(self, obstacle: ReservedRect) -> tuple[int, int]:
        center = QPoint(obstacle.x + obstacle.width // 2, obstacle.y + obstacle.height // 2)
        screen = QApplication.screenAt(center) or QApplication.screenAt(self.frameGeometry().center())
        available = (screen or QApplication.primaryScreen()).availableGeometry()
        minimum = available.left() + 8
        maximum = available.left() + available.width() - self.width() - 8
        return minimum, max(minimum, maximum)

    def _safe_ranges_next_to_eevee(self) -> list[tuple[int, int]]:
        obstacle = self._eevee_rect()
        if obstacle is None:
            return []
        minimum, maximum = self._horizontal_limits(obstacle)
        sprite = self._arfoxia_rect()
        offset_x = sprite.x - self.x()
        ranges = horizontal_safe_ranges(
            minimum + offset_x,
            maximum + offset_x,
            window_width=sprite.width,
            window_y=sprite.y,
            window_height=sprite.height,
            obstacle=obstacle,
            padding=max(0, int(self.service.config.eevee_avoidance_padding)),
        )
        return [(start - offset_x, end - offset_x) for start, end in ranges]

    def ensure_eevee_separation(self) -> None:
        if self.service.state_dict().get("seated"):
            return
        obstacle = self._eevee_rect()
        if obstacle is None or self.drag_origin is not None:
            return
        padding = max(0, int(self.service.config.eevee_avoidance_padding))
        if not rectangles_overlap(self._arfoxia_rect(), obstacle, padding=padding):
            return
        minimum, maximum = self._horizontal_limits(obstacle)
        sprite = self._arfoxia_rect()
        offset_x = sprite.x - self.x()
        safe_sprite_x = nearest_safe_x(
            sprite.x,
            minimum + offset_x,
            maximum + offset_x,
            window_width=sprite.width,
            window_y=sprite.y,
            window_height=sprite.height,
            obstacle=obstacle,
            padding=padding,
        )
        if safe_sprite_x is not None:
            self.wander_target = None
            self.movement_purpose = "idle"
            self.movement_timer.stop()
            self.move(safe_sprite_x - offset_x, self.y())

    def move_next_to_eevee(self) -> None:
        if self.service.state_dict().get("seated"):
            return
        obstacle = self._eevee_rect()
        ranges = self._safe_ranges_next_to_eevee()
        if obstacle is None or not ranges:
            return
        sprite = self._arfoxia_rect()
        offset_x = sprite.x - self.x()
        candidates = [
            end if end + offset_x + sprite.width <= obstacle.x else start
            for start, end in ranges
        ]
        target = min(candidates, key=lambda value: abs(value - self.x()))
        if abs(target - self.x()) <= 10:
            return
        self.wander_target = target
        self.movement_purpose = "eevee"
        self.play("Walk", direction=2 if target > self.x() else 6, loop=True)
        self.movement_timer.start()

    def update_eevee_presence(self) -> None:
        if not self.service.config.eevee_companion_enabled:
            return
        detected = detect_codex_presence()
        was_visible = self.eevee_presence.visible
        if not detected.visible:
            self.eevee_missed_polls += 1
            # Codex writes its JSON state atomically, but a poll can still land
            # between replacements. Two misses prevent a repeated hello flicker.
            if was_visible and self.eevee_missed_polls < 2:
                return
            self.eevee_presence = CodexPresence(False)
            self.eevee_interaction_timer.stop()
            return

        self.eevee_missed_polls = 0
        self.eevee_presence = detected
        if self.service.state_dict().get("seated"):
            self.eevee_interaction_timer.stop()
            return
        self.ensure_bed_separation()
        if self.interaction_mode in {
            "aiming_lemon",
            "lemon_flying",
            "fetching",
            "returning",
        }:
            self.cancel_fetch_game("Gla… Eevee se acercó; jugamos luego.")
        self.ensure_eevee_separation()
        if not was_visible:
            if self.interaction_mode != "idle" or self.service.state_dict()["asleep"]:
                self._schedule_eevee_interaction(retry=True)
                return
            self.move_next_to_eevee()
            if not self.movement_timer.isActive():
                self.play(random.choice(["Nod", "LookUp", "Hop"]), loop=False)
            self.show_speech(random.choice(EEVEE_GREETING_SPEECH), source="interaction")
            self.cry_player.play("eevee")
            self._schedule_eevee_interaction()

    def _schedule_eevee_interaction(self, retry: bool = False) -> None:
        if not self.eevee_presence.visible:
            self.eevee_interaction_timer.stop()
            return
        if retry:
            delay = 25_000
        else:
            base = max(
                45_000,
                min(int(self.service.config.eevee_interaction_interval_ms), 900_000),
            )
            delay = int(base * random.uniform(0.82, 1.18))
        self.eevee_interaction_timer.start(delay)

    def interact_with_eevee(self) -> None:
        if not self.eevee_presence.visible:
            return
        state = self.service.state_dict()
        busy = (
            state["asleep"]
            or state.get("seated", False)
            or self.quick_chat.isVisible()
            or self.chat_window.isVisible()
            or self.speech_bubble.isVisible()
            or self.interaction_mode != "idle"
        )
        if busy:
            self._schedule_eevee_interaction(retry=True)
            return
        self.ensure_eevee_separation()
        obstacle = self._eevee_rect()
        if obstacle is not None:
            direction = 2 if obstacle.x > self.x() + self.width() // 2 else 6
            self.play(random.choice(["Nod", "LookUp", "TailWhip", "Hop"]), direction=direction)
        self.show_speech(random.choice(EEVEE_COMPANION_SPEECH), source="interaction")
        self.cry_player.play("eevee")
        self._schedule_eevee_interaction()

    def play(self, name: str, direction: int | None = None, loop: bool = False) -> None:
        if self.interaction_mode == "idle" and self.service.state_dict().get("seated"):
            name, loop = "Sit", True
        if name not in self.library.available():
            name = "Idle"
        if direction is not None:
            self.direction = direction
        images, durations = self.library.frames(name, self.direction)
        self.frames = [image_to_pixmap(image, self.scale) for image in images]
        self.durations = durations
        self.frame_index = 0
        self.loop_animation = loop
        self.current_animation = name
        self.render_frame()

    def render_frame(self) -> None:
        if not self.frames:
            return
        self.update()
        self.animation_timer.start(self.durations[self.frame_index])
        pixmap = self.frames[self.frame_index]
        x = (self.width() - pixmap.width()) // 2
        y = self.height() - pixmap.height() - 12
        try:
            region = QRegion(pixmap.mask()).translated(x, y)
            self.setMask(region)
        except TypeError:
            self.clearMask()

    def next_frame(self) -> None:
        self.frame_index += 1
        if self.frame_index >= len(self.frames):
            if self.loop_animation:
                self.frame_index = 0
            else:
                self.play("Sleep" if self.service.state_dict()["asleep"] else "Idle", loop=True)
                return
        self.render_frame()

    def paintEvent(self, event: Any) -> None:
        super().paintEvent(event)
        if not self.frames:
            return
        pixmap = self.frames[self.frame_index]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap((self.width() - pixmap.width()) // 2, self.height() - pixmap.height() - 12, pixmap)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.interaction_mode != "idle":
                return
            if self.service.state_dict()["asleep"]:
                self.sleeping_on_bed = False
                self.service.interact("wake")
            self.wander_target = None
            self.movement_purpose = "idle"
            self.movement_timer.stop()
            self.drag_origin = event.globalPosition().toPoint()
            self.window_origin = self.pos()
            self.pet_distance = 0
            self.pet_triggered = False
        elif event.button() == Qt.MouseButton.RightButton:
            self.open_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: Any) -> None:
        if not self.drag_origin or not self.window_origin:
            return
        current = event.globalPosition().toPoint()
        delta = current - self.drag_origin
        self.move(self.window_origin + delta)
        self.pet_distance += abs(delta.x()) + abs(delta.y())
        self.drag_origin = current
        self.window_origin = self.pos()
        if self.pet_distance > 190 and not self.pet_triggered:
            self.pet_triggered = True
            self.service.interact("pet")

    def mouseReleaseEvent(self, event: Any) -> None:
        was_dragged = self.pet_distance > 8
        self.drag_origin = None
        self.window_origin = None
        if (
            was_dragged
            and not self.service.state_dict().get("seated")
            and self.bed_prop.isVisible()
            and foot_is_over_bed(self._arfoxia_rect(), self.bed_prop.screen_rect())
        ):
            self.sleep_on_bed()
            return
        if was_dragged and self.sleeping_on_bed:
            self.sleeping_on_bed = False
            if self.service.state_dict()["asleep"]:
                self.service.interact("wake")
        self.ensure_eevee_separation()

    def mouseDoubleClickEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.show_quick_chat()

    def open_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        gpu_manager_action = menu.addAction("Gestor de GPU…")
        gpu_manager_action.triggered.connect(self.chat_window.show_gpu_manager)
        mode_label = (
            "Volver al modelo normal"
            if self.service.ollama.requested_mode == "power"
            else "Activar modelo Potencia"
        )
        power_action = menu.addAction(mode_label)
        power_action.triggered.connect(self.chat_window.toggle_power_mode)
        menu.addSeparator()
        actions = [
            ("Hablar", self.show_quick_chat),
            ("Conversación completa", self.show_chat),
            ("Dar una Baya Aranja", self.request_feed),
            ("Acariciar", lambda: self.service.interact("pet")),
            ("Jugar con el limón", self.begin_fetch_game),
            ("Colocar / mover cama", self.begin_bed_placement),
            ("Dormir / despertar", self.toggle_sleep),
            ("Volver a pasear" if self.service.state_dict().get("seated") else "Quedarse sentado (sin dormir)", self.toggle_seated),
            ("Hacer captura", lambda: self.service.actions.execute("take_screenshot")),
            ("Emparejar iPhone", self.show_pairing),
        ]
        for label, callback in actions:
            action = menu.addAction(label)
            action.triggered.connect(callback)
        if self.bed_prop.isVisible():
            remove_bed_action = menu.addAction("Quitar cama")
            remove_bed_action.triggered.connect(self.remove_bed)
        sound_action = menu.addAction("Sonidos de Arfoxia")
        sound_action.setCheckable(True)
        sound_action.setChecked(self.service.config.sound_enabled)
        sound_action.toggled.connect(self.set_sound_enabled)
        password_action = menu.addAction("Contraseña de seguridad…")
        password_action.triggered.connect(self.show_password_settings)
        menu.addSeparator()
        quit_action = menu.addAction("Salir")
        quit_action.triggered.connect(QApplication.quit)
        menu.exec(position)

    def set_sound_enabled(self, enabled: bool) -> None:
        self.service.config.sound_enabled = enabled
        self.service.store.save(self.service.config)
        if enabled:
            self.cry_player.last_played_at = 0.0
            self.cry_player.play("wake")

    def show_password_settings(self) -> None:
        dialog = PasswordSettingsDialog(self.service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(
                self,
                "Seguridad de Arfoxia",
                "La contraseña local se ha guardado de forma segura.",
            )

    def toggle_sleep(self) -> None:
        kind = "wake" if self.service.state_dict()["asleep"] else "sleep"
        if kind == "wake":
            self.sleeping_on_bed = False
        self.service.interact(kind)

    def toggle_seated(self) -> None:
        self.service.interact("resume" if self.service.state_dict().get("seated") else "sit")

    def show_chat(self) -> None:
        self.chat_window.refresh_state()
        self.chat_window.showNormal()
        self.chat_window.raise_()
        self.chat_window.activateWindow()

    def _position_companion_window(self, widget: QWidget, gap: int = 10) -> None:
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        sprite = self._arfoxia_rect()
        above = (
            sprite.x + (sprite.width - widget.width()) // 2,
            sprite.y - widget.height() - gap,
        )
        left = (sprite.x - widget.width() - gap, sprite.bottom - widget.height())
        right = (sprite.right + gap, sprite.bottom - widget.height())
        candidates = [above]

        mascot = self._eevee_rect()
        codex_overlay = overlay_window_rect(mascot) if mascot is not None else None
        if codex_overlay is not None:
            arfoxia_center = sprite.x + sprite.width // 2
            eevee_center = mascot.x + mascot.width // 2
            away, toward = (left, right) if eevee_center >= arfoxia_center else (right, left)
            candidates = [above, away, toward]

        min_x = available.left() + 8
        max_x = max(min_x, available.right() - widget.width() - 7)
        min_y = available.top() + 8
        max_y = max(min_y, available.bottom() - widget.height() - 7)
        clamped: list[tuple[int, int]] = []
        for candidate_x, candidate_y in candidates:
            point = (
                max(min_x, min(candidate_x, max_x)),
                max(min_y, min(candidate_y, max_y)),
            )
            if point not in clamped:
                clamped.append(point)

        selected = clamped[0]
        if codex_overlay is not None:
            for candidate_x, candidate_y in clamped:
                candidate_rect = ReservedRect(
                    candidate_x, candidate_y, widget.width(), widget.height()
                )
                if not rectangles_overlap(candidate_rect, codex_overlay, padding=8):
                    selected = (candidate_x, candidate_y)
                    break
        widget.move(*selected)

    def show_speech(self, message: str, source: str = "interaction") -> None:
        if not is_short_dialogue(message, self.service.config.bubble_max_chars):
            return
        if source == "chat":
            self.quick_chat.hide()
        duration = self.service.config.bubble_duration_ms + min(2800, len(message) * 22)
        self.speech_bubble.show_message(message, duration)
        self._position_companion_window(self.speech_bubble, gap=12)
        if source == "chat":
            self.cry_player.play("chat")

    def show_quick_chat(self) -> None:
        self.quick_chat.show_and_focus()
        self._position_companion_window(self.quick_chat, gap=12)

    def prepare_for_authorization(self) -> None:
        """Release desktop input grabs before showing a sensitive dialog."""

        if self.placement_overlay.mode == "lemon":
            self.cancel_fetch_game()
        elif self.placement_overlay.mode:
            self.placement_overlay.cancel()
        self.quick_chat.hide()
        self.speech_bubble.hide()

    def send_quick_message(self, text: str) -> None:
        self.show_speech("Gla… ❄")
        self.chat_window.submit_quick_message(text)

    def on_quick_chat_error(self, payload: Any) -> None:
        message = (
            str(payload.get("message") or "")
            if isinstance(payload, dict)
            else str(payload)
        )
        self.show_speech(f"Gla… {message}")

    def on_model_mode_ready(self, status: Any) -> None:
        payload = status if isinstance(status, dict) else {}
        if payload.get("requested_mode") == "dual":
            self.show_speech("✦ ¡Modo Dual listo! Qwen3.8 está cargado en ambas GPU.")
        elif payload.get("requested_mode") == "power":
            self.show_speech("⚡ ¡Modo Potencia listo! Qwen3.6 está cargado.")
        elif payload.get("requested_mode") == "gaming_gpu":
            self.show_speech("🎮 Modelo pequeño listo en la GPU de 8 GB.")
        else:
            self.show_speech("❄ He vuelto al modelo normal.")

    def moveEvent(self, event: Any) -> None:
        super().moveEvent(event)
        if hasattr(self, "berry_prop") and self.interaction_mode == "feeding":
            self.position_berry()
        if hasattr(self, "lemon_prop") and self.interaction_mode == "returning":
            self.position_carried_lemon()
        if hasattr(self, "speech_bubble") and self.speech_bubble.isVisible():
            self._position_companion_window(self.speech_bubble, gap=12)
        if hasattr(self, "quick_chat") and self.quick_chat.isVisible():
            self._position_companion_window(self.quick_chat, gap=12)

    def pairing_url(self) -> str:
        installed_tailscale = Path("C:/Program Files/Tailscale/tailscale.exe")
        tailscale = shutil.which("tailscale")
        if not tailscale and installed_tailscale.exists():
            tailscale = str(installed_tailscale)
        if tailscale:
            try:
                value = subprocess.run(
                    [tailscale, "status", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=True,
                )
                dns_name = str(json.loads(value.stdout).get("Self", {}).get("DNSName", "")).rstrip(".")
                if dns_name:
                    return (
                        f"https://{dns_name}/?ui={MOBILE_UI_REVISION}"
                        f"#token={self.token}"
                    )
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        host = socket.gethostname()
        return (
            f"http://{host}:{self.service.config.api_port}/"
            f"?ui={MOBILE_UI_REVISION}#token={self.token}"
        )

    def show_pairing(self) -> None:
        self.pair_dialog = PairingDialog(self.pairing_url())
        self.pair_dialog.show()

    def autonomous_behavior(self) -> None:
        if self.interaction_mode != "idle" or self.drag_origin is not None:
            return
        state = self.service.state_dict()
        if state["asleep"]:
            self.play("Sleep", loop=True)
            return
        if state.get("seated"):
            self.play("Sit", loop=True)
            return
        if state["energy"] < 15:
            self.service.interact("sleep")
            return
        if state["hunger"] > 82:
            self.play("Sit", loop=False)
            return
        if random.random() < 0.62:
            self.start_wander()
        else:
            self.play(random.choice(["Idle", "LookUp", "Sit", "DeepBreath"]), loop=False)

    def start_wander(self) -> None:
        state = self.service.state_dict()
        if self.interaction_mode != "idle" or state["asleep"] or state.get("seated"):
            return
        screen_object = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        screen = screen_object.availableGeometry()
        left = screen.left() - self.width() // 3
        right = screen.right() - self.width() * 2 // 3
        ranges = self._safe_ranges_next_to_eevee()
        if ranges:
            containing = [bounds for bounds in ranges if bounds[0] <= self.x() <= bounds[1]]
            if containing:
                active_range = containing[0]
            else:
                active_range = min(
                    ranges,
                    key=lambda bounds: min(abs(self.x() - bounds[0]), abs(self.x() - bounds[1])),
                )
            target = random.randint(active_range[0], max(active_range))
            left, right = active_range
        else:
            target = random.randint(left, max(left, right))
        if abs(target - self.x()) < 140:
            target = left if self.x() > (left + right) // 2 else right
        self.wander_target = target
        self.movement_purpose = "wander"
        direction = 2 if target > self.x() else 6
        self.play("Walk", direction=direction, loop=True)
        self.movement_timer.start()

    def move_step(self) -> None:
        if self.service.state_dict().get("seated"):
            self.wander_target = None
            self.movement_purpose = "idle"
            self.movement_timer.stop()
            self.play("Sit", loop=True)
            return
        if self.wander_target is None:
            self.movement_timer.stop()
            self.movement_purpose = "idle"
            return
        delta = self.wander_target - self.x()
        if abs(delta) <= 3:
            self.move(self.wander_target, self.y())
            completed_purpose = self.movement_purpose
            self.wander_target = None
            self.movement_purpose = "idle"
            self.movement_timer.stop()
            if completed_purpose == "fetch":
                self.collect_lemon()
                return
            if completed_purpose == "return":
                self.finish_fetch_game()
                return
            self.play("Idle", direction=0, loop=True)
            return
        next_x = self.x() + (3 if delta > 0 else -3)
        obstacle = self._eevee_rect()
        padding = max(0, int(self.service.config.eevee_avoidance_padding))
        if obstacle is not None and rectangles_overlap(
            self._arfoxia_rect(next_x), obstacle, padding=padding
        ):
            interrupted_purpose = self.movement_purpose
            self.wander_target = None
            self.movement_purpose = "idle"
            self.movement_timer.stop()
            if interrupted_purpose in {"fetch", "return"}:
                self.cancel_fetch_game("Gla… Eevee está en medio; lo intentamos luego.")
                return
            self.play("Idle", direction=0, loop=True)
            return
        self.move(next_x, self.y())

    def poll_events(self) -> None:
        while not self.service.events.empty():
            event = self.service.events.get_nowait()
            self.chat_window.handle_service_event(event)
            if event.get("type") == "chat_received":
                state = self.service.state_dict()
                if (
                    state["asleep"]
                    or self.interaction_mode != "idle"
                    or self.drag_origin is not None
                ):
                    continue
                # A message may interrupt autonomous wandering, but never a
                # purposeful route such as fetching the lemon or approaching
                # Eevee.
                if self.movement_purpose == "wander":
                    self.wander_target = None
                    self.movement_purpose = "idle"
                    self.movement_timer.stop()
                elif self.movement_purpose != "idle" or self.movement_timer.isActive():
                    continue
                self.play(
                    "LookUp" if event.get("has_attachments") else "Sit",
                    loop=False,
                )
            elif event.get("type") == "interaction":
                kind = str(event.get("kind", ""))
                if kind == "sit":
                    self.placement_overlay.cancel()
                    self.cancel_fetch_game()
                    self.feed_timer.stop()
                    self.berry_prop.hide()
                    self.interaction_mode = "idle"
                    self.sleeping_on_bed = False
                    self.wander_target = None
                    self.movement_purpose = "idle"
                    self.movement_timer.stop()
                    self.eevee_interaction_timer.stop()
                    self.play("Sit", loop=True)
                    continue
                if kind == "resume":
                    self.sleeping_on_bed = False
                    self.play("Idle", loop=True)
                    self._schedule_eevee_interaction()
                    continue
                if kind in {"feed", "pet", "play", "wake"}:
                    self.sleeping_on_bed = False
                if kind == "feed":
                    self.start_feed_sequence()
                    continue
                if kind == "sleep" and self.interaction_mode in {
                    "aiming_lemon",
                    "lemon_flying",
                    "fetching",
                    "returning",
                }:
                    self.cancel_fetch_game()
                animation = str(event.get("animation", "Idle"))
                self.play(animation, loop=animation == "Sleep")
                if kind == "play" and self.fetch_just_completed:
                    self.fetch_just_completed = False
                    reaction = random.choice(
                        (
                            f"¡Gla! Te traje el limón, {self.service.config.owner_name}.",
                            "¡Gla-ceon! *deja el limón junto a ti*",
                            "Ceon~ ¡otra vez cuando quieras!",
                        )
                    )
                else:
                    reaction = random.choice(INTERACTION_SPEECH.get(kind, ("¡Gla!",)))
                self.show_speech(reaction)
                self.cry_player.play(kind)
            elif event.get("type") == "action":
                mapping = {
                    "take_screenshot": "Pose",
                    "open_app": "Nod",
                    "open_target": "Nod",
                    "close_app": "TailWhip",
                    "file_operation": "Nod",
                    "pc_status": "LookUp",
                    "volume": "Nod",
                    "web_search": "LookUp",
                    "web_research": "LookUp",
                    "codex_list_tasks": "LookUp",
                    "codex_open_task": "Nod",
                    "codex_pause_task": "Nod",
                }
                self.play(mapping.get(str(event.get("action")), "Idle"), loop=False)
                result = event.get("result") or {}
                message = str(result.get("message") or "")
                if message:
                    self.show_speech(message, source="action")
            elif event.get("type") == "authorization_requested":
                self.prepare_for_authorization()
                self.chat_window.request_authorization(
                    str(event.get("challenge_id") or ""),
                    str(event.get("summary") or "Acción importante"),
                    bool(event.get("password_configured", False)),
                    auto_prompt=False,
                    conversation_id=(
                        str(event.get("conversation_id") or "") or None
                    ),
                )
            elif event.get("type") == "speech":
                self.show_speech(str(event.get("message") or ""), source="chat")
            elif event.get("type") == "ui" and event.get("action") == "show_chat":
                self.show_chat()

    def closeEvent(self, event: Any) -> None:
        self.eevee_presence_timer.stop()
        self.eevee_interaction_timer.stop()
        self.feed_timer.stop()
        self.lemon_flight.stop()
        self.placement_overlay.shutdown()
        self.placement_overlay.close()
        self.berry_prop.close()
        self.lemon_prop.close()
        self.bed_prop.close()
        self.speech_bubble.close()
        self.quick_chat.close()
        self.chat_window.close()
        self.bridge.shutdown()
        super().closeEvent(event)


class DesktopController(QObject):
    def __init__(self, service: CompanionService, token: str) -> None:
        super().__init__()
        self.pet = PetWindow(service, token)
        first_icon = self.pet.frames[0] if self.pet.frames else QPixmap()
        self.tray = QSystemTrayIcon(first_icon, self)
        tray_menu = QMenu()
        show_action = QAction(f"Mostrar a {service.config.name}", tray_menu)
        chat_action = QAction(f"Hablar con {service.config.name}", tray_menu)
        full_chat_action = QAction("Conversación completa", tray_menu)
        gpu_action = QAction("Gestor de GPU", tray_menu)
        pair_action = QAction("Emparejar iPhone", tray_menu)
        sit_action = QAction("Quedarse sentado (sin dormir)", tray_menu)
        resume_action = QAction("Volver a pasear", tray_menu)
        quit_action = QAction("Salir", tray_menu)
        show_action.triggered.connect(self.pet.show)
        chat_action.triggered.connect(self.pet.show_quick_chat)
        full_chat_action.triggered.connect(self.pet.show_chat)
        gpu_action.triggered.connect(self.pet.chat_window.show_gpu_manager)
        pair_action.triggered.connect(self.pet.show_pairing)
        sit_action.triggered.connect(lambda: service.interact("sit"))
        resume_action.triggered.connect(lambda: service.interact("resume"))
        quit_action.triggered.connect(QApplication.quit)
        for action in (
            show_action,
            chat_action,
            full_chat_action,
            gpu_action,
            pair_action,
            sit_action,
            resume_action,
        ):
            tray_menu.addAction(action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self.tray.setContextMenu(tray_menu)
        self.tray.setToolTip(f"{service.config.name} · {service.config.species} ♂")
        self.tray.activated.connect(
            lambda reason: self.pet.show_quick_chat()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )

    def show(self) -> None:
        self.pet.show()
        self.tray.show()
