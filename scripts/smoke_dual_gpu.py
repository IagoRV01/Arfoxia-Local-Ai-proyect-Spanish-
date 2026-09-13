"""Manual live test: unload Arfoxia models, exercise Dual, then release both GPUs.

Does not write conversations or execute any tool proposed by the model.
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from glaceon_companion.config import ConfigStore
from glaceon_companion.model_policy import probe_nvidia_gpus
from glaceon_companion.ollama_client import OllamaClient


async def main() -> None:
    config = ConfigStore().load()
    client = OllamaClient(config, Path(".test-tmp/dual-smoke"))
    configured = {config.model, config.large_model, config.power_model}
    for model in await client.running_models():
        if model.name in configured:
            await client.unload(model.name)
    await asyncio.sleep(1)
    peaks: dict[str, int] = {}

    async def watch():
        while client.dual.owned:
            error = await asyncio.to_thread(client.dual.guard)
            if error:
                client.dual.stop_sync(error)
                raise RuntimeError(error)
            for gpu in (await asyncio.to_thread(probe_nvidia_gpus)).devices:
                peaks[gpu.uuid] = max(peaks.get(gpu.uuid, 0), gpu.effective_used_vram_mib)
            await asyncio.sleep(1)

    watcher = None
    try:
        await client.dual.start(client._gaming_ollama_executable())
        print(json.dumps({"stage": "loading", "options": client.dual.options()}), flush=True)
        await client.dual.preload()
        watcher = asyncio.create_task(watch())
        client.requested_mode = "dual"
        selection = client._dual_selection(probe_nvidia_gpus())
        print(json.dumps({"stage": "loaded", "models": [model.name for model in
            await client.running_models(client.dual.url)]}), flush=True)
        examples = [
            ("code", {"role": "user", "content": "Escribe una función Python es_primo(n) correcta y tres asserts. Solo código corto."}, False),
            ("tool", {"role": "user", "content": "Busca las noticias de hoy en España usando web_search."}, ["web_search"]),
            ("vision", {"role": "user", "content": "Describe en una frase el personaje y su color principal.",
                "images": [base64.b64encode(Path("mobile/assets/arfoxia.png").read_bytes()).decode()]}, False),
        ]
        for name, message, tools in examples:
            response = await client.chat([message], "tranquilo", tools=tools, selection=selection)
            if watcher.done():
                await watcher
            value = response.get("message", {})
            print(json.dumps({"test": name, "content": value.get("content"),
                "tool_calls": value.get("tool_calls"), "eval_count": response.get("eval_count"),
                "tokens_per_second": round(response.get("eval_count", 0) * 1e9 /
                    max(1, response.get("eval_duration", 1)), 2), "peaks_mib": peaks}, ensure_ascii=True), flush=True)
            assert value.get("content") or value.get("tool_calls"), "Empty model response"
            if name == "tool":
                assert value.get("tool_calls"), "Expected a structured tool call"
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await client.dual.stop()
        print(json.dumps({"stage": "released", "peaks_mib": peaks}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
