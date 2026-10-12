import subprocess
import json

import pytest
from fastapi.testclient import TestClient

from glaceon_companion.api import create_api
from glaceon_companion.config import ConfigStore, PROJECT_ROOT
from glaceon_companion.services import CompanionService
from glaceon_companion.travel import TravelManager


def manager(tmp_path):
    now = [100.0]
    travel = TravelManager(tmp_path, 8742, clock=lambda: now[0])
    token = travel.register("linux", "Linux", "pc2")
    return travel, now, token


def test_arrival_requires_painted_ready_then_disconnect_returns_home(tmp_path):
    travel, now, token = manager(tmp_path)
    travel.select("linux", connect=False)
    assert travel.snapshot()["active"] == "home"
    assert travel.heartbeat("linux", False)["requested"]
    assert travel.snapshot()["active"] == "home"
    assert travel.heartbeat("linux", True)["active"]
    now[0] += 9
    assert travel.snapshot()["active"] == "home"
    assert "Conexión perdida" in travel.snapshot()["error"]
    assert not travel.heartbeat("linux", True)["active"]
    assert travel.authenticate(token) == "linux"


def test_manual_return_stale_heartbeats_cannot_resurrect(tmp_path):
    travel, _, _ = manager(tmp_path)
    travel.select("linux", connect=False)
    travel.heartbeat("linux", True)
    generation = travel.snapshot()["generation"]
    travel.home()
    assert not travel.heartbeat("linux", True)["active"]
    assert travel.snapshot()["generation"] > generation


def test_pending_timeout_and_client_losing_display(tmp_path):
    travel, now, _ = manager(tmp_path)
    travel.select("linux", connect=False)
    now[0] += 21
    assert not travel.heartbeat("linux", True)["active"]
    travel.select("linux", connect=False)
    travel.heartbeat("linux", True)
    travel.heartbeat("linux", False)
    assert travel.snapshot()["active"] == "home"


def test_secret_rotation_persistence_and_never_public_snapshot(tmp_path):
    travel, _, old = manager(tmp_path)
    secret = travel.register("linux", "BC250", "pc2")
    assert travel.authenticate(old) is None
    restored = TravelManager(tmp_path, 8742)
    assert restored.authenticate(secret) == "linux"
    assert secret not in str(restored.snapshot())
    assert "secret" not in str(restored.snapshot())
    assert restored.snapshot()["active"] == "home"


def test_reserved_device_and_corrupt_registry_preserve_app_and_file(tmp_path):
    travel, _, _ = manager(tmp_path)
    with pytest.raises(ValueError):
        travel.register("home", "Another home", "pc2")
    travel.path.write_text("broken-json", encoding="utf-8")
    restored = TravelManager(tmp_path, 8742)
    assert restored.snapshot()["active"] == "home"
    assert restored.snapshot()["devices"] == []
    assert "original" in restored.snapshot()["error"]
    assert travel.path.read_text() == "broken-json"


@pytest.mark.parametrize("alias", ["-oProxyCommand=calc", "pc2; reboot", "pc2\nother", "user@host", ""])
def test_ssh_alias_rejects_options_or_shell_injection(tmp_path, alias):
    travel, _, _ = manager(tmp_path)
    with pytest.raises(ValueError):
        travel.register("linux", "Linux", alias)


def test_ssh_uses_known_hosts_keys_and_loopback_only(tmp_path, monkeypatch):
    travel, _, _ = manager(tmp_path)
    captured = []
    class Process:
        def poll(self): return None
        def terminate(self): captured.append("terminated")
    monkeypatch.setattr("glaceon_companion.travel.shutil.which", lambda _: "ssh.exe")
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: captured.append(args) or Process())
    travel.select("linux")
    command = captured[0]
    assert "StrictHostKeyChecking=yes" in command
    assert "BatchMode=yes" in command
    assert "127.0.0.1:18842:127.0.0.1:8742" in command
    assert command[-2] == "pc2"
    travel.close()
    assert captured[-1] == "terminated"


@pytest.mark.parametrize("mismatch", [None, "created", "command", "name"])
def test_restore_only_identity_checked_owned_tunnel(tmp_path, monkeypatch, mismatch):
    travel, _, _ = manager(tmp_path)
    travel.tunnel_path.write_text(json.dumps([{"device_id": "linux", "pid": 123, "created": 50.0}]))
    class Process:
        pid = 123
        def create_time(self): return 51.0 if mismatch == "created" else 50.0
        def cmdline(self): return ["ssh", "unrelated"] if mismatch == "command" else ["ssh", *travel._connection_args("linux")]
        def name(self): return "other.exe" if mismatch == "name" else "ssh.exe"
        def is_running(self): return True
    monkeypatch.setattr("glaceon_companion.travel.psutil.Process", lambda _: Process())
    restored = TravelManager(tmp_path, 8742)
    assert ("linux" in restored.tunnels) == (mismatch is None)
    assert restored.snapshot()["active"] == "home"


def test_client_cannot_use_owner_actions_chat_or_register(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    app = create_api(service, "owner", PROJECT_ROOT / "src/glaceon_companion/static")
    try:
        with TestClient(app) as client:
            assert client.get("/api/travel").status_code == 401
            owner = {"Authorization": "Bearer owner"}
            result = client.post("/api/travel/register", headers=owner,
                json={"device_id": "linux", "label": "Linux", "ssh_alias": "pc2"})
            assert result.status_code == 200
            headers = {"Authorization": "Bearer " + result.json()["client_token"]}
            for path in ("/api/action", "/api/chat", "/api/travel/register"):
                assert client.post(path, headers=headers, json={}).status_code == 401
            assert client.get("/api/state", headers=headers).status_code == 401
            assert client.post("/api/travel/client/heartbeat", headers=owner, json={"ready": True}).status_code == 401
            service.travel.select("linux", connect=False)
            pending = client.post("/api/travel/client/heartbeat", headers=headers, json={"ready": False}).json()
            assert pending["requested"] and not pending["active"]
            response = client.post("/api/travel/client/heartbeat", headers=headers, json={"ready": True})
            assert response.json()["active"]
            assert set(response.json()["pet"]) <= {"name", "energy", "asleep", "seated", "hunger", "happiness"}
            assert client.post("/api/travel/client/interact", headers=headers, json={"kind": "run_powershell"}).status_code == 422
            assert client.post("/api/travel/client/interact", headers=headers, json={"kind": "sit"}).status_code == 200
            assert client.post("/api/travel/client/return", headers=headers).status_code == 200
            assert service.travel.snapshot()["active"] == "home"
            assert client.post("/api/travel/client/interact", headers=headers, json={"kind": "wake"}).status_code == 409
            service.travel.select("linux", connect=False)
            assert client.post("/api/travel/client/return", headers=headers).status_code == 200
            assert service.travel.snapshot()["pending"] is None
            assert not service.travel.heartbeat("linux", True)["active"]
    finally:
        service.close()
