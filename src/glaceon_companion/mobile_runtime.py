from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import IO, Any, Callable


DEFAULT_METRO_PORT = 8081
METRO_STARTUP_GRACE_SECONDS = 90.0
METRO_HEALTH_FAILURE_LIMIT = 12
MIN_RESTART_DELAY_SECONDS = 10.0
MAX_RESTART_DELAY_SECONDS = 60.0


class MobileRuntimeManager:
    """Start and supervise the private Expo/Metro development server.

    The public methods are non-blocking so a slow Tailscale startup cannot
    freeze Arfoxia's Qt interface. Only a process created by this manager is
    ever terminated.
    """

    def __init__(
        self,
        mobile_dir: Path,
        data_dir: Path,
        *,
        enabled: bool = True,
        port: int = DEFAULT_METRO_PORT,
        preferred_host: str = "",
        node_executable: Path | None = None,
        tailscale_executable: Path | None = None,
        popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mobile_dir = mobile_dir.resolve()
        self.data_dir = data_dir.resolve()
        self.enabled = bool(enabled)
        self.port = max(1, min(int(port), 65_535))
        self.preferred_host = preferred_host.strip().rstrip(".")
        self.node_executable = node_executable
        self.tailscale_executable = tailscale_executable
        self._popen = popen_factory
        self._run = run_command
        self._clock = clock

        self._lock = threading.RLock()
        self._process: subprocess.Popen[Any] | None = None
        self._process_started_at = 0.0
        self._log_stream: IO[str] | None = None
        self._worker_active = False
        self._closed = False
        self._last_log_message = ""
        self._ever_ready = False
        self._health_failures = 0
        self._restart_delay_seconds = 0.0
        self._next_start_at = 0.0

    @property
    def log_path(self) -> Path:
        return self.data_dir / "expo-mobile.log"

    @property
    def cached_host_path(self) -> Path:
        return self.data_dir / "expo-host.txt"

    def ensure_started(self) -> None:
        """Schedule one health/start check without blocking the caller."""

        with self._lock:
            if not self.enabled or self._closed or self._worker_active:
                return
            self._worker_active = True
        threading.Thread(
            target=self._ensure_worker,
            daemon=True,
            name="arfoxia-expo-supervisor",
        ).start()

    def _ensure_worker(self) -> None:
        try:
            self._ensure_started_once()
        except Exception as exc:  # pragma: no cover - final startup safety net
            self._log(f"No se pudo comprobar Expo/Metro: {type(exc).__name__}.")
        finally:
            with self._lock:
                self._worker_active = False

    def _ensure_started_once(self) -> None:
        """Run one supervisor pass. Kept separate for deterministic tests."""

        with self._lock:
            if not self.enabled or self._closed:
                return
            process = self._process

        if process is not None and process.poll() is None:
            if self._metro_running():
                with self._lock:
                    self._ever_ready = True
                    self._health_failures = 0
                    self._restart_delay_seconds = 0.0
                    self._next_start_at = 0.0
                return
            with self._lock:
                startup_grace = (
                    not self._ever_ready
                    and self._clock() - self._process_started_at
                    < METRO_STARTUP_GRACE_SECONDS
                )
                if startup_grace:
                    return
                self._health_failures += 1
                health_failures = self._health_failures
            if health_failures < METRO_HEALTH_FAILURE_LIMIT:
                return
            self._log(
                "Expo dejó de responder durante varias comprobaciones; "
                "se reiniciará."
            )
            self._discard_owned_process(terminate=True)
            self._schedule_restart()
            return
        elif process is not None:
            return_code = process.poll()
            self._discard_owned_process(terminate=False)
            self._schedule_restart(
                f"Expo se cerró con código {return_code};"
            )
            return

        with self._lock:
            if self._clock() < self._next_start_at:
                return

        if self._metro_running():
            self._log(
                f"Expo/Metro ya estaba disponible en el puerto {self.port}."
            )
            return
        if self._port_open():
            self._log(
                f"El puerto {self.port} está ocupado por otro programa; "
                "Expo no se iniciará para evitar un conflicto."
            )
            return

        node = self._resolve_node()
        expo_cli = self.mobile_dir / "node_modules" / "expo" / "bin" / "cli"
        if node is None:
            self._log("No se encuentra Node.js; Expo no puede iniciarse.")
            return
        if not expo_cli.is_file():
            self._log("No se encuentra el Expo CLI local; ejecuta npm install en mobile.")
            return

        hostname = self._tailscale_host()
        if not hostname:
            self._log("Esperando a que Tailscale esté listo antes de iniciar Expo.")
            return

        self.data_dir.mkdir(parents=True, exist_ok=True)
        log_stream = self.log_path.open("a", encoding="utf-8", buffering=1)
        command = [
            str(node),
            str(expo_cli),
            "start",
            "--go",
            "--port",
            str(self.port),
            "--max-workers",
            "2",
        ]
        environment = os.environ.copy()
        # Expo Go 57 on iOS needs the CLI's signed-in development session.
        # Do not inherit an old offline setting that disables its registration.
        environment.pop("EXPO_OFFLINE", None)
        environment["REACT_NATIVE_PACKAGER_HOSTNAME"] = hostname
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )

        with self._lock:
            if self._closed:
                log_stream.close()
                return
        try:
            process = self._popen(
                command,
                cwd=str(self.mobile_dir),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=creationflags,
            )
        except OSError as exc:
            log_stream.close()
            self._log(f"No se pudo iniciar Expo: {type(exc).__name__}.")
            self._schedule_restart()
            return

        with self._lock:
            if self._closed:
                log_stream.close()
                self._terminate_process(process)
                return
            self._process = process
            self._process_started_at = self._clock()
            self._log_stream = log_stream
            self._ever_ready = False
            self._health_failures = 0
        self._log(f"Expo iniciado para {hostname}:{self.port}.")

    def stop(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._discard_owned_process(terminate=True)

    def _discard_owned_process(self, *, terminate: bool) -> None:
        with self._lock:
            process = self._process
            stream = self._log_stream
            self._process = None
            self._log_stream = None
            self._process_started_at = 0.0
            self._ever_ready = False
            self._health_failures = 0

        if process is not None and terminate and process.poll() is None:
            self._terminate_process(process)
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass

    @staticmethod
    def _terminate_process(process: subprocess.Popen[Any]) -> None:
        try:
            process.terminate()
            process.wait(timeout=5.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _schedule_restart(self, prefix: str = "Expo se reiniciará;") -> None:
        with self._lock:
            if self._closed:
                return
            if self._restart_delay_seconds:
                delay = min(
                    self._restart_delay_seconds * 2.0,
                    MAX_RESTART_DELAY_SECONDS,
                )
            else:
                delay = MIN_RESTART_DELAY_SECONDS
            self._restart_delay_seconds = delay
            self._next_start_at = self._clock() + delay
        self._log(f"{prefix} nuevo intento en {int(delay)} segundos.")

    def _resolve_node(self) -> Path | None:
        candidates: list[Path] = []
        if self.node_executable:
            candidates.append(self.node_executable)
        resolved = shutil.which("node")
        if resolved:
            candidates.append(Path(resolved))
        if os.name == "nt":
            candidates.append(Path("C:/Program Files/nodejs/node.exe"))
        return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)

    def _resolve_tailscale(self) -> Path | None:
        candidates: list[Path] = []
        if self.tailscale_executable:
            candidates.append(self.tailscale_executable)
        resolved = shutil.which("tailscale")
        if resolved:
            candidates.append(Path(resolved))
        if os.name == "nt":
            candidates.append(Path("C:/Program Files/Tailscale/tailscale.exe"))
        return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)

    def _tailscale_host(self) -> str | None:
        preferred = self._validated_host(self.preferred_host)
        if preferred:
            self._cache_tailscale_host(preferred)
            return preferred
        executable = self._resolve_tailscale()
        if executable is None:
            return self._cached_tailscale_host()
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )
        try:
            status = self._run(
                [str(executable), "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3.0,
                check=True,
                shell=False,
                creationflags=creationflags,
            )
            payload = json.loads(status.stdout)
            if payload.get("BackendState") not in (None, "Running"):
                return self._cached_tailscale_host()
            hostname = str(payload.get("Self", {}).get("DNSName", "")).rstrip(".")
            if self._valid_hostname(hostname):
                self._cache_tailscale_host(hostname)
                return hostname
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

        try:
            address = self._run(
                [str(executable), "ip", "-4"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3.0,
                check=True,
                shell=False,
                creationflags=creationflags,
            ).stdout.strip().splitlines()[0]
            if isinstance(ipaddress.ip_address(address), ipaddress.IPv4Address):
                self._cache_tailscale_host(address)
                return address
        except (
            IndexError,
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ):
            return self._cached_tailscale_host()
        return self._cached_tailscale_host()

    def _cached_tailscale_host(self) -> str | None:
        try:
            value = self.cached_host_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return self._validated_host(value)

    @classmethod
    def _validated_host(cls, value: str) -> str | None:
        try:
            if isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address):
                return value
        except ValueError:
            pass
        return value if cls._valid_hostname(value) else None

    def _cache_tailscale_host(self, value: str) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.cached_host_path.write_text(value, encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _valid_hostname(value: str) -> bool:
        if not value or len(value) > 253 or "." not in value:
            return False
        labels = value.split(".")
        return all(
            label
            and len(label) <= 63
            and label[0].isalnum()
            and label[-1].isalnum()
            and all(character.isalnum() or character == "-" for character in label)
            for label in labels
        )

    def _metro_running(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/status",
                timeout=0.6,
            ) as response:
                value = response.read(128).decode("utf-8", errors="replace").strip()
                raw_root = response.headers.get("X-React-Native-Project-Root", "")
            if value != "packager-status:running" or not raw_root:
                return False
            project_root = Path(urllib.parse.unquote(raw_root)).resolve()
            return project_root == self.mobile_dir
        except (OSError, urllib.error.URLError, ValueError):
            return False

    def _port_open(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.3):
                return True
        except OSError:
            return False

    def _log(self, message: str) -> None:
        with self._lock:
            if message == self._last_log_message:
                return
            self._last_log_message = message
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"[{stamp}] {message}\n")
        except OSError:
            pass
