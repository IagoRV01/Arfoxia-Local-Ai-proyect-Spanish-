import asyncio
from types import SimpleNamespace

import pytest
import httpx

from glaceon_companion.config import CompanionConfig, ConfigStore
from glaceon_companion.ollama_client import OllamaClient
from glaceon_companion.services import CompanionService
from glaceon_companion.model_policy import RuntimeModel


@pytest.mark.parametrize("method", ["select_for_turn", "preload_power", "preload_gaming_gpu", "ensure_primary_server", "chat"])
def test_paused_client_cannot_load_or_generate(method):
    client = OllamaClient(CompanionConfig(local_ai_paused=True))
    with pytest.raises(RuntimeError, match="apagada"):
        asyncio.run(getattr(client, method)([], "bien") if method == "chat" else getattr(client, method)())


@pytest.fixture
def service(tmp_path):
    store = ConfigStore(tmp_path)
    config = CompanionConfig.defaults()
    store.save(config)
    instance = CompanionService(store, config)
    yield instance
    instance.close()


def test_release_stops_both_owned_servers_and_verifies_no_models(service):
    calls = []
    class Runtime:
        requested_mode = "dual"
        switching_to = None
        dual = SimpleNamespace(stop=lambda: record("dual"))
        stop_gaming_server = lambda self: record("gaming")
        def use_normal_mode(self):
            self.requested_mode = "normal"
        async def running_models(self):
            return () if "unload" in calls else (RuntimeModel("model:any", 100),)
        async def unload(self, name):
            assert name == "model:any"
            calls.append("unload")
    async def record(name):
        calls.append(name)
    service.ollama = Runtime()
    asyncio.run(service.unload_model())
    assert calls == ["dual", "gaming", "unload"]
    assert service.config.local_ai_paused
    assert service.ollama.requested_mode == "normal"


def test_shutdown_failure_keeps_pause_but_releases_locks(service):
    async def fail():
        raise OSError("unreachable")
    service.ollama = SimpleNamespace(running_models=fail, switching_to=None)
    with pytest.raises(RuntimeError, match="verificar"):
        asyncio.run(service.unload_model())
    assert service.config.local_ai_paused
    assert service.ollama.switching_to is None
    assert not service._turn_lock.locked()


def test_explicit_normal_reactivation_clears_saved_pause(service):
    class Runtime:
        requested_mode = "normal"
        switching_to = None
        def use_normal_mode(self):
            self.requested_mode = "normal"
        async def stop_gaming_server(self):
            pass
        async def unload(self, _):
            pass
        async def model_status(self):
            return {"requested_mode": self.requested_mode}
    service.ollama = Runtime()
    service.config.local_ai_paused = True
    result = asyncio.run(service.set_model_mode("normal"))
    assert result["ai_paused"] is False
    assert not service.store.load().local_ai_paused


def test_failed_activation_does_not_enable_paused_ai(service):
    service.config.local_ai_paused = True
    async def installed():
        return ()
    service.ollama = SimpleNamespace(requested_mode="normal", switching_to=None,
        use_normal_mode=lambda: None, stop_gaming_server=lambda: asyncio.sleep(0),
        installed_models=installed)
    with pytest.raises(RuntimeError, match="instalado"):
        asyncio.run(service.set_model_mode("power"))
    assert service.config.local_ai_paused
    assert service.store.load().local_ai_paused
    assert not service._turn_lock.locked()
    assert service.ollama.switching_to is None


def test_cancel_waiting_shutdown_keeps_pause_and_frees_switch_marker(service):
    async def run():
        service._turn_lock.acquire()
        try:
            task = asyncio.create_task(service.unload_model())
            await asyncio.sleep(0.01)
            assert service.config.local_ai_paused
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert service.ollama.switching_to is None
            assert service._turn_lock.locked()  # the active turn still owns it
        finally:
            service._turn_lock.release()
    asyncio.run(run())


def test_already_stopped_primary_counts_as_empty_only_for_verified_loopback(monkeypatch):
    client = OllamaClient(CompanionConfig())
    async def offline():
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(client, 'running_models', offline)
    monkeypatch.setattr(client, '_primary_server_stopped', lambda: True)
    assert asyncio.run(client.models_for_shutdown()) == ()
    monkeypatch.setattr(client, '_primary_server_stopped', lambda: False)
    with pytest.raises(RuntimeError, match='comprobar'):
        asyncio.run(client.models_for_shutdown())


def test_primary_activation_is_hidden_gpu_pinned_and_never_generates(monkeypatch):
    client = OllamaClient(CompanionConfig())
    calls, attempts = [], []
    async def installed():
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError('offline')
        if len(attempts) == 2:
            raise httpx.ReadError('HTTP listener still starting')
        return ('existing:model',)
    monkeypatch.setattr(client, 'installed_models', installed)
    monkeypatch.setattr(client, '_primary_server_stopped', lambda: True)
    monkeypatch.setattr(client, '_gaming_ollama_executable', lambda: 'verified-ollama.exe')
    monkeypatch.setattr('glaceon_companion.ollama_client.probe_nvidia_gpus', lambda **_: SimpleNamespace(available=True))
    monkeypatch.setattr('glaceon_companion.ollama_client.subprocess.Popen',
        lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(poll=lambda: None))
    asyncio.run(client.ensure_primary_server())
    command, options = calls[0]
    assert command == ['verified-ollama.exe', 'serve']
    assert options['env']['OLLAMA_HOST'] == 'http://127.0.0.1:11434'
    assert options['env']['CUDA_VISIBLE_DEVICES'] == client.config.ai_gpu_uuid
    assert options['shell'] is False
    assert options['creationflags'] != 0
    assert len(attempts) == 3


def test_custom_server_is_never_started_or_assumed_stopped():
    client = OllamaClient(CompanionConfig(ollama_url='http://127.0.0.1:9999'))
    assert not client._primary_server_stopped()


def test_closed_windows_port_has_enough_time_to_report_refusal(monkeypatch):
    client = OllamaClient(CompanionConfig())
    def refused(address, timeout):
        assert address == ('127.0.0.1', 11434)
        assert timeout >= 3  # WSAECONNREFUSED is delayed on Windows.
        raise ConnectionRefusedError(10061, 'closed')
    monkeypatch.setattr('glaceon_companion.ollama_client.socket.create_connection', refused)
    assert client._primary_server_stopped()


def test_primary_activation_reuses_healthy_server(monkeypatch):
    client = OllamaClient(CompanionConfig())
    monkeypatch.setattr(client, 'installed_models', lambda: asyncio.sleep(0, result=()))
    def unexpected(*args, **kwargs):
        raise AssertionError('must not spawn')
    monkeypatch.setattr('glaceon_companion.ollama_client.subprocess.Popen', unexpected)
    asyncio.run(client.ensure_primary_server())
