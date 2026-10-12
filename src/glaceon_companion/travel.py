"""Display-only travel leases. The model, tools and memory never leave the PC."""
from __future__ import annotations

import hmac
import json
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import psutil

from .config import _protect_windows_secret, _unprotect_windows_secret


class TravelManager:
    LEASE_SECONDS = 8
    PENDING_SECONDS = 20

    def __init__(self, data_dir: Path, api_port: int, *, clock: Callable = time.monotonic):
        self.path = data_dir / "travel-devices.json"
        self.tunnel_path = data_dir / "travel-tunnels.json"
        self.api_port = api_port
        self.clock = clock
        self.lock = threading.RLock()
        self.devices: dict[str, dict] = {}
        self.seen: dict[str, float] = {}
        self.active = "home"
        self.pending: str | None = None
        self.pending_at = 0.0
        self.generation = 0
        self.error = ""
        self.tunnels: dict[str, subprocess.Popen | psutil.Process] = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded, list) or len(loaded) > 32:
                    raise ValueError("Registro inválido")
                for row in loaded:
                    self._validate(row["id"], row["ssh_alias"])
                    if not isinstance(row["label"], str) or not isinstance(row["secret"], str):
                        raise ValueError("Registro inválido")
                    _unprotect_windows_secret(row["secret"])
                    self.devices[row["id"]] = row
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                self.devices.clear()
                self.error = "No se ha podido leer el registro de dispositivos; se conserva el archivo original."
        self._restore_tunnels()

    def _connection_args(self, device_id: str) -> list[str]:
        return ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=8", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
            "-R", f"127.0.0.1:18842:127.0.0.1:{self.api_port}",
            self.devices[device_id]["ssh_alias"],
            "systemctl --user start arfoxia-traveler.service && exec sleep infinity"]

    def _restore_tunnels(self) -> None:
        if not self.tunnel_path.exists():
            return
        try:
            rows = json.loads(self.tunnel_path.read_text(encoding="utf-8"))
            for row in rows:
                if row["device_id"] not in self.devices:
                    continue
                process = psutil.Process(row["pid"])
                if (abs(process.create_time() - row["created"]) < 0.01
                        and process.name().casefold() in {"ssh", "ssh.exe"}
                        and process.cmdline()[1:] == self._connection_args(row["device_id"])):
                    self.tunnels[row["device_id"]] = process
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            # Never terminate a process just because a damaged marker mentions its PID.
            pass

    @staticmethod
    def _poll(process) -> int | None:
        if hasattr(process, "poll"):
            return process.poll()
        return None if process.is_running() else 0

    def _save_tunnels(self) -> None:
        rows = []
        for key, process in self.tunnels.items():
            try:
                rows.append({"device_id": key, "pid": process.pid,
                             "created": psutil.Process(process.pid).create_time()})
            except (psutil.Error, AttributeError):
                continue
        temp = self.tunnel_path.with_suffix(".tmp")
        temp.write_text(json.dumps(rows), encoding="utf-8")
        temp.replace(self.tunnel_path)

    @staticmethod
    def _validate(device_id: str, alias: str) -> None:
        if device_id == "home" or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", device_id):
            raise ValueError("Identificador de dispositivo no válido")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", alias):
            raise ValueError("Usa un alias ya configurado en OpenSSH")

    def register(self, device_id: str, label: str, alias: str) -> str:
        self._validate(device_id, alias)
        if not label.strip() or len(label) > 80:
            raise ValueError("Nombre de dispositivo no válido")
        with self.lock:
            if device_id not in self.devices and len(self.devices) >= 32:
                raise ValueError("Máximo de 32 dispositivos emparejados")
            self.home()
            token = secrets.token_urlsafe(32)
            self.devices[device_id] = {"id": device_id, "label": label.strip(),
                "ssh_alias": alias, "secret": _protect_windows_secret(token)}
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(list(self.devices.values()), ensure_ascii=False), encoding="utf-8")
            temp.replace(self.path)
            self.seen.pop(device_id, None)
            return token

    def authenticate(self, token: str) -> str | None:
        with self.lock:
            for row in self.devices.values():
                if hmac.compare_digest(token, _unprotect_windows_secret(row["secret"])):
                    return row["id"]
        return None

    def _expire(self) -> None:
        now = self.clock()
        if self.active != "home" and now - self.seen.get(self.active, -1000) > self.LEASE_SECONDS:
            self.home()
            self.error = "Conexión perdida: Arfoxia ha vuelto a este PC."
        if self.pending and now - self.pending_at > self.PENDING_SECONDS:
            self.pending = None
            self.error = "El cliente no ha confirmado que pueda mostrar a Arfoxia."
        for key, process in list(self.tunnels.items()):
            if self._poll(process) is not None:
                del self.tunnels[key]
                self._save_tunnels()
                if self.pending == key:
                    self.pending = None
                    self.error = "SSH no ha conectado. Comprueba la clave, el escritorio y el servicio del cliente."

    def snapshot(self) -> dict:
        with self.lock:
            self._expire()
            now = self.clock()
            return {"active": self.active, "pending": self.pending, "generation": self.generation,
                "error": self.error, "devices": [{"id": key, "label": row["label"],
                    "online": now - self.seen.get(key, -1000) < self.LEASE_SECONDS}
                    for key, row in self.devices.items()]}

    def select(self, device_id: str, *, connect: bool = True) -> dict:
        with self.lock:
            self._expire()
            if device_id == "home":
                self.home()
                return self.snapshot()
            if device_id not in self.devices:
                raise ValueError("Dispositivo no emparejado")
            if self.active == device_id:
                return self.snapshot()
            if self.active != "home":
                raise ValueError("Haz que Arfoxia vuelva al PC antes de viajar a otro dispositivo")
            if connect and device_id not in self.tunnels:
                ssh = shutil.which("ssh")
                if not ssh:
                    raise ValueError("OpenSSH no está disponible en este PC")
                # Explicit loopback binding: no open LAN listener or owner API token on Linux.
                command = [ssh, *self._connection_args(device_id)]
                self.tunnels[device_id] = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._save_tunnels()
            self.pending = device_id
            self.pending_at = self.clock()
            self.error = ""
            return self.snapshot()

    def heartbeat(self, device_id: str, ready: bool) -> dict:
        with self.lock:
            self._expire()
            if device_id not in self.devices:
                raise ValueError("Dispositivo no emparejado")
            if ready:
                self.seen[device_id] = self.clock()
                if self.pending == device_id:
                    self.active = device_id
                    self.pending = None
                    self.generation += 1
            elif self.active == device_id:
                self.home()
                self.error = "El cliente ha perdido la capacidad de mostrar la mascota."
            return {"active": self.active == device_id, "generation": self.generation,
                    "requested": self.pending == device_id,
                    "lease_seconds": self.LEASE_SECONDS}

    def home(self) -> None:
        with self.lock:
            self.active = "home"
            self.pending = None
            self.error = ""
            self.generation += 1

    def close(self) -> None:
        with self.lock:
            self.home()
            for process in self.tunnels.values():
                if self._poll(process) is None:
                    try:
                        process.terminate()
                    except psutil.Error:
                        pass
            self.tunnels.clear()
            self._save_tunnels()
