from __future__ import annotations

import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
import psutil

from .config import CompanionConfig, ConfigStore
from .model_policy import probe_nvidia_gpus


SUNSHINE_EXECUTABLE = Path("C:/Program Files/Sunshine/sunshine.exe")
SUNSHINE_STATE_FILE = Path(
    "C:/Program Files/Sunshine/config/sunshine_state.json"
)
MOONLIGHT_APP_STORE_URL = (
    "https://apps.apple.com/es/app/moonlight-game-streaming/id1000551566"
)
STREAMING_TCP_PORTS = (47984, 47989, 48010)
PAIR_ATTEMPT_LIMIT = 5
PAIR_ATTEMPT_WINDOW_SECONDS = 60.0


class GameStreamingError(RuntimeError):
    pass


class PairingRateLimitedError(GameStreamingError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(
            "Demasiados intentos de emparejamiento. "
            f"Espera {self.retry_after_seconds} segundos."
        )


class GameStreamingManager:
    """A narrow local bridge between Expo Go and Sunshine.

    It can check/start only the exact Sunshine Windows service and submit the
    four-digit Moonlight PIN to Sunshine's loopback API. It deliberately does
    not expose Sunshine's generic administrative API or a command runner.
    """

    def __init__(self, config: CompanionConfig, store: ConfigStore) -> None:
        self.config = config
        self.store = store
        self._lock = threading.RLock()
        self._pair_attempts: deque[float] = deque()

    def status(self) -> dict[str, Any]:
        service_status = self._service_status()
        installed = SUNSHINE_EXECUTABLE.is_file() or service_status is not None
        running = service_status == "running"
        ports = {
            str(port): self._port_open(port)
            for port in (*STREAMING_TCP_PORTS, self.config.sunshine_web_port)
        }
        streaming_ports_ready = all(
            ports.get(str(port), False) for port in STREAMING_TCP_PORTS
        )
        web_ready = ports.get(str(self.config.sunshine_web_port), False)
        credentials = self.store.sunshine_credentials()
        paired_clients, credentials_verified, paired_device_names = (
            self._sunshine_client_status(credentials)
        )
        tailscale_ip = self._tailscale_ipv4()
        host = (
            str(self.config.game_streaming_host or "").strip()
            or str(self.config.mobile_dev_server_host or "").strip()
            or tailscale_ip
        )
        sunshine_ready = bool(
            self.config.game_streaming_enabled
            and installed
            and running
            and streaming_ports_ready
        )
        remote_ready = bool(sunshine_ready and tailscale_ip and host)
        pin_submission_available = bool(
            sunshine_ready and web_ready and credentials and credentials_verified
        )
        return {
            "enabled": bool(self.config.game_streaming_enabled),
            "installed": installed,
            "service_status": service_status or "missing",
            "running": running,
            "ready": remote_ready,
            "sunshine_ready": sunshine_ready,
            "remote_ready": remote_ready,
            "web_ready": web_ready,
            "ports": ports,
            "host": host,
            "tailscale_ip": tailscale_ip,
            "tailscale_ready": bool(tailscale_ip),
            "credentials_managed": credentials is not None,
            "credentials_verified": credentials_verified,
            "pin_submission_available": pin_submission_available,
            "pairing_available": pin_submission_available,
            "paired": paired_clients > 0,
            "paired_clients": paired_clients,
            "paired_device_names": paired_device_names,
            "gamepad_ready": self._vigembus_ready(),
            "capture_gpu": self._capture_gpu_label(),
            "moonlight_app_store_url": MOONLIGHT_APP_STORE_URL,
            "wake_available": False,
            "wake_reason": (
                "Tailscale no puede despertar por sí solo un PC apagado; "
                "hace falta otro dispositivo siempre encendido en la red de casa."
            ),
        }

    def prepare(self) -> dict[str, Any]:
        if not self.config.game_streaming_enabled:
            raise GameStreamingError("El streaming de juegos está desactivado.")
        status = self.status()
        if not status["installed"]:
            raise GameStreamingError("Sunshine no está instalado en este PC.")
        if not status["running"]:
            self._start_service()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if self._service_status() == "running":
                    break
                time.sleep(0.25)
        self._wait_for_web_port()

        with self._lock:
            if (
                not self.store.sunshine_credentials()
                and not SUNSHINE_STATE_FILE.exists()
            ):
                self._create_sunshine_credentials()

        status = self.status()
        if not status["running"]:
            raise GameStreamingError(
                "Sunshine está instalado, pero su servicio no ha podido iniciarse."
            )
        if not status["sunshine_ready"]:
            raise GameStreamingError(
                "Sunshine se ha iniciado, pero todavía no están listos sus puertos "
                "de streaming."
            )
        if not status["remote_ready"]:
            status["message"] = (
                "Sunshine está listo en la red local. Conecta Tailscale en el PC "
                "para jugar desde fuera de casa."
            )
        elif not status["credentials_verified"]:
            status["message"] = (
                "El PC está listo. Sunshine ya tenía credenciales propias; "
                "el PIN se debe confirmar una vez desde su panel local."
            )
        elif status["paired"]:
            status["message"] = "PC listo y Moonlight ya emparejado."
        else:
            status["message"] = (
                "PC listo. Añade el host en Moonlight y escribe aquí el PIN "
                "de cuatro dígitos."
            )
        return status

    def pair(self, pin: str, name: str = "iPhone de Iago") -> dict[str, Any]:
        pin_value = str(pin).strip()
        if len(pin_value) != 4 or any(
            character not in "0123456789" for character in pin_value
        ):
            raise ValueError("El PIN de Moonlight debe tener exactamente 4 cifras.")
        name_value = " ".join(str(name).split()).strip()[:64]
        if not name_value:
            name_value = "iPhone de Iago"
        with self._lock:
            return self._pair_locked(pin_value, name_value)

    def _pair_locked(self, pin_value: str, name_value: str) -> dict[str, Any]:
        self._record_pair_attempt()
        status = self.prepare()
        if not status["pin_submission_available"]:
            raise GameStreamingError(
                "Arfoxia no dispone de las credenciales locales de Sunshine. "
                "Completa el PIN en https://localhost:47990 desde el PC."
            )
        credentials = self.store.sunshine_credentials()
        if credentials is None:
            raise GameStreamingError("Faltan las credenciales locales de Sunshine.")
        username, password = credentials
        try:
            with self._http_client() as client:
                response = client.post(
                    "/api/pin",
                    auth=httpx.BasicAuth(username, password),
                    json={"pin": pin_value, "name": name_value},
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GameStreamingError(
                "Sunshine no ha podido confirmar el PIN. Comprueba que Moonlight "
                "siga mostrando la solicitud de emparejamiento."
            ) from exc
        if payload.get("status") not in {True, "true"}:
            raise GameStreamingError(
                str(payload.get("error") or "Sunshine ha rechazado el PIN.")
            )
        result = self.status()
        result["message"] = (
            "PIN enviado a Sunshine. Vuelve a Moonlight para comprobar la conexión."
        )
        return result

    def _create_sunshine_credentials(self) -> None:
        username = "arfoxia"
        password = secrets.token_urlsafe(32)
        # Persist the DPAPI-protected value before changing Sunshine. If the
        # response is lost after Sunshine commits, Arfoxia still retains the
        # only usable credential and can verify it on the next status request.
        self.store.save_sunshine_credentials(username, password)
        try:
            with self._http_client() as client:
                response = client.post(
                    "/api/password",
                    json={
                        "newUsername": username,
                        "newPassword": password,
                        "confirmNewPassword": password,
                    },
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GameStreamingError(
                "Sunshine necesita que crees sus credenciales iniciales en "
                "https://localhost:47990."
            ) from exc
        if payload.get("status") not in {True, "true"}:
            raise GameStreamingError(
                str(payload.get("error") or "Sunshine no aceptó sus credenciales.")
            )
        self.store.save_sunshine_credentials(username, password)

    def _http_client(self) -> httpx.Client:
        # This exception is intentionally scoped to Sunshine's literal
        # loopback-only endpoint and never applies to a configurable host.
        return httpx.Client(
            base_url=f"https://127.0.0.1:{int(self.config.sunshine_web_port)}",
            verify=False,
            trust_env=False,
            timeout=httpx.Timeout(8.0),
            headers={"Accept": "application/json"},
        )

    def _service_status(self) -> str | None:
        if os.name != "nt":
            return "running" if self._process_running() else None
        try:
            return str(
                psutil.win_service_get(self.config.sunshine_service_name).status()
            ).casefold()
        except (OSError, psutil.Error):
            return "running" if self._process_running() else None

    @staticmethod
    def _process_running() -> bool:
        for process in psutil.process_iter(["name"]):
            try:
                if str(process.info.get("name") or "").casefold() == "sunshine.exe":
                    return True
            except (psutil.Error, OSError):
                continue
        return False

    def _start_service(self) -> None:
        if os.name != "nt":
            raise GameStreamingError(
                "El inicio automático de Sunshine solo está configurado para Windows."
            )
        try:
            completed = subprocess.run(
                ["sc.exe", "start", self.config.sunshine_service_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GameStreamingError(
                "Windows no ha podido iniciar el servicio de Sunshine."
            ) from exc
        if completed.returncode not in {0, 1056}:
            raise GameStreamingError(
                "Windows no ha permitido iniciar el servicio de Sunshine."
            )

    @staticmethod
    def _port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.35):
                return True
        except OSError:
            return False

    def _wait_for_web_port(self) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self._port_open(self.config.sunshine_web_port):
                return
            time.sleep(0.25)

    def _tailscale_ipv4(self) -> str:
        executable = shutil.which("tailscale")
        installed = Path("C:/Program Files/Tailscale/tailscale.exe")
        if not executable and installed.is_file():
            executable = str(installed)
        if not executable:
            return ""
        try:
            completed = subprocess.run(
                [executable, "ip", "-4"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if completed.returncode != 0:
            return ""
        candidates = completed.stdout.strip().splitlines()
        if not candidates:
            return ""
        candidate = candidates[0].strip()
        try:
            address = ipaddress.ip_address(candidate)
            tailnet = ipaddress.ip_network("100.64.0.0/10")
        except ValueError:
            return ""
        return candidate if address.version == 4 and address in tailnet else ""

    def _sunshine_client_status(
        self,
        credentials: tuple[str, str] | None,
    ) -> tuple[int, bool, list[str]]:
        if credentials is None:
            return self._paired_client_count(), False, []
        username, password = credentials
        try:
            with self._http_client() as client:
                response = client.get(
                    "/api/clients/list",
                    auth=httpx.BasicAuth(username, password),
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return self._paired_client_count(), False, []
        if not isinstance(payload, dict) or payload.get("status") not in {
            True,
            "true",
        }:
            return self._paired_client_count(), False, []
        records = payload.get("named_certs")
        if not isinstance(records, list):
            return self._paired_client_count(), True, []
        names: list[str] = []
        count = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("enabled") is False or record.get("revoked") is True:
                continue
            count += 1
            raw_name = record.get("name") or record.get("displayName")
            if isinstance(raw_name, str) and raw_name.strip():
                names.append(raw_name.strip()[:64])
        return count, True, names

    @staticmethod
    def _paired_client_count() -> int:
        if not SUNSHINE_STATE_FILE.is_file():
            return 0
        try:
            payload = json.loads(SUNSHINE_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0

        def find_devices(value: Any) -> int:
            if isinstance(value, dict):
                for key in ("named_certs", "named_devices", "devices", "clients"):
                    devices = value.get(key)
                    if isinstance(devices, (list, dict)):
                        return len(devices)
                for nested in value.values():
                    count = find_devices(nested)
                    if count:
                        return count
            elif isinstance(value, list):
                for nested in value:
                    count = find_devices(nested)
                    if count:
                        return count
            return 0

        return find_devices(payload)

    @staticmethod
    def _vigembus_ready() -> bool:
        if os.name != "nt":
            return False
        try:
            return psutil.win_service_get("ViGEmBus").status().casefold() == "running"
        except (OSError, psutil.Error):
            return False

    def _capture_gpu_label(self) -> str:
        snapshot = probe_nvidia_gpus(self.config.gaming_gpu_uuid)
        if not snapshot.available or len(snapshot.devices) != 1:
            return "GPU de juego configurada en Sunshine"
        device = snapshot.devices[0]
        name = device.name.strip() or "GPU NVIDIA"
        total_gb = max(1, round(device.total_vram_mib / 1024))
        return f"{name} de {total_gb} GB (pantalla de juego)"

    def _record_pair_attempt(self) -> None:
        now = time.monotonic()
        with self._lock:
            cutoff = now - PAIR_ATTEMPT_WINDOW_SECONDS
            while self._pair_attempts and self._pair_attempts[0] <= cutoff:
                self._pair_attempts.popleft()
            if len(self._pair_attempts) >= PAIR_ATTEMPT_LIMIT:
                retry_after = int(
                    PAIR_ATTEMPT_WINDOW_SECONDS - (now - self._pair_attempts[0])
                )
                raise PairingRateLimitedError(retry_after)
            self._pair_attempts.append(now)
