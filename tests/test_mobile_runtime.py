from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from glaceon_companion.mobile_runtime import MobileRuntimeManager


class FakeProcess:
    def __init__(self) -> None:
        self.return_code: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9

    def wait(self, timeout: float | None = None) -> int:
        assert timeout is not None
        return self.return_code or 0


def runtime_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    mobile = tmp_path / "mobile"
    expo_cli = mobile / "node_modules" / "expo" / "bin" / "cli"
    expo_cli.parent.mkdir(parents=True)
    expo_cli.write_text("// expo", encoding="utf-8")
    node = tmp_path / "node.exe"
    node.write_bytes(b"node")
    return mobile, expo_cli, node


def test_starts_expo_with_private_tailscale_hostname(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPO_OFFLINE", "1")
    mobile, expo_cli, node = runtime_files(tmp_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    process = FakeProcess()

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        calls.append((command, kwargs))
        return process

    manager = MobileRuntimeManager(
        mobile,
        tmp_path / "data",
        node_executable=node,
        popen_factory=fake_popen,
    )
    monkeypatch.setattr(manager, "_metro_running", lambda: False)
    monkeypatch.setattr(manager, "_port_open", lambda: False)
    monkeypatch.setattr(
        manager,
        "_tailscale_host",
        lambda: "pciagorv.tail122075.ts.net",
    )

    manager._ensure_started_once()

    assert len(calls) == 1
    command, options = calls[0]
    assert command == [
        str(node.resolve()),
        str(expo_cli),
        "start",
        "--go",
        "--port",
        "8081",
        "--max-workers",
        "2",
    ]
    assert options["cwd"] == str(mobile.resolve())
    assert "EXPO_OFFLINE" not in options["env"]
    assert options["env"]["REACT_NATIVE_PACKAGER_HOSTNAME"] == (
        "pciagorv.tail122075.ts.net"
    )
    assert options["shell"] is False
    assert options["stdin"] is subprocess.DEVNULL

    manager._ensure_started_once()
    assert len(calls) == 1
    manager.stop()
    assert process.terminated is True


def test_waits_for_tailscale_instead_of_advertising_lan_address(
    tmp_path,
    monkeypatch,
):
    mobile, _, node = runtime_files(tmp_path)
    calls: list[list[str]] = []
    manager = MobileRuntimeManager(
        mobile,
        tmp_path / "data",
        node_executable=node,
        popen_factory=lambda command, **_: calls.append(command),
    )
    monkeypatch.setattr(manager, "_metro_running", lambda: False)
    monkeypatch.setattr(manager, "_port_open", lambda: False)
    monkeypatch.setattr(manager, "_tailscale_host", lambda: None)

    manager._ensure_started_once()

    assert calls == []
    assert "Esperando a que Tailscale" in manager.log_path.read_text(
        encoding="utf-8"
    )


def test_does_not_duplicate_an_existing_metro_server(tmp_path, monkeypatch):
    mobile, _, node = runtime_files(tmp_path)
    calls: list[list[str]] = []
    manager = MobileRuntimeManager(
        mobile,
        tmp_path / "data",
        node_executable=node,
        popen_factory=lambda command, **_: calls.append(command),
    )
    monkeypatch.setattr(manager, "_metro_running", lambda: True)

    manager._ensure_started_once()

    assert calls == []


def test_restarts_an_owned_process_after_it_exits(tmp_path, monkeypatch):
    mobile, _, node = runtime_files(tmp_path)
    processes = [FakeProcess(), FakeProcess()]
    calls: list[list[str]] = []
    now = [100.0]

    def fake_popen(command: list[str], **_: Any) -> FakeProcess:
        calls.append(command)
        return processes[len(calls) - 1]

    manager = MobileRuntimeManager(
        mobile,
        tmp_path / "data",
        node_executable=node,
        popen_factory=fake_popen,
        clock=lambda: now[0],
    )
    monkeypatch.setattr(manager, "_metro_running", lambda: False)
    monkeypatch.setattr(manager, "_port_open", lambda: False)
    monkeypatch.setattr(manager, "_tailscale_host", lambda: "pc.tail.test")

    manager._ensure_started_once()
    processes[0].return_code = 1
    manager._ensure_started_once()
    assert len(calls) == 1
    now[0] += 10.0
    manager._ensure_started_once()

    assert len(calls) == 2
    manager.stop()


def test_requires_repeated_health_failures_before_restarting_owned_metro(
    tmp_path,
    monkeypatch,
):
    mobile, _, node = runtime_files(tmp_path)
    processes = [FakeProcess(), FakeProcess()]
    calls: list[list[str]] = []
    now = [100.0]

    def fake_popen(command: list[str], **_: Any) -> FakeProcess:
        calls.append(command)
        return processes[len(calls) - 1]

    manager = MobileRuntimeManager(
        mobile,
        tmp_path / "data",
        node_executable=node,
        preferred_host="pc.tail.test",
        popen_factory=fake_popen,
        clock=lambda: now[0],
    )
    monkeypatch.setattr(manager, "_metro_running", lambda: False)
    monkeypatch.setattr(manager, "_port_open", lambda: False)

    manager._ensure_started_once()
    now[0] += 91.0
    for _ in range(11):
        manager._ensure_started_once()
    assert len(calls) == 1
    assert processes[0].terminated is False

    manager._ensure_started_once()
    assert processes[0].terminated is True
    assert len(calls) == 1
    now[0] += 10.0
    manager._ensure_started_once()
    assert len(calls) == 2
    manager.stop()


def test_prefers_magicdns_and_falls_back_to_tailscale_ipv4(tmp_path):
    mobile, _, node = runtime_files(tmp_path)
    tailscale = tmp_path / "tailscale.exe"
    tailscale.write_bytes(b"tailscale")
    results = [
        subprocess.CompletedProcess(
            ["tailscale", "status"],
            0,
            stdout=json.dumps(
                {
                    "BackendState": "Running",
                    "Self": {"DNSName": "pc.tail.example."},
                }
            ),
            stderr="",
        )
    ]
    manager = MobileRuntimeManager(
        mobile,
        tmp_path / "data",
        node_executable=node,
        tailscale_executable=tailscale,
        run_command=lambda *_, **__: results.pop(0),
    )

    assert manager._tailscale_host() == "pc.tail.example"

    fallback_results = [
        subprocess.CompletedProcess(
            ["tailscale", "status"],
            0,
            stdout=json.dumps({"BackendState": "Running", "Self": {}}),
            stderr="",
        ),
        subprocess.CompletedProcess(
            ["tailscale", "ip"],
            0,
            stdout="100.96.94.52\n",
            stderr="",
        ),
    ]
    fallback = MobileRuntimeManager(
        mobile,
        tmp_path / "data-fallback",
        node_executable=node,
        tailscale_executable=tailscale,
        run_command=lambda *_, **__: fallback_results.pop(0),
    )

    assert fallback._tailscale_host() == "100.96.94.52"


def test_uses_configured_magicdns_without_waiting_for_tailscale(tmp_path):
    mobile, _, node = runtime_files(tmp_path)
    manager = MobileRuntimeManager(
        mobile,
        tmp_path / "data",
        node_executable=node,
        preferred_host="pciagorv.tail122075.ts.net",
        run_command=lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("Tailscale must not be queried for a configured host")
        ),
    )

    assert manager._tailscale_host() == "pciagorv.tail122075.ts.net"
