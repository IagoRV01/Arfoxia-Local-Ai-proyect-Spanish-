from __future__ import annotations

import json
import os

import httpx
import pytest

from glaceon_companion.config import ConfigStore
from glaceon_companion.game_streaming import (
    GameStreamingError,
    GameStreamingManager,
    PairingRateLimitedError,
)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP status {self.status_code}")

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args) -> None:
        return None

    def post(self, path: str, **kwargs) -> FakeResponse:
        self.calls.append({"path": path, **kwargs})
        return self.responses.pop(0)

    def get(self, path: str, **kwargs) -> FakeResponse:
        self.calls.append({"path": path, **kwargs})
        return self.responses.pop(0)


class FailingClient:
    def __enter__(self) -> "FailingClient":
        return self

    def __exit__(self, *args) -> None:
        return None

    def post(self, _path: str, **_kwargs) -> FakeResponse:
        raise httpx.ReadTimeout("response lost")


def ready_manager(tmp_path, monkeypatch) -> tuple[GameStreamingManager, ConfigStore]:
    store = ConfigStore(tmp_path)
    config = store.load()
    manager = GameStreamingManager(config, store)
    executable = tmp_path / "sunshine.exe"
    executable.write_bytes(b"sunshine")
    state_file = tmp_path / "sunshine_state.json"
    monkeypatch.setattr(
        "glaceon_companion.game_streaming.SUNSHINE_EXECUTABLE",
        executable,
    )
    monkeypatch.setattr(
        "glaceon_companion.game_streaming.SUNSHINE_STATE_FILE",
        state_file,
    )
    monkeypatch.setattr(manager, "_service_status", lambda: "running")
    monkeypatch.setattr(manager, "_port_open", lambda _port: True)
    monkeypatch.setattr(manager, "_tailscale_ipv4", lambda: "100.64.0.2")
    monkeypatch.setattr(manager, "_vigembus_ready", lambda: True)
    monkeypatch.setattr(
        manager,
        "_sunshine_client_status",
        lambda credentials: (0, credentials is not None, []),
    )
    monkeypatch.setattr(
        manager,
        "_capture_gpu_label",
        lambda: "RTX de prueba de 8 GB (pantalla de juego)",
    )
    return manager, store


def test_secret_store_preserves_api_token_and_hides_sunshine_credentials(tmp_path):
    store = ConfigStore(tmp_path)
    token = store.api_token()
    store.save_sunshine_credentials("arfoxia", "very-private-password")

    assert store.api_token() == token
    assert store.sunshine_credentials() == ("arfoxia", "very-private-password")
    public = store.public_config(store.load())
    serialized = json.dumps(public).casefold()
    assert "very-private-password" not in serialized
    assert token.casefold() not in serialized
    if os.name == "nt":
        secret_file = store.secrets_path.read_text(encoding="utf-8")
        assert "very-private-password" not in secret_file
        assert "password_dpapi" in secret_file


def test_secret_store_fails_closed_when_acl_cannot_be_applied(
    tmp_path,
    monkeypatch,
):
    store = ConfigStore(tmp_path)
    monkeypatch.setattr(
        "glaceon_companion.auth.harden_authorization_file",
        lambda _path: False,
    )

    with pytest.raises(RuntimeError, match="proteger el nuevo almacén"):
        store.api_token()


def test_status_reports_the_private_host_without_returning_credentials(
    tmp_path,
    monkeypatch,
):
    manager, store = ready_manager(tmp_path, monkeypatch)
    store.save_sunshine_credentials("arfoxia", "do-not-return-me")

    status = manager.status()

    assert status["ready"] is True
    assert status["pairing_available"] is True
    assert status["host"] == "pciagorv.tail122075.ts.net"
    assert status["tailscale_ip"] == "100.64.0.2"
    assert status["gamepad_ready"] is True
    assert status["capture_gpu"] == "RTX de prueba de 8 GB (pantalla de juego)"
    assert "do-not-return-me" not in json.dumps(status)


def test_status_separates_local_sunshine_from_remote_tailscale_readiness(
    tmp_path,
    monkeypatch,
):
    manager, store = ready_manager(tmp_path, monkeypatch)
    store.save_sunshine_credentials("arfoxia", "private-password")
    monkeypatch.setattr(manager, "_tailscale_ipv4", lambda: "")

    status = manager.status()

    assert status["sunshine_ready"] is True
    assert status["remote_ready"] is False
    assert status["ready"] is False
    assert status["tailscale_ready"] is False
    assert status["pin_submission_available"] is True


def test_prepare_creates_random_sunshine_credentials_only_after_success(
    tmp_path,
    monkeypatch,
):
    manager, store = ready_manager(tmp_path, monkeypatch)
    client = FakeClient([FakeResponse({"status": True})])
    monkeypatch.setattr(manager, "_http_client", lambda: client)

    status = manager.prepare()

    assert status["ready"] is True
    assert status["credentials_managed"] is True
    assert client.calls[0]["path"] == "/api/password"
    body = client.calls[0]["json"]
    assert body["newUsername"] == "arfoxia"
    assert body["newPassword"] == body["confirmNewPassword"]
    assert len(body["newPassword"]) >= 32
    assert store.sunshine_credentials() == ("arfoxia", body["newPassword"])
    assert body["newPassword"] not in json.dumps(status)


def test_first_run_keeps_protected_credentials_if_sunshine_response_is_lost(
    tmp_path,
    monkeypatch,
):
    manager, store = ready_manager(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "_http_client", lambda: FailingClient())

    with pytest.raises(GameStreamingError, match="credenciales iniciales"):
        manager.prepare()

    credentials = store.sunshine_credentials()
    assert credentials is not None
    assert credentials[0] == "arfoxia"


def test_client_status_counts_only_enabled_sunshine_certificates(
    tmp_path,
    monkeypatch,
):
    store = ConfigStore(tmp_path)
    manager = GameStreamingManager(store.load(), store)
    client = FakeClient(
        [
            FakeResponse(
                {
                    "status": True,
                    "named_certs": [
                        {"name": "iPhone de Iago", "enabled": True},
                        {"name": "iPad antiguo", "enabled": False},
                        {"name": "Revocado", "revoked": True},
                    ],
                }
            )
        ]
    )
    monkeypatch.setattr(manager, "_http_client", lambda: client)

    count, verified, names = manager._sunshine_client_status(
        ("arfoxia", "private-password")
    )

    assert verified is True
    assert count == 1
    assert names == ["iPhone de Iago"]
    assert client.calls[0]["path"] == "/api/clients/list"


def test_pair_submits_only_a_four_digit_pin_to_the_loopback_bridge(
    tmp_path,
    monkeypatch,
):
    manager, store = ready_manager(tmp_path, monkeypatch)
    store.save_sunshine_credentials("arfoxia", "private-password")
    client = FakeClient([FakeResponse({"status": True})])
    monkeypatch.setattr(manager, "_http_client", lambda: client)
    monkeypatch.setattr(
        manager,
        "prepare",
        lambda: {"pin_submission_available": True, "ready": True},
    )
    monkeypatch.setattr(
        manager,
        "status",
        lambda: {
            "pin_submission_available": True,
            "ready": True,
            "paired": False,
        },
    )

    result = manager.pair("1234", "  iPhone   de Iago  ")

    assert result["paired"] is False
    assert result["message"].startswith("PIN enviado")
    assert client.calls[0]["path"] == "/api/pin"
    assert client.calls[0]["json"] == {
        "pin": "1234",
        "name": "iPhone de Iago",
    }
    assert client.calls[0]["auth"] is not None
    with pytest.raises(ValueError, match="4 cifras"):
        manager.pair("12ab")


def test_pairing_is_rate_limited_even_when_sunshine_accepts_requests(
    tmp_path,
    monkeypatch,
):
    manager, store = ready_manager(tmp_path, monkeypatch)
    store.save_sunshine_credentials("arfoxia", "private-password")
    client = FakeClient([FakeResponse({"status": True}) for _ in range(5)])
    monkeypatch.setattr(manager, "_http_client", lambda: client)
    monkeypatch.setattr(
        manager,
        "prepare",
        lambda: {"pin_submission_available": True, "ready": True},
    )
    monkeypatch.setattr(manager, "status", lambda: {"ready": True})

    for _ in range(5):
        manager.pair("1234")
    with pytest.raises(PairingRateLimitedError):
        manager.pair("1234")
