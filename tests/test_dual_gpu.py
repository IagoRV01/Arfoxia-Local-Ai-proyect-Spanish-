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
    monkeypatch.setattr(runtime, "cpu_offload_error", lambda: "")
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


def test_dual_failure_preserves_residency_and_selection(monkeypatch):
    client = OllamaClient(CompanionConfig())
    stopped = []
    monkeypatch.setattr(client.dual, "stop_sync", lambda *args: stopped.append(args))
    client.requested_mode = "dual"
    fallback = client.fallback_small_selection(client._dual_selection(snapshot(client.config)))
    assert client.requested_mode == "dual"
    assert fallback.reason == "dual_selected"
    assert not stopped


def test_guard_samples_at_most_every_twenty_seconds(monkeypatch):
    runtime = DualGpuRuntime(CompanionConfig(), None)
    now = [100.0]
    calls = []
    monkeypatch.setattr("glaceon_companion.dual_gpu.time.monotonic", lambda: now[0])
    monkeypatch.setattr(runtime, "_check_guard", lambda: calls.append(now[0]) or "warning")
    assert runtime.guard() == "warning"
    for increment in (1, 2, 10, 19.99):
        now[0] = 100 + increment
        assert runtime.guard() == "warning"
    assert calls == [100]
    now[0] = 120
    runtime.guard()
    assert calls == [100, 120]


def test_dual_chat_uses_official_extra_high_and_never_evicts_on_warning(monkeypatch):
    import json
    client = OllamaClient(CompanionConfig())
    monkeypatch.setattr(DualGpuRuntime, "owned", property(lambda _: True))
    monkeypatch.setattr(client.dual, "stop_sync", lambda *_: pytest.fail("Unexpected eviction"))
    client.dual.last_warning = "VRAM excedida"
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "OK"}})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    asyncio.run(client.chat([{"role": "user", "content": "Hola"}], "bien",
                           selection=client._dual_selection(snapshot(client.config))))
    assert requests[0]["think"] == "high"  # Native Ollama maps high to Qwen xhigh.
    assert requests[0]["keep_alive"] == -1
    assert requests[0]["options"]["num_predict"] == 16384
    assert requests[0]["options"]["temperature"] == 1.0


def test_recovery_adopts_only_verified_server_without_terminating(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import glaceon_companion.dual_gpu as module
    (tmp_path / "dual_ollama_process.json").write_text(json.dumps(
        {"pid": 44, "created": 123, "exe": "C:/ollama.exe"}))
    process = SimpleNamespace(pid=44, create_time=lambda: 123, exe=lambda: "C:/ollama.exe",
        name=lambda: "ollama.exe", cmdline=lambda: ["ollama.exe", "serve"],
        environ=lambda: {"OLLAMA_HOST": "http://127.0.0.1:11436"}, is_running=lambda: True)
    monkeypatch.setattr(module.psutil, "Process", lambda _: process)
    monkeypatch.setattr(DualGpuRuntime, "_terminate_tree", lambda *_: pytest.fail("Unexpected stop"))
    runtime = DualGpuRuntime(CompanionConfig(), tmp_path)
    assert runtime.owned
    assert runtime.process.pid == 44
    assert runtime.marker.exists()


def test_recovery_does_not_adopt_reused_pid(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import glaceon_companion.dual_gpu as module
    (tmp_path / "dual_ollama_process.json").write_text(json.dumps(
        {"pid": 44, "created": 123, "exe": "C:/ollama.exe"}))
    monkeypatch.setattr(module.psutil, "Process", lambda _: SimpleNamespace(create_time=lambda: 999))
    runtime = DualGpuRuntime(CompanionConfig(), tmp_path)
    assert not runtime.owned
    assert not runtime.marker.exists()


def test_dual_start_refuses_game_without_starting_process(monkeypatch):
    runtime = DualGpuRuntime(CompanionConfig(), None)
    monkeypatch.setattr("glaceon_companion.dual_gpu.detect_game_processes", lambda _: GameSnapshot(True))
    with pytest.raises(RuntimeError, match="juegos activos"):
        asyncio.run(runtime.start("unused.exe"))
    assert runtime.process is None


@pytest.mark.parametrize("content_type", ["application/x-ndjson", "application/json"])
def test_stalled_reasoning_retries_once_without_unloading_or_changing_gpu_options(monkeypatch, content_type):
    import json
    client = OllamaClient(CompanionConfig())
    monkeypatch.setattr(DualGpuRuntime, "owned", property(lambda _: True))
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            chunk = {"message": {"thinking": "private" * 1200}, "done": False}
            return httpx.Response(200, text=json.dumps(chunk) + "\n", headers={"content-type": content_type})
        return httpx.Response(200, json={"message": {"content": "", "tool_calls": [
            {"function": {"name": "calculate", "arguments": {"expression": "2+2"}}}]}, "done": True})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = asyncio.run(client.chat([{"role": "user", "content": "Calcula"}], "bien",
                                    selection=client._dual_selection(snapshot(client.config))))
    assert len(requests) == 2
    assert requests[0]["stream"] is True
    assert requests[0]["think"] == "high"
    assert requests[1]["think"] is False
    assert requests[0]["options"] == requests[1]["options"]
    assert all(request["keep_alive"] == -1 for request in requests)
    assert result["execution_recovery"] is True
    assert result["recovery_reason"] == "reasoning_without_progress"
    assert "thinking" not in result["message"]
    assert "private" not in json.dumps(result)


def test_streamed_tools_are_assembled_and_never_retried(monkeypatch):
    import json
    client = OllamaClient(CompanionConfig())
    monkeypatch.setattr(DualGpuRuntime, "owned", property(lambda _: True))
    requests = []
    call = {"function": {"name": "calculate", "arguments": {"expression": "2+2"}}}
    chunks = [{"message": {"content": "Voy "}}, {"message": {"content": "a calcular", "tool_calls": [call]}},
              {"message": {"thinking": "x" * 9000}, "done": True, "eval_count": 42}]
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="\n".join(json.dumps(chunk) for chunk in chunks),
                              headers={"content-type": "application/x-ndjson"})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = asyncio.run(client.chat([{"role": "user", "content": "Calcula"}], "bien",
                                    selection=client._dual_selection(snapshot(client.config))))
    assert len(requests) == 1
    assert result["message"] == {"role": "assistant", "content": "Voy a calcular", "tool_calls": [call]}
    assert result["eval_count"] == 42


def test_empty_recovery_is_bounded_even_if_retry_also_empty(monkeypatch):
    import json
    client = OllamaClient(CompanionConfig())
    monkeypatch.setattr(DualGpuRuntime, "owned", property(lambda _: True))
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": ""}, "done_reason": "length"})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = asyncio.run(client.chat([], "bien", tools=False,
                                    selection=client._dual_selection(snapshot(client.config))))
    assert len(requests) == 2
    assert result["message"]["content"] == ""
    assert result["recovery_reason"] == "empty_generation"
    requests.clear()
    asyncio.run(client.chat([], "bien", tools=False, execution_recovery=True,
                            selection=client._dual_selection(snapshot(client.config))))
    assert len(requests) == 1 and requests[0]["think"] is False


@pytest.mark.parametrize("body", ['{"message":{"tool_calls":[{}]}}\n', 'invalid\n'])
def test_incomplete_or_invalid_stream_never_returns_a_tool_call(monkeypatch, body):
    client = OllamaClient(CompanionConfig())
    monkeypatch.setattr(DualGpuRuntime, "owned", property(lambda _: True))
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=body,
                                    headers={"content-type": "application/x-ndjson"}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    with pytest.raises(httpx.HTTPError):
        asyncio.run(client.chat([], "bien", selection=client._dual_selection(snapshot(client.config))))


@pytest.mark.parametrize("closing_workflow", [False, True])
def test_no_stream_progress_has_real_deadline_and_safe_retry(monkeypatch, closing_workflow):
    import json
    client = OllamaClient(CompanionConfig())
    monkeypatch.setattr(DualGpuRuntime, "owned", property(lambda _: True))
    monkeypatch.setattr(OllamaClient, "TOOL_PROGRESS_TIMEOUT_SECONDS", 0.01)
    class SilentStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(1)
            yield b'{"message":{"content":"too late"},"done":true}\n'
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, stream=SilentStream(), headers={"content-type": "application/x-ndjson"})
        return httpx.Response(200, json={"message": {"content": "Recovered"}, "done": True})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    messages = [{"role": "tool", "content": "Result"}] if closing_workflow else []
    result = asyncio.run(client.chat(messages, "bien", tools=not closing_workflow,
                                    selection=client._dual_selection(snapshot(client.config))))
    assert len(requests) == 2 and requests[1]["think"] is False
    assert result["recovery_reason"] == "generation_without_progress"
    assert result["message"]["content"] == "Recovered"
