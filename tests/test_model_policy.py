from __future__ import annotations

import subprocess

import pytest

from glaceon_companion.model_policy import (
    NVIDIA_SMI_COMMAND,
    GameProcess,
    GameSnapshot,
    GpuDevice,
    GpuSnapshot,
    RuntimeModel,
    detect_game_processes,
    parse_nvidia_smi_output,
    probe_nvidia_gpus,
    select_model,
)


class FakeProcess:
    def __init__(self, pid: int, name: str, executable: str | None) -> None:
        self.pid = pid
        self.info = {"pid": pid, "name": name, "exe": executable}


def gpu(free: int, total: int = 16_000) -> GpuSnapshot:
    return GpuSnapshot((GpuDevice(index=0, total_vram_mib=total, free_vram_mib=free),))


def idle_game() -> GameSnapshot:
    return GameSnapshot(active=False)


def selection(**overrides):
    values = {
        "small_model": "qwen3.5:4b",
        "large_model": "gpt-oss:20b",
        "large_required_vram_mib": 12_000,
        "installed_models": {"qwen3.5:4b", "gpt-oss:20b"},
        "gpu": gpu(13_000),
        "game": idle_game(),
        "runtime_models": (),
    }
    values.update(overrides)
    return select_model(**values)


def test_nvidia_probe_uses_fixed_system32_command_timeout_and_parses_all_gpus():
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "0, GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa, 16384, 8192\n"
                "1, GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb, 8192, 4096\n"
            ),
            stderr="",
        )

    snapshot = probe_nvidia_gpus(runner=runner)

    assert captured["command"] == NVIDIA_SMI_COMMAND
    assert captured["command"][0] == r"C:\Windows\System32\nvidia-smi.exe"
    assert captured["kwargs"] == {
        "capture_output": True,
        "text": True,
        "timeout": 2,
        "check": True,
        "shell": False,
    }
    assert snapshot.available
    assert [device.index for device in snapshot.devices] == [0, 1]
    assert [device.uuid for device in snapshot.devices] == [
        "GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]
    assert snapshot.total_vram_mib == 24_576
    assert snapshot.free_vram_mib == 12_288


def test_nvidia_probe_filters_by_uuid_without_putting_user_input_in_command():
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "0, GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa, 8192, 8000\n"
                "1, GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb, 16384, 15000\n"
            ),
            stderr="",
        )

    snapshot = probe_nvidia_gpus(
        " gpu-BBBBBBBB-bbbb-BBBB-bbbb-BBBBBBBBBBBB ",
        runner=runner,
    )

    assert captured["command"] == NVIDIA_SMI_COMMAND
    assert snapshot.available
    assert len(snapshot.devices) == 1
    assert snapshot.devices[0].index == 1
    assert snapshot.devices[0].uuid == "GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert snapshot.total_vram_mib == 16_384
    assert snapshot.free_vram_mib == 15_000


def test_nvidia_probe_keeps_aggregate_snapshot_when_uuid_is_empty():
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "0, GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa, 8192, 8000\n"
                "1, GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb, 16384, 15000\n"
            ),
            stderr="",
        )

    snapshot = probe_nvidia_gpus("   ", runner=runner)

    assert snapshot.available
    assert len(snapshot.devices) == 2
    assert snapshot.total_vram_mib == 24_576
    assert snapshot.free_vram_mib == 23_000


def test_nvidia_parser_exposes_per_gpu_identity_and_live_telemetry():
    snapshot = parse_nvidia_smi_output(
        "0, GPU-game, NVIDIA GeForce RTX 5060 Ti, 8151, 703, 7190, 77, 51\n"
        "1, GPU-ai, NVIDIA GeForce RTX 5060 Ti, 16311, 15878, 175, 12, 49\n"
    )

    assert snapshot.available
    gaming, ai = snapshot.devices
    assert gaming.name == "NVIDIA GeForce RTX 5060 Ti"
    assert gaming.used_vram_mib == 703
    assert gaming.effective_used_vram_mib == 703
    assert gaming.utilization_percent == 77
    assert gaming.temperature_c == 51
    assert ai.uuid == "GPU-ai"
    assert ai.total_vram_mib == 16_311


def test_nvidia_probe_fails_closed_when_configured_uuid_is_missing():
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="0, GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa, 8192, 8000\n",
            stderr="",
        )

    snapshot = probe_nvidia_gpus(
        "GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        runner=runner,
    )

    assert not snapshot.available
    assert snapshot.devices == ()
    assert snapshot.error == "configured NVIDIA GPU UUID was not found"


@pytest.mark.parametrize(
    "output",
    [
        "",
        "0, GPU-aaaaaaaa, 16384\n",
        "0, GPU-aaaaaaaa, 16384, N/A\n",
        "0, GPU-aaaaaaaa, 16384, 17000\n",
        "0, GPU-aaaaaaaa, 16384, 8000\n0, GPU-bbbbbbbb, 16384, 7000\n",
        "0, GPU-aaaaaaaa, 16384, 8000\n1, GPU-aaaaaaaa, 16384, 7000\n",
    ],
)
def test_nvidia_parser_fails_closed_on_missing_or_malformed_data(output):
    snapshot = parse_nvidia_smi_output(output)

    assert not snapshot.available
    assert snapshot.devices == ()
    assert snapshot.error


def test_nvidia_probe_fails_closed_when_command_cannot_run():
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    snapshot = probe_nvidia_gpus(runner=runner)

    assert not snapshot.available
    assert "TimeoutExpired" in snapshot.error


@pytest.mark.parametrize(
    ("source", "executable"),
    [
        ("steam", r"D:\SteamLibrary\steamapps\common\Hades\Hades.exe"),
        ("epic", r"D:\Epic Games\Fortnite\FortniteClient-Win64-Shipping.exe"),
        ("xbox", r"D:\XboxGames\Forza Horizon 5\Content\ForzaHorizon5.exe"),
        ("gog", r"D:\GOG Games\Cyberpunk 2077\bin\x64\Cyberpunk2077.exe"),
        (
            "ubisoft",
            r"C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games\Anno 1800\Bin\Anno1800.exe",
        ),
        ("ea", r"D:\EA Games\The Sims 4\Game\Bin\TS4_x64.exe"),
        ("riot", r"C:\Riot Games\VALORANT\live\VALORANT.exe"),
    ],
)
def test_game_probe_recognizes_supported_library_payloads(source, executable):
    def process_iter(attrs):
        assert attrs == ["pid", "name", "exe"]
        return [FakeProcess(41, executable.rsplit("\\", 1)[-1], executable)]

    snapshot = detect_game_processes(process_iter=process_iter)

    assert snapshot.active
    assert len(snapshot.processes) == 1
    assert snapshot.processes[0].source == source


@pytest.mark.parametrize(
    ("name", "executable"),
    [
        (
            "EpicGamesLauncher.exe",
            r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
        ),
        (
            "EOSOverlayRenderer-Win64-Shipping.exe",
            r"C:\Program Files (x86)\Epic Games\Epic Online Services\ManagedArtifacts\test\EOSOverlayRenderer-Win64-Shipping.exe",
        ),
        (
            "RiotClientServices.exe",
            r"C:\Riot Games\Riot Client\RiotClientServices.exe",
        ),
        (
            "GameLauncher.exe",
            r"D:\SteamLibrary\steamapps\common\Example\GameLauncher.exe",
        ),
        (
            "CrashReportHelper.exe",
            r"D:\EA Games\Example\CrashReportHelper.exe",
        ),
        (
            "wallpaper64.exe",
            r"C:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine\wallpaper64.exe",
        ),
    ],
)
def test_game_probe_ignores_store_launchers_and_helpers(name, executable):
    snapshot = detect_game_processes(
        process_iter=lambda attrs: [FakeProcess(52, name, executable)]
    )

    assert not snapshot.active
    assert snapshot.processes == ()


def test_game_probe_accepts_an_explicit_executable_outside_known_libraries():
    snapshot = detect_game_processes(
        ["MySpecialGame.exe"],
        process_iter=lambda attrs: [
            FakeProcess(63, "MySpecialGame.exe", r"D:\Portable\MySpecialGame.exe")
        ],
    )

    assert snapshot.active
    assert snapshot.processes[0].source == "explicit"


def test_explicit_executable_takes_precedence_over_generic_launcher_exclusion():
    snapshot = detect_game_processes(
        ["FanGameLauncher.exe"],
        process_iter=lambda attrs: [
            FakeProcess(64, "FanGameLauncher.exe", r"D:\FanGame\FanGameLauncher.exe")
        ],
    )

    assert snapshot.active
    assert snapshot.processes[0].source == "explicit"


def test_large_model_is_selected_when_installed_and_free_vram_meets_threshold():
    result = selection()

    assert result.model == "gpt-oss:20b"
    assert result.tier == "large"
    assert result.reason == "large_fits"
    assert result.effective_free_vram_mib == 13_000


def test_game_mode_forces_small_model_even_when_large_would_fit():
    game = GameSnapshot(
        active=True,
        processes=(
            GameProcess(71, "game.exe", r"D:\Steam\steamapps\common\Game\game.exe", "steam"),
        ),
    )

    result = selection(game=game)

    assert result.model == "qwen3.5:4b"
    assert result.tier == "small"
    assert result.reason == "game_active"
    assert result.game_active


def test_missing_large_model_forces_small_model():
    result = selection(installed_models={"qwen3.5:4b"})

    assert result.tier == "small"
    assert result.reason == "large_not_installed"


def test_failed_gpu_probe_forces_small_model():
    result = selection(gpu=GpuSnapshot.failed("no NVIDIA GPU"))

    assert result.tier == "small"
    assert result.reason == "gpu_unavailable"


def test_insufficient_free_vram_selects_small_model():
    result = selection(gpu=gpu(11_999))

    assert result.tier == "small"
    assert result.reason == "insufficient_vram"
    assert result.effective_free_vram_mib == 11_999


def test_loaded_large_model_vram_is_reclaimable_to_avoid_selection_thrashing():
    result = selection(
        gpu=gpu(3_500),
        runtime_models=(
            RuntimeModel("gpt-oss:20b", 9_000 * 1024**2),
            RuntimeModel("unrelated:latest", 4_000 * 1024**2),
        ),
    )

    assert result.tier == "large"
    assert result.reason == "large_fits_after_reclaim"
    assert result.gpu_free_vram_mib == 3_500
    assert result.reclaimable_large_vram_mib == 9_000
    assert result.effective_free_vram_mib == 12_500


def test_other_running_models_are_not_counted_as_reclaimable_large_vram():
    result = selection(
        gpu=gpu(8_500),
        runtime_models=(RuntimeModel("other:large", 8_000 * 1024**2),),
    )

    assert result.tier == "small"
    assert result.reason == "insufficient_vram"
    assert result.reclaimable_large_vram_mib == 0


def test_model_names_must_be_distinct_and_threshold_non_negative():
    with pytest.raises(ValueError):
        selection(large_model="QWEN3.5:4B")
    with pytest.raises(ValueError):
        selection(large_required_vram_mib=-1)
