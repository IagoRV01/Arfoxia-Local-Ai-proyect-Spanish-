import asyncio
import json
import os
from queue import Queue
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from glaceon_companion.actions import ActionDispatcher
from glaceon_companion.api import create_api
from glaceon_companion.config import CompanionConfig, ConfigStore, PROJECT_ROOT
from glaceon_companion.database import Database
from glaceon_companion.ollama_client import OllamaClient
from glaceon_companion.pc_commands import validate_command, run_command, MAX_OUTPUT_BYTES
from glaceon_companion.services import CompanionService


@pytest.mark.parametrize("args", [{}, {"command": ""}, {"command": "x\0"},
    {"command": "x", "timeout_seconds": True}, {"command": "x", "timeout_seconds": 121},
    {"command": "x", "working_directory": "relative"}, {"command": "x", "admin": True}])
def test_invalid_command_is_rejected(args):
    with pytest.raises(ValueError):
        validate_command(args)


def test_command_disabled_by_default_even_after_validated_dispatch(tmp_path, monkeypatch):
    dispatcher = ActionDispatcher(CompanionConfig(), Database(tmp_path / "test.db"), tmp_path, Queue())
    monkeypatch.setattr("glaceon_companion.actions.run_command", lambda _: pytest.fail("Must not run"))
    result = dispatcher.execute_validated("run_powershell", {"command": "Get-Date"})
    assert not result.success
    assert "desactivado" in result.message


def test_passwordless_is_local_policy_and_does_not_remove_api_auth(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path)
    config = store.load()
    config.require_action_password = False
    config.pc_command_enabled = True
    service = CompanionService(store, config)
    executed = []
    monkeypatch.setattr("glaceon_companion.actions.run_command", lambda args:
        executed.append(args) or {"exit_code": 0, "stdout": "OK", "timed_out": False})
    app = create_api(service, "test-token", PROJECT_ROOT / "src/glaceon_companion/static")
    try:
        with TestClient(app) as client:
            body = {"action": "run_powershell", "arguments": {"command": "Write-Output 'OK'"}}
            assert client.post("/api/action", json=body).status_code == 401
            assert not executed
            response = client.post("/api/action", json=body, headers={"Authorization": "Bearer test-token"})
            assert response.status_code == 200
            assert response.json()["success"]
            assert not response.json()["requires_authorization"]
            assert len(executed) == 1
            invalid = client.post("/api/action", json={"action": "power", "arguments": {"operation": "bad"}},
                                  headers={"Authorization": "Bearer test-token"})
            assert not invalid.json()["success"]
    finally:
        service.close()


def test_default_password_policy_is_preserved_for_command(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path)
    config = store.load()
    config.pc_command_enabled = True
    service = CompanionService(store, config)
    monkeypatch.setattr("glaceon_companion.actions.run_command", lambda _: pytest.fail("Must not run"))
    try:
        result = service.execute_action("run_powershell", {"command": "Get-Date"})
        assert result.requires_authorization
        assert not result.success
    finally:
        service.close()


def test_command_audit_does_not_store_script():
    args = ActionDispatcher._redact_arguments("run_powershell", {"command": "private script"})
    assert "private script" not in json.dumps(args)
    assert args["command"]["redacted"] is True


@pytest.mark.parametrize("enabled", [False, True])
def test_tools_sent_to_model_match_local_permission_policy(monkeypatch, enabled):
    config = CompanionConfig(pc_command_enabled=enabled, require_action_password=not enabled)
    client = OllamaClient(config)
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "OK"}})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    asyncio.run(client.chat([{"role": "user", "content": "Hola"}], "bien", selection=client._fixed_small_selection()))
    names = {tool["function"]["name"] for tool in requests[0]["tools"]}
    assert ("run_powershell" in names) is enabled
    if enabled:
        assert "sin contraseña de Arfoxia" in requests[0]["messages"][0]["content"]


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_real_command_unicode_exit_status_and_bounded_output(tmp_path):
    result = run_command({"command": "Write-Output 'Arfoxia: ñ❄'; Write-Output ('x' * 30000)",
                          "working_directory": str(tmp_path)})
    assert result["exit_code"] == 0
    assert "ñ❄" in result["stdout"]
    assert result["truncated"]
    assert len(result["stdout"].encode("utf-8")) <= MAX_OUTPUT_BYTES
    failed = run_command({"command": "Write-Output 'fallo'; exit 7"})
    assert failed["exit_code"] == 7


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_real_command_timeout_kills_its_own_process():
    result = run_command({"command": "Start-Sleep -Seconds 30", "timeout_seconds": 1})
    assert result["timed_out"]


def test_service_close_keeps_dual_model_resident(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    stop = Mock()
    service.ollama.dual.stop_sync = stop
    service.ollama.requested_mode = "dual"
    service.close()
    stop.assert_not_called()
