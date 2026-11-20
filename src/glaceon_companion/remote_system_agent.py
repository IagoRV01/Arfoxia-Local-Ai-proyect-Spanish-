"""Read-only Linux telemetry; runs over the registered SSH connection, stdlib only."""

import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import time


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def number(path, divisor=1):
    try:
        value = float(read(path)) / divisor
        return round(value, 2) if math.isfinite(value) and value >= 0 else None
    except ValueError:
        return None


def cpu_ticks(proc):
    fields = read(proc / "stat").splitlines()[0].split()
    values = [int(value) for value in fields[1:9]]
    return sum(values), values[3] + values[4]


def collect(proc=Path("/proc"), sys=Path("/sys"), etc=Path("/etc"), sleep=time.sleep, disk_path=None):
    first = cpu_ticks(proc)
    sleep(0.2)
    last = cpu_ticks(proc)
    delta = last[0] - first[0]
    cpu = round(max(0, min(100, 100 * (1 - (last[1] - first[1]) / delta))), 1) if delta > 0 else None
    memory = {}
    for line in read(proc / "meminfo").splitlines():
        key, _, value = line.partition(":")
        if value.split():
            memory[key] = int(value.split()[0]) * 1024
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable")
    cpuinfo = read(proc / "cpuinfo")
    names = re.findall(r"^model name\s*:\s*(.+)$", cpuinfo, re.M)
    cores = re.findall(r"^processor\s*:", cpuinfo, re.M)
    os_release = {}
    for line in read(etc / "os-release").splitlines():
        key, _, value = line.partition("=")
        os_release[key] = value.strip('"')
    # Bazzite's immutable composefs root is tiny and normally reports 100%.
    # The home filesystem is the useful capacity for games and user data.
    disk_path = disk_path or next((p for p in ("/var/home", "/home", "/var", "/") if Path(p).is_dir()), "/")
    disk = shutil.disk_usage(disk_path)
    status = {
        "hostname": platform.node(), "os_name": os_release.get("PRETTY_NAME", platform.system()),
        "cpu_name": names[0] if names else platform.machine(),
        "cpu_logical_cores": len(cores) or os.cpu_count(), "cpu_percent": cpu,
        "uptime_seconds": float(read(proc / "uptime").split()[0]),
        "memory_total_gb": round(total / 1024**3, 2),
        "memory_available_gb": round(available / 1024**3, 2) if available is not None else None,
        "memory_used_gb": round((total - available) / 1024**3, 2) if available is not None else None,
        "memory_percent": round(100 * (total - available) / total, 1) if total and available is not None else None,
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "disk_used_gb": round(disk.used / 1024**3, 2),
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "disk_percent": round(disk.used * 100 / disk.total, 1) if disk.total else None,
        "disk_path": str(disk_path),
        "gpus": [],
    }
    for sensor in sorted((sys / "class/hwmon").glob("hwmon*")):
        if read(sensor / "name") in {"k10temp", "zenpower"}:
            status["cpu_temperature_c"] = number(sensor / "temp1_input", 1000)
            break
    seen = set()
    for card in sorted((sys / "class/drm").glob("card*")):
        if not re.fullmatch(r"card\d+", card.name):
            continue
        device = card / "device"
        identity = str(device.resolve())
        if identity in seen or read(device / "vendor") != "0x1002":
            continue
        seen.add(identity)
        hwmon = next(iter(sorted((device / "hwmon").glob("hwmon*"))), None)
        gpu = {
            "name": ("AMD BC-250 · " if names and "BC-250" in names[0] else "AMD · ") + card.name,
            "utilization_percent": number(device / "gpu_busy_percent"),
            "memory_used_mb": number(device / "mem_info_vram_used", 1024**2),
            "memory_total_mb": number(device / "mem_info_vram_total", 1024**2),
            "temperature_c": number(hwmon / "temp1_input", 1000) if hwmon else None,
            # AMD APU power is the SoC reading, not necessarily GPU-only.
            "soc_power_w": number(hwmon / "power1_average", 1000000) if hwmon else None,
        }
        status["gpus"].append(gpu)
    return status


if __name__ == "__main__":
    try:
        print(json.dumps({"success": True, "status": collect()}, allow_nan=False))
    except (OSError, ValueError, IndexError, ZeroDivisionError):
        print(json.dumps({"success": False}))
