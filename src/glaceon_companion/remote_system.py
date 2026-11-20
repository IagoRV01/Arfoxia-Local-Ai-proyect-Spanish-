"""Fixed-target, cached and read-only BC-250 monitoring through existing SSH."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time


class RemoteSystemMonitor:
    CACHE_SECONDS = 15

    def __init__(self, travel, clock=time.monotonic):
        self.travel = travel
        self.clock = clock
        self._lock = threading.Lock()
        self._cached = None
        self._expires = 0

    @staticmethod
    def _sanitize(raw):
        if not isinstance(raw, dict):
            raise ValueError("Invalid status")
        result = {}
        for key in ("hostname", "os_name", "cpu_name", "disk_path"):
            if isinstance(raw.get(key), str):
                result[key] = raw[key][:200]
        numeric = ("cpu_percent", "cpu_logical_cores", "cpu_temperature_c", "uptime_seconds",
                   "memory_total_gb", "memory_available_gb", "memory_used_gb", "memory_percent",
                   "disk_total_gb", "disk_used_gb", "disk_free_gb", "disk_percent")
        def valid(value):
            return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1e12
        for key in numeric:
            result[key] = raw.get(key) if valid(raw.get(key)) else None
        if not result["memory_total_gb"]:
            raise ValueError("Missing memory data")
        result["gpus"] = []
        gpus = raw.get("gpus", [])
        if not isinstance(gpus, list):
            raise ValueError("Invalid GPU data")
        for gpu in gpus[:8]:
            if not isinstance(gpu, dict):
                continue
            item = {"name": str(gpu.get("name", "AMD"))[:100]}
            for key in ("utilization_percent", "memory_used_mb", "memory_total_mb", "temperature_c", "soc_power_w"):
                item[key] = gpu.get(key) if valid(gpu.get(key)) else None
            result["gpus"].append(item)
        return result

    def status(self):
        with self._lock:
            if self._cached is not None and self.clock() < self._expires:
                return deepcopy(self._cached)
            device = self.travel.devices.get("bc250", {}) if self.travel else {}
            result = {"target": "bc250", "label": "BC-250 · Bazzite", "configured": bool(device),
                      "online": False, "sampled_at": None, "status": None, "error": ""}
            alias = device.get("ssh_alias", "")
            ssh = shutil.which("ssh")
            if not device:
                result["error"] = "Registra la BC-250 por SSH para consultar sus estadísticas."
            elif not isinstance(alias, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", alias):
                result["error"] = "La conexión SSH registrada no es válida."
            elif not ssh:
                result["error"] = "El cliente SSH no está disponible en el PC de Arfoxia."
            else:
                script = Path(__file__).with_name("remote_system_agent.py").read_text(encoding="utf-8")
                command = [ssh, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                           "-o", "ClearAllForwardings=yes", "-o", "ConnectTimeout=6",
                           "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=1",
                           alias, "python3 -c " + shlex.quote(script)]
                try:
                    reply = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                           encoding="utf-8", errors="replace", timeout=12, shell=False,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if reply.returncode or len(reply.stdout) > 65536:
                        raise ValueError("SSH failed")
                    payload = json.loads(reply.stdout)
                    if not isinstance(payload, dict) or payload.get("success") is not True:
                        raise ValueError("Invalid reply")
                    result["status"] = self._sanitize(payload.get("status"))
                    result["online"] = True
                    result["sampled_at"] = datetime.now(timezone.utc).isoformat()
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    result["error"] = "BC-250 sin conexión o sin acceso a sus métricas por SSH. Comprueba que está encendida."
            self._cached = result
            self._expires = self.clock() + self.CACHE_SECONDS
            return deepcopy(result)
