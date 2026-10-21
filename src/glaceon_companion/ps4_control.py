"""Local launcher settings for the bounded PS4 menu control, never a loader."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import subprocess
import sys

from .config import PROJECT_ROOT


def validate_settings(host: str, revision: int) -> tuple[str, int]:
    if not isinstance(host, str):
        raise ValueError("Introduce la IPv4 privada de tu PS4.")
    address = ipaddress.ip_address(host.strip())
    if (address.version != 4 or not address.is_private or address.is_loopback
            or address.is_unspecified or address.is_multicast):
        raise ValueError("Usa la IPv4 privada de tu PS4, no una dirección pública o local del PC.")
    if type(revision) is not int or revision not in (10, 11):
        raise ValueError("Selecciona un cliente de menú revisado (v10 o v11).")
    return str(address), revision


def load_settings(data_dir: Path) -> tuple[str, int]:
    path = data_dir / "ps4-menu-control.json"
    if not path.exists():
        return "", 11
    with path.open("rb") as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("La configuración PS4 es demasiado grande; se conserva sin modificar.")
    row = json.loads(data)
    if not isinstance(row, dict) or set(row) != {"host", "revision"}:
        raise ValueError("Configuración PS4 desconocida; se conserva sin modificar.")
    return validate_settings(row["host"], row["revision"])


def launch_controls(data_dir: Path, host: str, revision: int) -> subprocess.Popen:
    host, revision = validate_settings(host, revision)
    # Read before writing: do not silently overwrite unknown/corrupted settings.
    load_settings(data_dir)
    script = PROJECT_ROOT / "ports" / "ps4" / "repeat_control.py"
    if not script.is_file():
        raise ValueError("No está instalado el control experimental de PS4 en esta copia del proyecto.")
    command = [sys.executable, str(script), "--host", host, "--revision", str(revision), "--panel"]
    process = subprocess.Popen(command, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    path = data_dir / "ps4-menu-control.json"
    temporary = path.with_suffix(".tmp")
    try:
        # Configuration failure must not conceal an already opened control panel.
        if not temporary.exists():
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump({"host": host, "revision": revision}, stream)
            temporary.replace(path)
    except OSError:
        pass
    return process
