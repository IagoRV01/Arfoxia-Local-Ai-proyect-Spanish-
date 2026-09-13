import asyncio
from dataclasses import replace

import httpx
import pytest

from glaceon_companion.config import CompanionConfig
from glaceon_companion.dual_gpu import DualGpuRuntime
from glaceon_companion.model_policy import GameSnapshot, GpuDevice, GpuSnapshot
from glaceon_companion.ollama_client import OllamaClient


def snapshot(config, ai_used=14500, gaming_used=5000):
    return GpuSnapshot(devices=(
        GpuDevice(0, 8151, 8151 - gaming_used, config.gaming_gpu_uuid, used_vram_mib=gaming_used),
        GpuDevice(1, 16311, 16311 - ai_used, config.ai_gpu_uuid, used_vram_mib=ai_used),
    ))


def test_dual_environment_pins_uuid_order_and_preserves_main_ollama(monkeypatch):
    config = CompanionConfig()
    runtime = DualGpuRuntime(config, None)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "old")
    monkeypatch.setenv("LLAMA_ARG_MAIN_GPU", "0")
    monkeypatch.setenv("OLLAMA_GPU_OVERHEAD", "1")
    env = runtime.environment(snapshot(config))
    assert env["CUDA_VISIBLE_DEVICES"] == f"{config.ai_gpu_uuid},{config.gaming_gpu_uuid}"
    assert env["OLLAMA_HOST"] == "http://127.0.0.1:11436"
    assert env["LLAMA_ARG_SPLIT_MODE"] == "layer"
    assert env["LLAMA_ARG_TENSOR_SPLIT"] == "86,14"
    assert env["LLAMA_ARG_FIT"] == "off"
    assert env["LLAMA_ARG_CACHE_RAM"] == "0"
    assert env["LLAMA_ARG_CTX_CHECKPOINTS"] == "0"
    assert env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
    assert env["OLLAMA_NO_CLOUD"] == "true"
    assert "LLAMA_ARG_MAIN_GPU" not in env
    assert "OLLAMA_GPU_OVERHEAD" not in env
    import os
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "old"


@pytest.mark.parametrize("ai,gaming,blocked", [(14500, 5632, False), (14500, 5633, True),
                                                   (16300, 4000, True), (14500, 4000, False)])
def test_dual_budget_counts_desktop_memory_and_keeps_headroom(ai, gaming, blocked):
    config = CompanionConfig()
    assert bool(DualGpuRuntime(config, None).budget_error(snapshot(config, ai, gaming))) is blocked


def test_dual_refuses_unknown_or_duplicate_gpu():
    config = CompanionConfig()
    runtime = DualGpuRuntime(config, None)
    with pytest.raises(RuntimeError):
        runtime.environment(GpuSnapshot.failed("no nvidia-smi"))
    same = replace(config, ai_gpu_uuid=config.gaming_gpu_uuid)
    with pytest.raises(RuntimeError):
        DualGpuRuntime(same, None).environment(snapshot(config))


def test_dual_options_cannot_force_single_gpu_or_unbounded_context():
    runtime = DualGpuRuntime(replace(CompanionConfig(), dual_context_tokens=999999), None)
    assert runtime.options()["num_gpu"] == 999
    assert runtime.options()["num_ctx"] == 32768
    assert "main_gpu" not in runtime.options()


@pytest.mark.parametrize("percent,accepted", [(100, True), (90, False), (0, False)])
def test_dual_preload_rejects_cpu_layers_and_keeps_residency(monkeypatch, percent, accepted):
    runtime = DualGpuRuntime(CompanionConfig(), None)
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": runtime.config.dual_model,
                "size": 10000, "size_vram": percent * 100}]})
        return httpx.Response(200, json={"done": True})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(runtime, "guard", lambda: "")
    if accepted:
        asyncio.run(runtime.preload())
    else:
        with pytest.raises(RuntimeError, match="100 %"):
            asyncio.run(runtime.preload())
    import json
    payload = json.loads(requests[0].content)
    assert payload["keep_alive"] == -1
    assert "main_gpu" not in payload["options"]


def test_dual_game_guard_blocks_before_gpu_probe(monkeypatch):
    runtime = DualGpuRuntime(CompanionConfig(), None)
    monkeypatch.setattr(DualGpuRuntime, "owned", property(lambda _: True))
    monkeypatch.setattr("glaceon_companion.dual_gpu.detect_game_processes", lambda _: GameSnapshot(True))
    assert "Juego detectado" in runtime.guard()


def test_dual_failure_stops_sidecar_and_returns_normal(monkeypatch):
    client = OllamaClient(CompanionConfig())
    stopped = []
    monkeypatch.setattr(client.dual, "stop_sync", lambda *args: stopped.append(args))
    client.requested_mode = "dual"
    fallback = client.fallback_small_selection(client._dual_selection(snapshot(client.config)))
    assert client.requested_mode == "normal"
    assert fallback.reason == "dual_runtime_failed"
    assert stopped


def test_dual_start_refuses_game_without_starting_process(monkeypatch):
    runtime = DualGpuRuntime(CompanionConfig(), None)
    monkeypatch.setattr("glaceon_companion.dual_gpu.detect_game_processes", lambda _: GameSnapshot(True))
    with pytest.raises(RuntimeError, match="juegos activos"):
        asyncio.run(runtime.start("unused.exe"))
    assert runtime.process is None
