from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from glaceon_companion.config import ConfigStore
from glaceon_companion.services import CompanionService
from glaceon_companion.ui import AuthorizationDialog, Bridge, ChatWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_first_sensitive_action_is_configured_and_authorized_only_in_local_dialog(
    app, tmp_path, monkeypatch
):
    del app
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    bridge = Bridge(service)
    window = ChatWindow(service, bridge)
    document = tmp_path / "authorized.txt"
    password = "ui-test-passphrase"
    proposed = service.execute_action(
        "file_operation",
        {
            "operation": "write_text",
            "path": str(document),
            "content": "hecho",
        },
    )
    monkeypatch.setattr(
        AuthorizationDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(AuthorizationDialog, "take_password", lambda self: password)
    monkeypatch.setattr(
        bridge,
        "authorize",
        lambda challenge_id, candidate: window.on_authorization_result(
            service.authorize_action(challenge_id, candidate)
        ),
    )
    window.pending_authorization = {
        "challenge_id": proposed.challenge_id,
        "summary": proposed.authorization_summary,
        "configured": False,
    }

    try:
        window.authorize_pending()
        assert service.authorization.is_configured
        assert document.read_text(encoding="utf-8") == "hecho"
        assert window.pending_authorization is None
    finally:
        window.close()
        bridge.shutdown()
        service.close()


def test_authorization_requests_are_processed_fifo_without_overwrite(
    app, tmp_path, monkeypatch
):
    del app
    store = ConfigStore(tmp_path / "app-data")
    service = CompanionService(store, store.load())
    service.authorization.configure("queue-test-passphrase")
    bridge = Bridge(service)
    window = ChatWindow(service, bridge)
    first_file = tmp_path / "first.txt"
    second_file = tmp_path / "second.txt"
    first = service.execute_action(
        "file_operation",
        {"operation": "write_text", "path": str(first_file), "content": "one"},
    )
    second = service.execute_action(
        "file_operation",
        {"operation": "write_text", "path": str(second_file), "content": "two"},
    )
    monkeypatch.setattr(
        AuthorizationDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(
        AuthorizationDialog,
        "take_password",
        lambda self: "queue-test-passphrase",
    )
    monkeypatch.setattr(
        bridge,
        "authorize",
        lambda challenge_id, candidate: window.on_authorization_result(
            service.authorize_action(challenge_id, candidate)
        ),
    )
    window.request_authorization(
        first.challenge_id, first.authorization_summary, True, auto_prompt=False
    )
    window.request_authorization(
        second.challenge_id, second.authorization_summary, True, auto_prompt=False
    )

    try:
        assert window.pending_authorization["challenge_id"] == first.challenge_id
        assert len(window.authorization_queue) == 1
        assert not window.input.isEnabled()

        window.authorize_pending()
        assert first_file.read_text(encoding="utf-8") == "one"
        assert not second_file.exists()
        assert window.pending_authorization["challenge_id"] == second.challenge_id

        window.authorize_pending()
        assert second_file.read_text(encoding="utf-8") == "two"
        assert window.pending_authorization is None
        assert not window.input.isEnabled()
        assert "+ Nueva" in window.input.placeholderText()
    finally:
        window.close()
        bridge.shutdown()
        service.close()
