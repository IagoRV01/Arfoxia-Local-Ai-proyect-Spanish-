"""Explicit owner-selected Windows elevation, retaining the normal UAC boundary."""
from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path
from xml.etree import ElementTree

ADMIN_TASK_NAME = "Arfoxia Companion (Administrador)"


def is_administrator() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def launch_as_administrator(project_root: Path, arguments: list[str]) -> bool:
    pythonw = project_root / ".venv/Scripts/pythonw.exe"
    launcher = project_root / "launcher.pyw"
    if not pythonw.is_file() or not launcher.is_file():
        return False
    # Reuse only the exact task explicitly registered by the owner via UAC.
    # Alternate data/API arguments must go through a fresh UAC launch instead.
    if not arguments:
        try:
            result = subprocess.run(
                ["schtasks.exe", "/Query", "/TN", ADMIN_TASK_NAME, "/XML"],
                capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                # schtasks declares UTF-16 even when redirected stdout uses
                # the console OEM codepage. Parse Unicode, not that declaration.
                encoding = ("utf-16" if result.stdout.startswith((b'\xff\xfe', b'\xfe\xff'))
                            else "oem" if os.name == "nt" else "utf-8")
                root = ElementTree.fromstring(result.stdout.decode(encoding))
                commands = root.findall(".//{*}Exec/{*}Command")
                args = root.findall(".//{*}Exec/{*}Arguments")
                if (len(commands) == len(args) == 1
                        and os.path.normcase(commands[0].text or "") == os.path.normcase(str(pythonw))
                        and args[0].text == subprocess.list2cmdline([str(launcher)])):
                    started = subprocess.run(["schtasks.exe", "/Run", "/TN", ADMIN_TASK_NAME],
                        capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if started.returncode == 0:
                        return True
        except (OSError, ValueError, ElementTree.ParseError, subprocess.TimeoutExpired):
            pass
    # Windows itself asks for elevation. Never simulate or auto-accept UAC.
    parameters = subprocess.list2cmdline([str(launcher), *arguments])
    return ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(pythonw), parameters, str(project_root), 0
    ) > 32
