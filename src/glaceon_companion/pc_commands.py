"""Owner-opt-in PowerShell execution. No elevation, networking, or UAC changes."""
from __future__ import annotations

import base64
import os
import subprocess
import threading
from pathlib import Path

import psutil

MAX_OUTPUT_BYTES = 24000


def validate_command(args: dict) -> tuple[str, Path, int]:
    if set(args) - {"command", "working_directory", "timeout_seconds"}:
        raise ValueError("Argumentos de PowerShell no admitidos.")
    command = args.get("command")
    if not isinstance(command, str) or not command.strip() or len(command) > 16000 or "\0" in command:
        raise ValueError("El comando debe tener entre 1 y 16000 caracteres, sin NUL.")
    directory = args.get("working_directory", str(Path.home()))
    if not isinstance(directory, str) or "\0" in directory:
        raise ValueError("Indica un directorio de trabajo absoluto existente.")
    cwd = Path(directory)
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError("Indica un directorio de trabajo absoluto existente.")
    timeout = args.get("timeout_seconds", 60)
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("El tiempo máximo debe ser un entero entre 1 y 120 segundos.")
    return command, cwd.resolve(), timeout


def _terminate_owned(process: subprocess.Popen) -> None:
    try:
        root = psutil.Process(process.pid)
        children = root.children(recursive=True)
        for item in [root, *children]:
            try:
                item.kill()
            except psutil.Error:
                pass
        psutil.wait_procs([root, *children], timeout=3)
    except psutil.Error:
        pass


def run_command(args: dict) -> dict:
    command, cwd, timeout = validate_command(args)
    if os.name != "nt":
        raise ValueError("Esta herramienta necesita Windows.")
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = ("$ErrorActionPreference = 'Stop'; "
              "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
              "$OutputEncoding = [Console]::OutputEncoding; " + command)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    process = subprocess.Popen(
        [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = bytearray()
    output_lock = threading.Lock()
    truncated = threading.Event()

    def drain() -> None:
        try:
            while chunk := process.stdout.read(4096):
                with output_lock:
                    available = MAX_OUTPUT_BYTES - len(output)
                    output.extend(chunk[:available])
                    if len(chunk) > available:
                        truncated.set()
        finally:
            process.stdout.close()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_owned(process)
        process.wait(timeout=5)
    reader.join(timeout=2)
    with output_lock:
        text = output.decode("utf-8", errors="replace")
    return {"exit_code": process.returncode, "stdout": text,
            "timed_out": timed_out, "truncated": truncated.is_set() or reader.is_alive(),
            "working_directory": str(cwd)}
