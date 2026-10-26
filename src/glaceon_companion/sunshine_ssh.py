"""PIN-only access to the locally registered BC-250, never arbitrary hosts."""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from .config import ConfigStore
from .game_streaming import GameStreamingError


class SunshineSSHError(GameStreamingError):
    pass


class SunshineSSHBridge:
    def __init__(self, store: ConfigStore, travel):
        self.store = store
        self.travel = travel

    def available(self):
        return self.travel is not None and "bc250" in self.travel.devices

    def _rpc(self, operation, *, credentials=None, pin=None, name=None):
        if not self.available():
            raise SunshineSSHError("La BC-250 no está registrada por SSH en Paseo entre dispositivos.")
        alias = self.travel.devices["bc250"]["ssh_alias"]
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", alias):
            raise SunshineSSHError("El alias SSH de la BC-250 no es válido.")
        ssh = shutil.which("ssh")
        if not ssh:
            raise SunshineSSHError("OpenSSH no está disponible en este PC.")
        script = Path(__file__).with_name("remote_sunshine_agent.py").read_text(encoding="utf-8")
        request = {"operation": operation}
        if credentials:
            request.update(username=credentials[0], password=credentials[1])
        if operation == "pair":
            request.update(pin=pin, name=name)
        command = [ssh, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
            alias, "python3 -c " + shlex.quote(script)]
        try:
            result = subprocess.run(command, input=json.dumps(request), capture_output=True,
                encoding="utf-8", errors="replace", timeout=28, shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode or len(result.stdout) > 65536:
                raise ValueError("SSH failed")
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or type(value.get("success")) is not bool:
                raise ValueError("Invalid bridge reply")
            return value
        except (OSError, ValueError, subprocess.SubprocessError) as from_error:
            raise SunshineSSHError("No se pudo consultar Sunshine en la BC-250 por el SSH configurado.") from from_error

    def status(self, credentials=None):
        saved = credentials if credentials is not None else self.store.sunshine_credentials("bc250")
        value = self._rpc("status", credentials=saved)
        if not value.get("success"):
            raise SunshineSSHError("El puente privado de Sunshine no ha podido consultar la BC-250.")
        value = {key: value.get(key) for key in ("ports", "running", "web_ready", "host",
            "tailscale_ip", "tailscale_ready", "credentials_verified", "credential_check", "paired_clients", "paired_device_names")}
        from .game_streaming import MOONLIGHT_APP_STORE_URL
        ready = bool(value.get("running"))
        verified = value.get("credentials_verified") is True
        return {**value, "target": "bc250", "target_label": "BC-250 · Bazzite",
            "enabled": True, "installed": ready or bool(value.get("web_ready")),
            "service_status": "running" if ready else "unavailable", "sunshine_ready": ready,
            "ready": ready and bool(value.get("host")), "remote_ready": ready and bool(value.get("tailscale_ready")),
            "credentials_managed": saved is not None, "pin_submission_available": ready and verified,
            "pairing_available": ready and verified, "paired": int(value.get("paired_clients", 0)) > 0,
            "gamepad_ready": False, "capture_gpu": "GPU AMD de la BC-250 (configuración de Sunshine)",
            "moonlight_app_store_url": MOONLIGHT_APP_STORE_URL, "wake_available": False,
            "wake_reason": "La BC-250 debe estar encendida. El PIN se envía por SSH, sin abrir su panel en Internet.",
            "message": ("Sunshine de la BC-250 listo para recibir el PIN." if verified else
                "Autoriza Sunshine de la BC-250 una vez desde el cuadro privado de Windows.")}

    def configure(self, username, password):
        if not isinstance(username, str) or not username.strip() or ":" in username or len(username) > 128:
            raise SunshineSSHError("Indica un usuario válido de Sunshine.")
        if not isinstance(password, str) or not password or len(password) > 4096:
            raise SunshineSSHError("Indica la contraseña de Sunshine.")
        credentials = (username.strip(), password)
        status = self.status(credentials)
        if not status["credentials_verified"]:
            reason = {"unauthorized": "Sunshine rechaza el usuario o la contraseña. Usa la cuenta del panel Sunshine, no la contraseña de Bazzite ni la del PC Windows.",
                "forbidden": "Sunshine rechaza la conexión local de su API (HTTP 403). No es una comprobación válida de tu contraseña.",
                "unsupported_api": "Sunshine no ofrece el endpoint de clientes esperado (HTTP 404).",
                "unreachable": "No se pudo conectar con el panel local de Sunshine.",
                "invalid_response": "El panel de Sunshine respondió con un formato inesperado.",
                "server_error": "El panel de Sunshine devolvió un error del servidor."}.get(status.get("credential_check"), "Sunshine no acepta esas credenciales.")
            raise SunshineSSHError(reason + " No se ha cambiado ninguna cuenta ni guardado esta contraseña.")
        self.store.save_sunshine_credentials(*credentials, target="bc250")
        return status

    def pair(self, pin, name):
        if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4}", pin):
            raise SunshineSSHError("El PIN de Moonlight debe tener exactamente 4 cifras.")
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise SunshineSSHError("El nombre del cliente Moonlight no es válido.")
        credentials = self.store.sunshine_credentials("bc250")
        if credentials is None:
            raise SunshineSSHError("Autoriza primero la cuenta de Sunshine de la BC-250 en el cuadro privado de Windows.")
        value = self._rpc("pair", credentials=credentials, pin=pin, name=name)
        if not value.get("success"):
            raise SunshineSSHError("Sunshine de la BC-250 no confirmó el PIN. Mantén abierta la solicitud de Moonlight y revisa las credenciales.")
        try:
            status = self.status()
        except SunshineSSHError:
            # POST is not idempotent: never imply it wasn't sent or retry it
            # just because the subsequent read-only status check failed.
            return {"target": "bc250", "message": "Sunshine aceptó el PIN de la BC-250, pero no pude actualizar el estado. Comprueba Moonlight antes de volver a intentarlo."}
        status["message"] = "PIN enviado a Sunshine de la BC-250. Vuelve a Moonlight para comprobar el emparejamiento."
        return status
