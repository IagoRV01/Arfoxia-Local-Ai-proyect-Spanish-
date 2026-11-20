import json
from concurrent.futures import ThreadPoolExecutor
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from glaceon_companion import remote_system_agent as agent
from glaceon_companion.api import create_api
from glaceon_companion.config import ConfigStore, PROJECT_ROOT
from glaceon_companion.remote_system import RemoteSystemMonitor
from glaceon_companion.services import CompanionService


def monitor(alias="test-bc250", clock=lambda: 0):
    return RemoteSystemMonitor(SimpleNamespace(devices={"bc250": {"ssh_alias": alias}}), clock)


def payload():
    return {"success": True, "status": {"hostname": "bazzite", "memory_total_gb": 7.47,
            "cpu_percent": 7, "gpus": [{"name": "AMD BC-250", "temperature_c": 65}]}}


def mock_run(monkeypatch, response=None):
    calls = []
    monkeypatch.setattr("glaceon_companion.remote_system.shutil.which", lambda _: "ssh.exe")
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(response or payload()))
    monkeypatch.setattr("glaceon_companion.remote_system.subprocess.run", run)
    return calls


def test_read_only_strict_ssh_cached_and_no_tunnels(monkeypatch):
    calls = mock_run(monkeypatch)
    now = [1]
    reader = monitor(clock=lambda: now[0])
    reply = reader.status()
    assert reply["online"] and reply["sampled_at"]
    reply["status"]["hostname"] = "changed"
    assert reader.status()["status"]["hostname"] == "bazzite"
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[-2] == "test-bc250"
    for option in ("BatchMode=yes", "StrictHostKeyChecking=yes", "ClearAllForwardings=yes", "ConnectTimeout=6"):
        assert option in command
    assert not any(flag in command for flag in ("-L", "-R", "-D"))
    assert kwargs["shell"] is False and kwargs["timeout"] == 12
    assert kwargs["stdin"] == subprocess.DEVNULL
    now[0] = 17
    reader.status()
    assert len(calls) == 2


def test_concurrent_clients_share_one_ssh_sample(monkeypatch):
    calls = mock_run(monkeypatch)
    reader = monitor()
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(lambda _: reader.status(), range(16)))
    assert all(reply["online"] for reply in replies)
    assert len(calls) == 1


@pytest.mark.parametrize("alias", ["-oProxyCommand=bad", "pc;touch bad", "pc/../bad", None])
def test_bad_alias_never_connects(alias, monkeypatch):
    calls = mock_run(monkeypatch)
    result = monitor(alias).status()
    assert not result["online"] and result["status"] is None
    assert not calls


def test_unconfigured_never_connects(monkeypatch):
    calls = mock_run(monkeypatch)
    assert RemoteSystemMonitor(None).status()["configured"] is False
    assert not calls


@pytest.mark.parametrize("raw,code", [("private-secret", 255), ("[]", 0), ('{"success":true}', 0),
                                     ('{"success":1,"status":{}}', 0), ("x" * 65537, 0)],
                         ids=["ssh-error", "array", "missing-status", "invalid-success", "oversize"])
def test_failure_private_and_cached(monkeypatch, raw, code):
    mock_run(monkeypatch)
    calls = []
    def run(*a, **kw):
        calls.append(1)
        return SimpleNamespace(returncode=code, stdout=raw, stderr="private-secret")
    monkeypatch.setattr("glaceon_companion.remote_system.subprocess.run", run)
    reader = monitor()
    result = reader.status()
    assert result["status"] is None and not result["online"]
    assert "private-secret" not in json.dumps(result)
    reader.status()
    assert len(calls) == 1


def test_timeout_clears_previous_live_snapshot(monkeypatch):
    mock_run(monkeypatch)
    now = [0]
    reader = monitor(clock=lambda: now[0])
    assert reader.status()["online"]
    now[0] = 20
    def fail(*a, **kw):
        raise subprocess.TimeoutExpired("ssh", 12)
    monkeypatch.setattr("glaceon_companion.remote_system.subprocess.run", fail)
    result = reader.status()
    assert not result["online"] and result["status"] is None and result["sampled_at"] is None


def test_status_whitelist_finite_numbers_and_missing_not_zero(monkeypatch):
    data = payload()
    marker = "never-return"
    data["status"].update(password=marker, cpu_percent=float("nan"), memory_used_gb=True)
    data["status"]["gpus"][0]["soc_power_w"] = -1
    mock_run(monkeypatch, data)
    result = monitor().status()["status"]
    assert "password" not in result
    assert result["cpu_percent"] is None and result["memory_used_gb"] is None
    assert result["gpus"][0]["utilization_percent"] is None
    assert result["gpus"][0]["soc_power_w"] is None


def put(root, filename, value):
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_linux_collector_reads_units_cpu_delta_and_filters_connectors(tmp_path):
    proc, sys, etc = (tmp_path / name for name in ("proc", "sys", "etc"))
    put(proc, "stat", "cpu 100 0 100 800 0 0 0 0 0 0")
    put(proc, "meminfo", "MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\n")
    put(proc, "cpuinfo", "processor : 0\nmodel name : AMD BC-250\nprocessor : 1\n")
    put(proc, "uptime", "3600.0 100")
    put(etc, "os-release", 'PRETTY_NAME="Bazzite"')
    device = sys / "class/drm/card1/device"
    put(device, "vendor", "0x1002")
    put(device, "gpu_busy_percent", "35")
    put(device, "mem_info_vram_used", str(1024**3))
    put(device, "mem_info_vram_total", str(8 * 1024**3))
    put(device, "hwmon/hwmon1/temp1_input", "64000")
    put(device, "hwmon/hwmon1/power1_average", "44120000")
    put(sys, "class/drm/card1-HDMI-A-1/device/vendor", "0x1002")
    put(sys, "class/hwmon/hwmon0/name", "k10temp")
    put(sys, "class/hwmon/hwmon0/temp1_input", "65000")
    def sleep(_):
        put(proc, "stat", "cpu 110 0 110 880 0 0 0 0 0 0")
    result = agent.collect(proc, sys, etc, sleep, disk_path=tmp_path)
    assert result["cpu_percent"] == 20
    assert result["memory_total_gb"] == 8 and result["memory_percent"] == 50
    assert result["cpu_logical_cores"] == 2 and result["cpu_temperature_c"] == 65
    assert result["disk_path"] == str(tmp_path)
    assert len(result["gpus"]) == 1
    assert result["gpus"][0] == {"name": "AMD BC-250 · card1", "utilization_percent": 35,
        "memory_used_mb": 1024, "memory_total_mb": 8192, "temperature_c": 64, "soc_power_w": 44.12}
    (device / "gpu_busy_percent").unlink()
    assert agent.collect(proc, sys, etc, lambda _: None, disk_path=tmp_path)["gpus"][0]["utilization_percent"] is None


def test_bc250_endpoint_auth_no_store_and_fixed_target(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    expected = {"target": "bc250", "online": False, "status": None}
    calls = []
    monkeypatch.setattr(service.bc250_monitor, "status", lambda: (calls.append(1) or expected))
    try:
        with TestClient(create_api(service, "test-token", PROJECT_ROOT / "src/glaceon_companion/static")) as client:
            assert client.get("/api/pc/bc250").status_code == 401
            assert not calls
            reply = client.get("/api/pc/bc250?target=untrusted&host=evil", headers={"Authorization": "Bearer test-token"})
            assert reply.status_code == 200 and reply.json() == expected
            assert reply.headers["cache-control"] == "no-store"
            assert len(calls) == 1
    finally:
        service.close()
