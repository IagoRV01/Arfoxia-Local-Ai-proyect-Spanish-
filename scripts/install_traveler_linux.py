"""Finish a display-client installation uploaded through authenticated SSH.

Reads the *scoped display credential* from stdin, never argv, logs or Git.
GTK/Pillow/PyGObject must already exist. On immutable Fedora, an authenticated
gtk-layer-shell RPM can be extracted into root/deps without altering the OS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if os.geteuid() == 0:
        raise RuntimeError("Instala como el usuario del escritorio, no como root")
    root = Path.home() / ".local/share/arfoxia-traveler"
    if root.is_symlink() or not all((root / name).is_file() for name in
                                    ("traveler_linux.py", "traveler_geometry.py")):
        raise RuntimeError("Sube primero los archivos del cliente al directorio previsto")
    root.chmod(0o700)
    credential = json.load(sys.stdin)
    if set(credential) != {"token", "url"} or credential["url"] != "http://127.0.0.1:18842":
        raise RuntimeError("Configuración no válida")
    if len(credential["token"]) < 32:
        raise RuntimeError("Permiso de cliente no válido")
    path = root / "client.json"
    temp = root / "client.new"
    if path.is_symlink() or temp.is_symlink():
        raise RuntimeError("La configuración no puede ser un enlace")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(credential, stream)
    temp.chmod(0o600)
    temp.replace(path)
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "arfoxia-traveler.service"
    content = f"""# Arfoxia display-only traveler; no AI model runs here.
[Unit]
Description=Arfoxia - cliente de paseo
After=graphical-session.target
PartOf=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
ExecStart=/usr/bin/python3 {root}/traveler_linux.py --root {root}
WorkingDirectory={root}
Environment=GDK_BACKEND=wayland
Environment=GI_TYPELIB_PATH={root}/deps/usr/lib64/girepository-1.0
Environment=LD_LIBRARY_PATH={root}/deps/usr/lib64
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=graphical-session.target
"""
    if unit.is_symlink() or (unit.exists() and not unit.read_text().startswith("# Arfoxia display-only traveler;")):
        raise RuntimeError("Ya existe otro servicio: se conserva sin sobrescribir")
    unit.write_text(content)
    for command in (["systemctl", "--user", "daemon-reload"],
                    ["systemctl", "--user", "enable", "arfoxia-traveler.service"],
                    ["systemctl", "--user", "restart", "arfoxia-traveler.service"]):
        subprocess.run(command, check=True)
    print("Cliente instalado en la sesión del usuario. Permiso guardado sin mostrarlo.")


if __name__ == "__main__":
    main()
