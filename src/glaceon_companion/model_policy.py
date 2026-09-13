from __future__ import annotations

import csv
import ntpath
import subprocess
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from io import StringIO
from typing import Any, Literal, Protocol

import psutil


MIB = 1024**2
NVIDIA_SMI_PATH = r"C:\Windows\System32\nvidia-smi.exe"
NVIDIA_SMI_COMMAND = (
    NVIDIA_SMI_PATH,
    (
        "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,"
        "utilization.gpu,temperature.gpu"
    ),
    "--format=csv,noheader,nounits",
)

# These markers identify installed game payloads, not merely a running store.
# They intentionally avoid broad paths such as ``WindowsApps``, which contain
# many ordinary applications.
GAME_LIBRARY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("steam", ("\\steamapps\\common\\",)),
    ("epic", ("\\epic games\\", "\\epicgames\\")),
    ("xbox", ("\\xboxgames\\", "\\modifiablewindowsapps\\")),
    ("gog", ("\\gog games\\", "\\gog galaxy\\games\\")),
    (
        "ubisoft",
        (
            "\\ubisoft\\ubisoft game launcher\\games\\",
            "\\ubisoft game launcher\\games\\",
        ),
    ),
    ("ea", ("\\ea games\\", "\\origin games\\")),
    ("riot", ("\\riot games\\",)),
)

EXCLUDED_GAME_PROCESSES = frozenset(
    {
        "eabackgroundservice.exe",
        "eadesktop.exe",
        "ealink.exe",
        "epicgameslauncher.exe",
        "epicwebhelper.exe",
        "eosoverlayrenderer-win64-shipping.exe",
        "eosoverlayrenderer-win32-shipping.exe",
        "gamebar.exe",
        "gamebarftserver.exe",
        "gameoverlayui.exe",
        "galaxyclient.exe",
        "galaxyclient helper.exe",
        "gamingservices.exe",
        "gamingservicesnet.exe",
        "goggalaxy.exe",
        "origin.exe",
        "riotclientservices.exe",
        "riotclientux.exe",
        "riotclientuxrender.exe",
        "steam.exe",
        "steamservice.exe",
        "steamwebhelper.exe",
        "ubisoftconnect.exe",
        "ubisoftconnectwebcore.exe",
        "ubisoftgamelauncher.exe",
        "upc.exe",
        "wallpaper32.exe",
        "wallpaper64.exe",
        "webwallpaper32.exe",
        "xboxpcapp.exe",
    }
)
EXCLUDED_PROCESS_NAME_PARTS = (
    "bootstrap",
    "crashpad",
    "crashreport",
    "helper",
    "launcher",
    "unins",
    "updater",
)


class CommandRunner(Protocol):
    def __call__(
        self, command: Sequence[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class GpuDevice:
    index: int
    total_vram_mib: int
    free_vram_mib: int
    uuid: str = ""
    name: str = ""
    used_vram_mib: int | None = None
    utilization_percent: float | None = None
    temperature_c: float | None = None

    @property
    def effective_used_vram_mib(self) -> int:
        if self.used_vram_mib is None:
            return max(0, self.total_vram_mib - self.free_vram_mib)
        return max(0, self.used_vram_mib)


@dataclass(frozen=True, slots=True)
class GpuSnapshot:
    devices: tuple[GpuDevice, ...] = ()
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.error is None and bool(self.devices)

    @property
    def total_vram_mib(self) -> int:
        return sum(device.total_vram_mib for device in self.devices)

    @property
    def free_vram_mib(self) -> int:
        return sum(device.free_vram_mib for device in self.devices)

    def for_uuid(self, gpu_uuid: str | None = None) -> GpuSnapshot:
        """Return only the configured physical GPU, or the full snapshot if unset."""

        requested = str(gpu_uuid or "").strip().casefold()
        if not requested or not self.available:
            return self
        matches = tuple(
            device
            for device in self.devices
            if device.uuid.strip().casefold() == requested
        )
        if len(matches) != 1:
            return self.failed("configured NVIDIA GPU UUID was not found")
        return GpuSnapshot(devices=matches)

    @classmethod
    def failed(cls, error: str) -> GpuSnapshot:
        return cls(error=error.strip() or "GPU probe failed")


@dataclass(frozen=True, slots=True)
class GameProcess:
    pid: int
    name: str
    executable: str
    source: str


@dataclass(frozen=True, slots=True)
class GameSnapshot:
    active: bool
    processes: tuple[GameProcess, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeModel:
    name: str
    size_vram_bytes: int
    size_bytes: int = 0

    @property
    def size_vram_mib(self) -> int:
        return max(0, int(self.size_vram_bytes)) // MIB

    @property
    def gpu_percent(self) -> float:
        total = max(0, int(self.size_bytes))
        if total <= 0:
            return 0.0
        return min(100.0, max(0.0, self.size_vram_bytes * 100.0 / total))


SelectionTier = Literal["small", "large", "power", "gaming_gpu", "dual"]
SelectionReason = Literal[
    "adaptive_disabled",
    "config_invalid",
    "large_runtime_failed",
    "game_active",
    "large_not_installed",
    "gpu_unavailable",
    "insufficient_vram",
    "large_fits",
    "large_fits_after_reclaim",
    "power_selected",
    "power_runtime_failed",
    "gaming_gpu_selected",
    "gaming_gpu_runtime_failed",
    "dual_selected",
    "dual_runtime_failed",
]


@dataclass(frozen=True, slots=True)
class ModelSelection:
    model: str
    tier: SelectionTier
    reason: SelectionReason
    gpu_free_vram_mib: int
    effective_free_vram_mib: int
    reclaimable_large_vram_mib: int
    large_required_vram_mib: int
    game_active: bool


def parse_nvidia_smi_output(output: str) -> GpuSnapshot:
    """Parse the fixed ``nvidia-smi`` CSV query as one aggregate snapshot."""

    devices: list[GpuDevice] = []
    seen_indexes: set[int] = set()
    seen_uuids: set[str] = set()
    try:
        rows = csv.reader(StringIO(str(output)))
        for row in rows:
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) not in {4, 8}:
                raise ValueError("unexpected column count")
            index = int(row[0].strip())
            uuid = row[1].strip()
            normalized_uuid = uuid.casefold()
            if len(row) == 8:
                name = row[2].strip()
                total_vram_mib = int(row[3].strip())
                used_vram_mib = int(row[4].strip())
                free_vram_mib = int(row[5].strip())
                utilization_percent = float(row[6].strip())
                temperature_c = float(row[7].strip())
            else:
                # Retain compatibility with the original memory-only probe
                # payload used by older installations and focused tests.
                name = ""
                total_vram_mib = int(row[2].strip())
                used_vram_mib = total_vram_mib - int(row[3].strip())
                free_vram_mib = int(row[3].strip())
                utilization_percent = None
                temperature_c = None
            if (
                index < 0
                or index in seen_indexes
                or not uuid
                or normalized_uuid in seen_uuids
                or total_vram_mib <= 0
                or used_vram_mib < 0
                or free_vram_mib < 0
                or free_vram_mib > total_vram_mib
                or used_vram_mib > total_vram_mib
                # NVIDIA may reserve a few hundred MiB that is reported as
                # neither used nor free under WDDM.
                or used_vram_mib + free_vram_mib > total_vram_mib + 64
                or (
                    utilization_percent is not None
                    and not 0 <= utilization_percent <= 100
                )
                or (
                    temperature_c is not None
                    and not -50 <= temperature_c <= 150
                )
            ):
                raise ValueError("invalid GPU memory values")
            seen_indexes.add(index)
            seen_uuids.add(normalized_uuid)
            devices.append(
                GpuDevice(
                    index=index,
                    total_vram_mib=total_vram_mib,
                    free_vram_mib=free_vram_mib,
                    uuid=uuid,
                    name=name,
                    used_vram_mib=used_vram_mib,
                    utilization_percent=utilization_percent,
                    temperature_c=temperature_c,
                )
            )
    except (TypeError, ValueError):
        return GpuSnapshot.failed("nvidia-smi returned malformed GPU data")

    if not devices:
        return GpuSnapshot.failed("nvidia-smi returned no GPUs")
    return GpuSnapshot(devices=tuple(sorted(devices, key=lambda device: device.index)))


def probe_nvidia_gpus(
    gpu_uuid: str | None = None,
    *,
    runner: CommandRunner = subprocess.run,
) -> GpuSnapshot:
    """Read NVIDIA VRAM without a shell, dynamic arguments or a PATH lookup."""

    try:
        completed = runner(
            NVIDIA_SMI_COMMAND,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return GpuSnapshot.failed(f"nvidia-smi probe failed: {type(exc).__name__}")
    return parse_nvidia_smi_output(completed.stdout).for_uuid(gpu_uuid)


def _normalize_windows_path(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return ntpath.normcase(ntpath.normpath(text)) if text else ""


def _process_basename(name: Any, executable: Any) -> str:
    normalized_name = _normalize_windows_path(name)
    if normalized_name:
        return ntpath.basename(normalized_name)
    return ntpath.basename(_normalize_windows_path(executable))


def _explicit_process_names(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        basename
        for value in values
        if (basename := ntpath.basename(_normalize_windows_path(value)))
    )


def _library_source(executable: str) -> str | None:
    for source, markers in GAME_LIBRARY_MARKERS:
        if any(marker in executable for marker in markers):
            return source
    return None


def _excluded_process(name: str) -> bool:
    return name in EXCLUDED_GAME_PROCESSES or any(
        marker in name for marker in EXCLUDED_PROCESS_NAME_PARTS
    )


def detect_game_processes(
    explicit_executables: Iterable[str] = (),
    *,
    process_iter: Callable[..., Iterable[Any]] = psutil.process_iter,
) -> GameSnapshot:
    """Detect game payloads while ignoring the stores and their helpers."""

    explicit_names = _explicit_process_names(explicit_executables)
    matches: list[GameProcess] = []
    error: str | None = None
    try:
        processes = process_iter(["pid", "name", "exe"])
        for process in processes:
            try:
                info = process.info
                executable = _normalize_windows_path(info.get("exe"))
                name = _process_basename(info.get("name"), executable)
                try:
                    pid = int(info.get("pid", getattr(process, "pid", 0)))
                except (TypeError, ValueError):
                    continue
                if pid <= 0 or not name:
                    continue

                source: str | None = None
                if name in explicit_names:
                    source = "explicit"
                elif _excluded_process(name):
                    continue
                elif executable:
                    source = _library_source(executable)
                if source is not None:
                    matches.append(
                        GameProcess(
                            pid=pid,
                            name=name,
                            executable=executable,
                            source=source,
                        )
                    )
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
    except (psutil.Error, OSError) as exc:
        error = f"process probe failed: {type(exc).__name__}"

    ordered = tuple(sorted(matches, key=lambda item: (item.pid, item.name)))
    return GameSnapshot(active=bool(ordered), processes=ordered, error=error)


def _normalized_model_name(value: str) -> str:
    return str(value or "").strip().casefold()


def select_model(
    *,
    small_model: str,
    large_model: str,
    large_required_vram_mib: int,
    installed_models: Iterable[str],
    gpu: GpuSnapshot,
    game: GameSnapshot,
    runtime_models: Iterable[RuntimeModel] = (),
) -> ModelSelection:
    """Choose one configured model without performing I/O or changing runtime state."""

    small_model = str(small_model or "").strip()
    large_model = str(large_model or "").strip()
    if not small_model or not large_model or small_model.casefold() == large_model.casefold():
        raise ValueError("small_model and large_model must be distinct non-empty names")
    if (
        isinstance(large_required_vram_mib, bool)
        or not isinstance(large_required_vram_mib, int)
        or large_required_vram_mib < 0
    ):
        raise ValueError("large_required_vram_mib must be a non-negative integer")

    installed = {
        normalized
        for model in installed_models
        if (normalized := _normalized_model_name(model))
    }
    normalized_large = _normalized_model_name(large_model)
    free_vram_mib = gpu.free_vram_mib if gpu.available else 0

    def small(reason: SelectionReason) -> ModelSelection:
        return ModelSelection(
            model=small_model,
            tier="small",
            reason=reason,
            gpu_free_vram_mib=free_vram_mib,
            effective_free_vram_mib=free_vram_mib,
            reclaimable_large_vram_mib=0,
            large_required_vram_mib=large_required_vram_mib,
            game_active=game.active,
        )

    if game.active:
        return small("game_active")
    if normalized_large not in installed:
        return small("large_not_installed")
    if not gpu.available:
        return small("gpu_unavailable")

    reclaimable_vram_mib = sum(
        runtime.size_vram_mib
        for runtime in runtime_models
        if _normalized_model_name(runtime.name) == normalized_large
    )
    effective_free_vram_mib = min(
        gpu.total_vram_mib,
        free_vram_mib + reclaimable_vram_mib,
    )
    if effective_free_vram_mib < large_required_vram_mib:
        return ModelSelection(
            model=small_model,
            tier="small",
            reason="insufficient_vram",
            gpu_free_vram_mib=free_vram_mib,
            effective_free_vram_mib=effective_free_vram_mib,
            reclaimable_large_vram_mib=reclaimable_vram_mib,
            large_required_vram_mib=large_required_vram_mib,
            game_active=False,
        )

    reason: SelectionReason = (
        "large_fits_after_reclaim" if reclaimable_vram_mib else "large_fits"
    )
    return ModelSelection(
        model=large_model,
        tier="large",
        reason=reason,
        gpu_free_vram_mib=free_vram_mib,
        effective_free_vram_mib=effective_free_vram_mib,
        reclaimable_large_vram_mib=reclaimable_vram_mib,
        large_required_vram_mib=large_required_vram_mib,
        game_active=False,
    )
