"""Owned, loopback-only Ollama runtime for the manually selected dual-GPU mode."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import httpx
import psutil

from .config import CompanionConfig
from .model_policy import GpuSnapshot, detect_game_processes, probe_nvidia_gpus


class DualGpuRuntime:
    def __init__(self, config: CompanionConfig, runtime_dir: Path | None) -> None:
        self.config = config
        self.process: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self.last_error = ""
        self.marker = runtime_dir / "dual_ollama_process.json" if runtime_dir else None
        self.log_path = runtime_dir / "dual-ollama.log" if runtime_dir else None
        self._recover()

    @property
    def owned(self) -> bool:
        with self._lock:
            return self.process is not None and self.process.poll() is None

    @property
    def url(self) -> str:
        # Never accept an arbitrary executable, host or port from the mobile API.
        return "http://127.0.0.1:11436"

    @property
    def limits_mib(self) -> tuple[int, int]:
        return 16 * 1024, 5632

    def devices(self, snapshot: GpuSnapshot):
        if not snapshot.available:
            raise RuntimeError("No puedo comprobar la VRAM de ambas GPU.")
        ai = snapshot.for_uuid(self.config.ai_gpu_uuid)
        gaming = snapshot.for_uuid(self.config.gaming_gpu_uuid)
        if not ai.available or not gaming.available or len(ai.devices) != 1 or len(gaming.devices) != 1:
            raise RuntimeError("No encuentro las dos GPU configuradas.")
        if ai.devices[0].uuid.casefold() == gaming.devices[0].uuid.casefold():
            raise RuntimeError("El modo Dual necesita dos GPU distintas.")
        return ai.devices[0], gaming.devices[0]

    def budget_error(self, snapshot: GpuSnapshot) -> str:
        try:
            devices = self.devices(snapshot)
        except RuntimeError as exc:
            return str(exc)
        for device, limit in zip(devices, self.limits_mib):
            # Count ALL dedicated memory on the card, including Windows/other apps.
            # This is deliberately stricter than counting only Arfoxia's allocation.
            if device.effective_used_vram_mib > min(limit, device.total_vram_mib):
                return (f"Límite de VRAM excedido en GPU {device.index}: "
                        f"{device.effective_used_vram_mib}/{limit} MiB; modo Dual detenido.")
            if device.free_vram_mib < 128:
                return f"Sin margen de VRAM en GPU {device.index}; modo Dual detenido."
        return ""

    def environment(self, snapshot: GpuSnapshot) -> dict[str, str]:
        ai, gaming = self.devices(snapshot)
        environment = {
            key: value for key, value in os.environ.items()
            if not key.upper().startswith(("LLAMA_ARG_", "OLLAMA_", "GGML_"))
        }
        environment.update({
            "CUDA_VISIBLE_DEVICES": f"{ai.uuid},{gaming.uuid}",
            "OLLAMA_HOST": self.url,
            "OLLAMA_MODELS": os.environ.get("OLLAMA_MODELS", str(Path.home() / ".ollama/models")),
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_KEEP_ALIVE": "-1",
            "OLLAMA_FLASH_ATTENTION": "1",
            "OLLAMA_KV_CACHE_TYPE": "q8_0",
            "OLLAMA_SCHED_SPREAD": "true",
            "OLLAMA_NO_CLOUD": "true",
            "OLLAMA_NOPRUNE": "true",
            "OLLAMA_VULKAN": "false",
            "OLLAMA_LOAD_TIMEOUT": "10m",
            # Ollama 0.34's fit exits early when all layers are explicitly on
            # GPU. Pin the split as well; never let it silently choose 2:1.
            "LLAMA_ARG_FIT": "off",
            "LLAMA_ARG_SPLIT_MODE": "layer",
            "LLAMA_ARG_TENSOR_SPLIT": "86,14",
            "LLAMA_ARG_CACHE_RAM": "0",
            "LLAMA_ARG_CTX_CHECKPOINTS": "0",
        })
        return environment

    def options(self) -> dict:
        return {"num_ctx": self.context_tokens, "num_gpu": 999,
                "num_batch": 256, "temperature": 0.6, "top_p": 0.95,
                "top_k": 20, "repeat_penalty": 1.0, "num_predict": 8192}

    @property
    def context_tokens(self) -> int:
        return max(4096, min(32768, int(self.config.dual_context_tokens)))

    def _recover(self) -> None:
        if not self.marker or not self.marker.exists():
            return
        try:
            data = json.loads(self.marker.read_text(encoding="utf-8"))
            process = psutil.Process(int(data["pid"]))
            if (abs(process.create_time() - float(data["created"])) < 0.1
                    and os.path.normcase(process.exe()) == os.path.normcase(data["exe"])
                    and process.name().casefold() == "ollama.exe"
                    and process.cmdline()[1:] == ["serve"]
                    and process.environ().get("OLLAMA_HOST") == self.url):
                self._terminate_tree(process)
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
        self.marker.unlink(missing_ok=True)

    @staticmethod
    def _terminate_tree(process: psutil.Process) -> None:
        try:
            children = process.children(recursive=True)
            process.terminate()
            for child in children:
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            _, alive = psutil.wait_procs([process, *children], timeout=3)
            for item in alive:
                try:
                    item.kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass

    def stop_sync(self, reason: str = "") -> None:
        with self._lock:
            process, self.process = self.process, None
            if reason:
                self.last_error = reason
            if process is not None and process.poll() is None:
                try:
                    self._terminate_tree(psutil.Process(process.pid))
                except psutil.Error:
                    pass
            if self.marker:
                self.marker.unlink(missing_ok=True)

    async def stop(self) -> None:
        await asyncio.to_thread(self.stop_sync)

    async def start(self, executable: str) -> None:
        if self.owned:
            return
        game = await asyncio.to_thread(detect_game_processes, self.config.game_processes)
        if game.active or game.error:
            raise RuntimeError("El modo Dual solo está disponible si no hay juegos activos y la comprobación funciona.")
        snapshot = await asyncio.to_thread(probe_nvidia_gpus)
        environment = self.environment(snapshot)
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 11436))
        except OSError as exc:
            raise RuntimeError("El puerto privado 11436 está ocupado; no modificaré ese proceso.") from exc
        log = None
        try:
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                log = self.log_path.open("a", encoding="utf-8")
            with self._lock:
                self.last_error = ""
                self.process = subprocess.Popen(
                    [executable, "serve"], env=environment, stdin=subprocess.DEVNULL,
                    stdout=log or subprocess.DEVNULL, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False,
                )
                if self.marker:
                    self.marker.parent.mkdir(parents=True, exist_ok=True)
                    owned = psutil.Process(self.process.pid)
                    self.marker.write_text(json.dumps({"pid": owned.pid,
                        "created": owned.create_time(), "exe": owned.exe()}), encoding="utf-8")
            async with httpx.AsyncClient(timeout=2) as client:
                for _ in range(120):
                    if not self.owned:
                        raise RuntimeError("El servidor Dual se ha detenido.")
                    try:
                        response = await client.get(f"{self.url}/api/version")
                        response.raise_for_status()
                        return
                    except httpx.HTTPError:
                        await asyncio.sleep(0.25)
            raise RuntimeError("Ollama Dual no respondió a tiempo.")
        except BaseException:
            self.stop_sync()
            raise
        finally:
            if log:
                log.close()

    def guard(self) -> str:
        if not self.owned:
            return "El servidor Dual no está activo."
        game = detect_game_processes(self.config.game_processes)
        if game.active or game.error:
            return "Juego detectado o comprobación no disponible; GPU de juego liberada."
        error = self.budget_error(probe_nvidia_gpus())
        if error:
            return error
        # Ollama may retry a vision projector on CPU. Reject that fallback too.
        try:
            with self._lock:
                if self.process is None:
                    return "El servidor Dual se ha detenido."
                for child in psutil.Process(self.process.pid).children(recursive=True):
                    if "--no-mmproj-offload" in child.cmdline():
                        return "El proyector visual intentó usar CPU; modo Dual cancelado."
        except psutil.Error:
            return "No puedo verificar los procesos del modo Dual."
        return ""

    async def preload(self) -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=5)) as client:
            loading = asyncio.create_task(client.post(f"{self.url}/api/generate", json={
                "model": self.config.dual_model, "prompt": "", "stream": False,
                "keep_alive": -1, "options": self.options(),
            }))
            try:
                while not loading.done():
                    error = await asyncio.to_thread(self.guard)
                    if error:
                        raise RuntimeError(error)
                    await asyncio.wait({loading}, timeout=1)
                (await loading).raise_for_status()
                models = (await client.get(f"{self.url}/api/ps")).json().get("models", [])
                model = next((item for item in models if item.get("name") == self.config.dual_model), {})
                if not model.get("size") or model.get("size_vram", 0) < model["size"] * 0.995:
                    raise RuntimeError("Ollama no cargó el 100 % del modelo en GPU; no usaré RAM para las capas.")
                error = await asyncio.to_thread(self.guard)
                if error:
                    raise RuntimeError(error)
            except BaseException as exc:
                self.stop_sync(str(exc))
                raise
            finally:
                loading.cancel()
                await asyncio.gather(loading, return_exceptions=True)
