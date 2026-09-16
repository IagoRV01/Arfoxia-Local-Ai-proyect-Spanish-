from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QImage, QTextDocument
from PySide6.QtWidgets import QApplication, QMessageBox

from glaceon_companion.ui import (
    ChatWindow,
    GpuManagerDialog,
    SafeMarkdownBrowser,
    SpeechBubble,
    is_safe_https_url,
)


def test_gpu_manager_status_renders_both_cards_and_active_profile():
    rendered = GpuManagerDialog.status_html(
        {
            "requested_mode": "gaming_gpu",
            "model": "qwen3.5:4b",
            "loaded_models": [],
            "gaming_gpu_loaded_models": [{"name": "qwen3.5:4b"}],
            "gpus": [
                {
                    "index": 0,
                    "uuid": "GPU-8GB",
                    "name": "RTX 5060 Ti",
                    "role": "gaming",
                    "total_gb": 7.96,
                    "used_gb": 4.49,
                    "free_gb": 3.22,
                    "utilization_percent": 91,
                    "temperature_c": 62,
                },
                {
                    "index": 1,
                    "uuid": "GPU-16GB",
                    "name": "RTX 5060 Ti",
                    "role": "ai",
                    "total_gb": 15.93,
                    "used_gb": 1.0,
                    "free_gb": 14.9,
                    "utilization_percent": 2,
                    "temperature_c": 39,
                },
            ],
        }
    )

    assert "Modelo pequeño · GPU de juego" in rendered
    assert "GPU de juego · 8 GB" in rendered
    assert "GPU de IA · 16 GB" in rendered
    assert "qwen3.5:4b" in rendered
    assert "GPU-8GB" in rendered
    assert "GPU-16GB" in rendered


def test_gpu_manager_dual_button_is_manual_and_game_gated(app):
    calls = []
    bridge = SimpleNamespace(set_model_mode=calls.append)
    dialog = GpuManagerDialog(SimpleNamespace(), bridge)
    try:
        dialog._on_status({"requested_mode": "normal", "dual_model_installed": True,
                           "game": {"active": False}, "gpus": []})
        assert dialog.dual_button.isEnabled()
        dialog.dual_button.click()
        assert calls == ["dual"]
        dialog._on_mode_ready({"requested_mode": "dual", "dual_model_installed": True,
                              "game": {"active": False}, "gpus": []})
        assert not dialog.dual_button.isEnabled()
        assert "Dual Extra High activo" in dialog.state_label.text()
        assert "20 s" in dialog.state_label.text()
        assert "manualmente" in dialog.state_label.text()
        dialog._on_mode_ready({"requested_mode": "normal", "dual_model_installed": True,
                              "game": {"active": True}, "gpus": []})
        assert not dialog.dual_button.isEnabled()
    finally:
        dialog.close()


def test_gpu_manager_coalesces_periodic_status_requests(app):
    del app

    class StatusBridge(QObject):
        model_status_ready = Signal(object)
        model_status_error = Signal(str)
        model_mode_ready = Signal(object)
        model_mode_error = Signal(str)
        model_unload_ready = Signal()
        model_unload_error = Signal(str)

        def __init__(self):
            super().__init__()
            self.requests = 0

        def request_model_status(self):
            self.requests += 1

    bridge = StatusBridge()
    dialog = GpuManagerDialog(SimpleNamespace(), bridge)
    try:
        dialog.refresh()
        dialog.refresh()
        assert bridge.requests == 1
        assert dialog.refresh_pending

        dialog._on_status({"requested_mode": "normal", "gpus": []})
        dialog.refresh()
        assert bridge.requests == 2
    finally:
        dialog.close()


class FakeBridge(QObject):
    chat_ready = Signal(object)
    chat_error = Signal(object)
    authorization_ready = Signal(object)
    authorization_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        text: str,
        attachment_ids: list[str] | None = None,
        *,
        conversation_id: str | None = None,
        research_mode: bool = False,
    ) -> str:
        request_id = f"request-{len(self.calls) + 1}"
        self.calls.append(
            {
                "request_id": request_id,
                "text": text,
                "attachment_ids": list(attachment_ids or []),
                "conversation_id": conversation_id,
                "research_mode": research_mode,
            }
        )
        return request_id

    def authorize(self, challenge_id: str, password: str) -> None:
        del challenge_id, password


class FakeAttachments:
    def __init__(self) -> None:
        self.discarded: list[str] = []

    def discard(self, identifiers: list[str]) -> None:
        self.discarded.extend(identifiers)


class FakeConversationService:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            name="Arfoxia",
            owner_name="Gori",
            bubble_max_chars=180,
        )
        self.authorization = SimpleNamespace(is_configured=True)
        self.attachments = FakeAttachments()
        self.create_calls = 0
        self._next_conversation = 3
        self._next_message = 5
        self.conversations = [
            {"id": "c1", "title": "General"},
            {"id": "c2", "title": "Proyecto"},
        ]
        self.messages: dict[str, list[dict[str, Any]]] = {
            "c1": [
                {"id": 1, "role": "user", "content": "Hola antigua"},
                {"id": 2, "role": "assistant", "content": "Recuerdo este chat"},
            ],
            "c2": [
                {"id": 3, "role": "user", "content": "Plan del proyecto"},
                {"id": 4, "role": "assistant", "content": "Seguimos aquí"},
            ],
        }

    def state_dict(self) -> dict[str, Any]:
        return {
            "mood": "feliz",
            "hunger": 10.0,
            "energy": 90.0,
            "happiness": 95.0,
        }

    def list_conversations(self) -> dict[str, Any]:
        return {"conversations": [dict(item) for item in self.conversations]}

    def create_conversation(self, title: str | None = None) -> dict[str, Any]:
        self.create_calls += 1
        conversation = {
            "id": f"c{self._next_conversation}",
            "title": title or "Nueva conversación",
        }
        self._next_conversation += 1
        self.conversations.insert(0, conversation)
        self.messages[conversation["id"]] = []
        return dict(conversation)

    def rename_conversation(
        self, conversation_id: str, title: str
    ) -> dict[str, Any]:
        conversation = self._conversation(conversation_id)
        conversation["title"] = title
        return dict(conversation)

    def delete_conversation(self, conversation_id: str) -> dict[str, Any]:
        deleted = self._conversation(conversation_id)
        self.conversations = [
            item
            for item in self.conversations
            if item["id"] != conversation_id
        ]
        self.messages.pop(conversation_id, None)
        replacement = self.conversations[0] if self.conversations else None
        return {
            "deleted": dict(deleted),
            "replacement": dict(replacement) if replacement else None,
        }

    def conversation_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before_id: int | None = None,
    ) -> dict[str, Any]:
        rows = list(self.messages[conversation_id])
        if before_id is not None:
            rows = [row for row in rows if int(row["id"]) < before_id]
        page = rows[-limit:]
        return {
            "messages": [dict(row) for row in page],
            "has_more": len(rows) > len(page),
        }

    def append_message(
        self, conversation_id: str, role: str, content: str
    ) -> dict[str, Any]:
        message = {
            "id": self._next_message,
            "role": role,
            "content": content,
        }
        self._next_message += 1
        self.messages[conversation_id].append(message)
        return dict(message)

    def cancel_authorization(self, challenge_id: str) -> bool:
        del challenge_id
        return True

    def _conversation(self, conversation_id: str) -> dict[str, Any]:
        return next(
            item
            for item in self.conversations
            if item["id"] == conversation_id
        )


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def conversation_window(app):
    del app
    service = FakeConversationService()
    bridge = FakeBridge()
    window = ChatWindow(service, bridge)
    yield window, service, bridge
    window.close()


def select_conversation(window: ChatWindow, conversation_id: str) -> None:
    window.conversation_list.setCurrentItem(
        window._conversation_items[conversation_id]
    )


def test_selector_loads_the_canonical_history_for_each_conversation(
    conversation_window,
):
    window, _, _ = conversation_window

    assert window.current_conversation_id == "c1"
    assert "Hola antigua" in window.transcript.toPlainText()
    assert "Plan del proyecto" not in window.transcript.toPlainText()

    select_conversation(window, "c2")

    assert window.current_conversation_id == "c2"
    assert window.conversation_title.text() == "Proyecto"
    assert "Plan del proyecto" in window.transcript.toPlainText()
    assert "Hola antigua" not in window.transcript.toPlainText()


def test_chat_window_has_snowflake_icon_and_native_minimize_button(
    conversation_window,
):
    window, _, _ = conversation_window
    flags = window.windowFlags()

    assert flags & Qt.WindowType.WindowMinimizeButtonHint
    assert flags & Qt.WindowType.WindowCloseButtonHint
    assert not flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Window
    assert not window.windowIcon().isNull()


def test_create_rename_and_confirmed_delete_keep_a_valid_selection(
    conversation_window, monkeypatch
):
    window, service, _ = conversation_window

    window.new_conversation(title="Viaje")
    created_id = window.current_conversation_id
    assert created_id is not None
    assert window.conversation_title.text() == "Viaje"

    window.rename_current_conversation(title="Viaje a Japón")
    assert window.conversation_title.text() == "Viaje a Japón"
    assert service._conversation(created_id)["title"] == "Viaje a Japón"

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window.delete_current_conversation()

    assert all(item["id"] != created_id for item in service.conversations)
    assert window.current_conversation_id in {
        item["id"] for item in service.conversations
    }


def test_late_reply_never_appears_in_the_conversation_selected_after_send(
    conversation_window,
):
    window, service, bridge = conversation_window
    select_conversation(window, "c1")

    request_id = window.submit_quick_message("Pregunta del chat uno")
    assert request_id
    assert service.create_calls == 0
    assert bridge.calls[-1]["conversation_id"] == "c1"
    select_conversation(window, "c2")

    user_message = service.append_message(
        "c1", "user", "Pregunta del chat uno"
    )
    assistant_message = service.append_message(
        "c1", "assistant", "Respuesta exclusiva del chat uno"
    )
    window.on_reply(
        {
            "request_id": request_id,
            "conversation_id": "c1",
            "result": {
                "message": assistant_message["content"],
                "user_message": user_message,
                "assistant_message": assistant_message,
            },
        }
    )

    assert window.current_conversation_id == "c2"
    assert "Respuesta exclusiva del chat uno" not in window.transcript.toPlainText()
    assert request_id not in window.pending_requests

    select_conversation(window, "c1")
    assert "Respuesta exclusiva del chat uno" in window.transcript.toPlainText()


def test_sending_without_a_selection_never_creates_a_conversation(app):
    del app
    service = FakeConversationService()
    service.conversations = []
    service.messages = {}
    bridge = FakeBridge()
    window = ChatWindow(service, bridge)
    try:
        assert service.create_calls == 0
        assert window.current_conversation_id is None
        assert window.conversation_list.count() == 0
        assert not window.send_button.isEnabled()
        assert "+ Nueva" in window.input.placeholderText()

        request_id = window.submit_quick_message("No abras otro chat")

        assert request_id is None
        assert bridge.calls == []
        assert service.create_calls == 0
        assert window.current_conversation_id is None
        assert "Pulsa «+ Nueva»" in window.transcript.toPlainText()

        window.input.setText("Conserva este borrador")
        window.pending_attachments = [
            {"attachment_id": "pending-file", "name": "pendiente.txt"}
        ]
        window.send()

        assert window.input.text() == "Conserva este borrador"
        assert window.pending_attachments == [
            {"attachment_id": "pending-file", "name": "pendiente.txt"}
        ]
        assert bridge.calls == []
        assert service.create_calls == 0

        window.new_conversation(title="Creado expresamente")

        assert service.create_calls == 1
        assert window.current_conversation_id is not None
        assert window.conversation_title.text() == "Creado expresamente"
    finally:
        window.close()


def test_deleting_the_last_desktop_chat_leaves_an_empty_history(
    app, monkeypatch
):
    del app
    service = FakeConversationService()
    service.conversations = [service.conversations[0]]
    service.messages = {"c1": service.messages["c1"]}
    bridge = FakeBridge()
    window = ChatWindow(service, bridge)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        window.delete_current_conversation()

        assert service.conversations == []
        assert service.create_calls == 0
        assert window.current_conversation_id is None
        assert window.conversation_list.count() == 0
        assert not window.send_button.isEnabled()
        assert "+ Nueva" in window.input.placeholderText()
    finally:
        window.close()


def test_remote_event_refreshes_only_its_canonical_conversation(
    conversation_window,
):
    window, service, _ = conversation_window
    select_conversation(window, "c1")
    service.append_message("c2", "assistant", "Respuesta enviada desde el móvil")

    window.handle_service_event(
        {
            "type": "speech",
            "conversation_id": "c2",
            "origin": "api",
        }
    )

    assert window.current_conversation_id == "c1"
    assert "Respuesta enviada desde el móvil" not in window.transcript.toPlainText()
    select_conversation(window, "c2")
    assert "Respuesta enviada desde el móvil" in window.transcript.toPlainText()


def test_historical_attachment_names_are_visible(conversation_window):
    window, service, _ = conversation_window
    service.messages["c1"][0]["attachments"] = [
        {
            "id": "stored-file",
            "name": "**captura**[abrir](https://attacker.test).png",
        }
    ]

    select_conversation(window, "c1")
    window.load_conversation_messages()

    assert (
        "**captura**[abrir](https://attacker.test).png"
        in window.transcript.toPlainText()
    )
    assert (
        'href="https://attacker.test'
        not in window.transcript.document().toHtml()
    )


def test_authorization_result_stays_with_its_origin_conversation(
    conversation_window,
):
    window, _, _ = conversation_window
    select_conversation(window, "c1")
    window.request_authorization(
        "challenge-c1",
        "Acción del chat uno",
        True,
        auto_prompt=False,
        conversation_id="c1",
    )
    select_conversation(window, "c2")

    window.on_authorization_result(
        SimpleNamespace(
            requires_authorization=False,
            message="Acción completada en el chat uno",
        )
    )

    assert window.current_conversation_id == "c2"
    assert "Acción completada en el chat uno" not in window.transcript.toPlainText()


def test_drafts_and_pending_attachments_do_not_leak_between_conversations(
    conversation_window,
):
    window, service, _ = conversation_window
    select_conversation(window, "c1")
    window.input.setText("borrador privado")
    window.pending_attachments = [
        {"attachment_id": "attachment-c1", "name": "uno.txt"}
    ]
    window._refresh_attachments()

    select_conversation(window, "c2")
    assert window.input.text() == ""
    assert window.pending_attachments == []

    select_conversation(window, "c1")
    assert window.input.text() == "borrador privado"
    assert window.pending_attachments[0]["attachment_id"] == "attachment-c1"

    window.close()
    assert "attachment-c1" in service.attachments.discarded


def test_transcript_renders_common_markdown_without_storing_html(
    conversation_window,
):
    window, _, _ = conversation_window
    window.transcript.clear()
    window.append(
        "Arfoxia",
        (
            "# Resumen\n\n"
            "**Importante**, *suave*, ~~antiguo~~ y `codigo`.\n\n"
            "- uno\n- dos\n\n"
            "| Campo | Valor |\n| --- | --- |\n| estado | bien |\n\n"
            "```txt\n<etiqueta>&dato\n```"
        ),
    )

    plain = window.transcript.toPlainText()
    assert "# Resumen" not in plain
    assert "**Importante**" not in plain
    assert "Importante" in plain
    assert "estado" in plain
    assert "<etiqueta>&dato" in plain
    important = window.transcript.document().find("Importante")
    assert important.charFormat().fontWeight() >= QFont.Weight.Bold


def test_transcript_disables_html_unsafe_links_and_image_resources(
    conversation_window,
):
    window, _, _ = conversation_window
    window.transcript.clear()
    window.append(
        "<img src=x onerror=alert(1)>",
        (
            "[seguro](https://example.com/informe) "
            "[js](javascript:alert(1)) "
            "[archivo](file:///C:/Windows/win.ini) "
            "[credenciales](https://user:pass@example.com)\n\n"
            "<script>alert('no')</script>\n\n"
            "![rastreador](https://attacker.test/pixel.gif)"
        ),
    )

    document_html = window.transcript.document().toHtml().casefold()
    assert "<script" not in document_html
    assert "javascript:" not in document_html
    assert "file:///" not in document_html
    assert "user:pass@" not in document_html
    assert "https://example.com/informe" in document_html
    assert "<img src=x onerror=alert(1)>" in window.transcript.toPlainText()

    blocked = window.transcript.loadResource(
        QTextDocument.ResourceType.ImageResource,
        QUrl("https://attacker.test/pixel.gif"),
    )
    assert isinstance(blocked, QImage)
    assert blocked.isNull()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/report", True),
        ("http://example.com/report", False),
        ("javascript:alert(1)", False),
        ("data:text/html,payload", False),
        ("file:///C:/Windows/win.ini", False),
        ("/api/state", False),
        ("https://user:pass@example.com/report", False),
        ("https://example.com/\nreport", False),
    ],
)
def test_external_chat_url_validation(url, expected):
    assert is_safe_https_url(url) is expected


def test_only_safe_markdown_links_are_opened(
    conversation_window,
    monkeypatch,
):
    window, _, _ = conversation_window
    opened: list[str] = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )

    window._open_markdown_link(QUrl("file:///C:/Windows/win.ini"))
    window._open_markdown_link(QUrl("https://user:pass@example.com/report"))
    window._open_markdown_link(QUrl("https://example.com/report"))

    assert opened == ["https://example.com/report"]


def test_short_speech_bubble_keeps_html_as_plain_text(app):
    del app
    bubble = SpeechBubble()
    try:
        payload = "<b>sin formato</b>"
        bubble.show_message(payload, 2200)
        assert bubble.label.textFormat() == Qt.TextFormat.PlainText
        assert bubble.label.text() == payload
    finally:
        bubble.close()


def test_markdown_browser_type_is_used(conversation_window):
    window, _, _ = conversation_window
    assert isinstance(window.transcript, SafeMarkdownBrowser)
