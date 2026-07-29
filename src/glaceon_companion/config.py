from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "GlaceonCompanion"


@dataclass(slots=True)
class AppEntry:
    command: list[str]
    processes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CompanionConfig:
    name: str = "Arfoxia"
    species: str = "Glaceon"
    gender: str = "male"
    owner_name: str = "Gori"
    language: str = "auto"
    supported_languages: list[str] = field(default_factory=lambda: ["es", "en", "gl"])
    model: str = "qwen3.5:4b"
    adaptive_model_enabled: bool = True
    large_model: str = "qwen3.5:9b-q4_K_M"
    large_model_vram_threshold_gb: float = 12.0
    power_model: str = "qwen3.6:27b-q4_K_M"
    power_context_tokens: int = 8192
    power_keep_alive: str = "-1"
    ai_gpu_uuid: str = "GPU-1ad4d697-126f-1101-233d-e079c4eb6f3b"
    gaming_gpu_uuid: str = "GPU-a068595b-3e42-ee40-6292-5572abbbdc72"
    gaming_gpu_model: str = "qwen3.5:4b"
    gaming_gpu_ollama_url: str = "http://127.0.0.1:11435"
    gaming_gpu_context_tokens: int = 4096
    gaming_gpu_keep_alive: str = "-1"
    gaming_gpu_server_start_timeout_seconds: float = 30.0
    power_secondary_gpu_limit_gb: float = 2.0
    ollama_url: str = "http://127.0.0.1:11434"
    context_tokens: int = 4096
    large_context_tokens: int = 32768
    keep_alive: str = "5m"
    large_keep_alive: str = "-1"
    model_residency_version: int = 1
    game_processes: list[str] = field(default_factory=list)
    small_attachment_text_chars: int = 8000
    large_attachment_text_chars: int = 24000
    chat_storage_limit_gb: float = 150.0
    chat_storage_min_free_gb: float = 20.0
    cross_chat_memory_enabled: bool = True
    cross_chat_memory_results: int = 6
    api_host: str = "127.0.0.1"
    api_port: int = 8742
    mobile_dev_server_enabled: bool = True
    mobile_dev_server_port: int = 8081
    mobile_dev_server_host: str = "pciagorv.tail122075.ts.net"
    sprite_variant: str = "default"
    sprite_scale: int = 4
    always_on_top: bool = True
    start_minimized: bool = False
    sound_enabled: bool = True
    sound_volume: float = 0.42
    sound_cooldown_ms: int = 2200
    bubble_max_chars: int = 180
    bubble_duration_ms: int = 6200
    quick_chat_inactivity_ms: int = 15_000
    eevee_companion_enabled: bool = True
    eevee_presence_poll_ms: int = 2_500
    eevee_interaction_interval_ms: int = 120_000
    eevee_avoidance_padding: int = 24
    bed_enabled: bool = False
    bed_screen_name: str = ""
    bed_x_ratio: float = 0.78
    bed_y_ratio: float = 0.72
    online_search_enabled: bool = True
    online_search_max_results: int = 5
    codex_bridge_enabled: bool = True
    # Power changes are available, but shutdown/restart are still gated by the
    # local one-use authorization challenge in CompanionService.
    allow_power_actions: bool = True
    privileged_actions_version: int = 1
    screenshot_retention_hours: int = 24
    apps: dict[str, AppEntry] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> "CompanionConfig":
        user = os.environ.get("USERNAME", "Iago")
        local = Path(os.environ.get("LOCALAPPDATA", f"C:/Users/{user}/AppData/Local"))
        roaming = Path(os.environ.get("APPDATA", f"C:/Users/{user}/AppData/Roaming"))
        candidates: dict[str, AppEntry] = {
            "steam": AppEntry(
                [r"C:\Program Files (x86)\Steam\steam.exe"], ["steam.exe"]
            ),
            "discord": AppEntry(
                [str(local / "Discord" / "Update.exe"), "--processStart", "Discord.exe"],
                ["Discord.exe"],
            ),
            "chrome": AppEntry(
                [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
                ["chrome.exe"],
            ),
            "explorador": AppEntry(["explorer.exe"], ["explorer.exe"]),
            "calculadora": AppEntry(
                [
                    "explorer.exe",
                    r"shell:AppsFolder\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
                ],
                ["CalculatorApp.exe", "Calculator.exe"],
            ),
            "chatgpt": AppEntry(
                [
                    "explorer.exe",
                    r"shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App",
                ],
                ["ChatGPT.exe"],
            ),
            "codex": AppEntry(
                [
                    "explorer.exe",
                    r"shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App",
                ],
                ["ChatGPT.exe"],
            ),
        }
        spotify = roaming / "Spotify" / "Spotify.exe"
        if spotify.exists():
            candidates["spotify"] = AppEntry([str(spotify)], ["Spotify.exe"])
        return cls(apps=candidates)


class ConfigStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or default_data_dir()).resolve()
        self.path = self.data_dir / "config.json"
        self.secrets_path = self.data_dir / "secrets.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> CompanionConfig:
        if not self.path.exists():
            config = CompanionConfig.defaults()
            self.save(config)
            return config
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        migrated = False
        if raw.get("name") == "Glaceon":
            raw["name"] = "Arfoxia"
            migrated = True
        if "species" not in raw:
            raw["species"] = "Glaceon"
            migrated = True
        if "gender" not in raw:
            raw["gender"] = "male"
            migrated = True
        if "owner_name" not in raw:
            raw["owner_name"] = "Gori"
            migrated = True
        # Older builds stored "es" even though the conversation layer now
        # chooses es/en/gl from each current message (with Spanish as fallback).
        if raw.get("language") == "es":
            raw["language"] = "auto"
            migrated = True
        if "supported_languages" not in raw:
            raw["supported_languages"] = ["es", "en", "gl"]
            migrated = True
        for key in (
            "online_search_enabled",
            "online_search_max_results",
            "codex_bridge_enabled",
            "quick_chat_inactivity_ms",
            "eevee_companion_enabled",
            "eevee_presence_poll_ms",
            "eevee_interaction_interval_ms",
            "eevee_avoidance_padding",
            "bed_enabled",
            "bed_screen_name",
            "bed_x_ratio",
            "bed_y_ratio",
            "adaptive_model_enabled",
            "large_model",
            "large_model_vram_threshold_gb",
            "large_context_tokens",
            "large_keep_alive",
            "power_model",
            "power_context_tokens",
            "power_keep_alive",
            "ai_gpu_uuid",
            "gaming_gpu_uuid",
            "gaming_gpu_model",
            "gaming_gpu_ollama_url",
            "gaming_gpu_context_tokens",
            "gaming_gpu_keep_alive",
            "gaming_gpu_server_start_timeout_seconds",
            "power_secondary_gpu_limit_gb",
            "game_processes",
            "small_attachment_text_chars",
            "large_attachment_text_chars",
            "chat_storage_limit_gb",
            "chat_storage_min_free_gb",
            "cross_chat_memory_enabled",
            "cross_chat_memory_results",
            "mobile_dev_server_enabled",
            "mobile_dev_server_port",
            "mobile_dev_server_host",
        ):
            if key not in raw:
                migrated = True
        if int(raw.get("privileged_actions_version", 0)) < 1:
            # v0.6 enables the power implementation requested by the owner.
            # The version marker makes this a one-time migration: choosing to
            # disable it again afterwards remains respected.
            raw["allow_power_actions"] = True
            raw["privileged_actions_version"] = 1
            migrated = True
        if int(raw.get("model_residency_version", 0)) < 1:
            # Older builds evicted the adaptive large model after two idle
            # minutes. Migrate once to explicit-only release while allowing a
            # later manual configuration change to remain respected.
            raw["large_keep_alive"] = "-1"
            raw["power_keep_alive"] = "-1"
            raw["model_residency_version"] = 1
            migrated = True
        configured_apps = {
            key: AppEntry(**value) for key, value in raw.get("apps", {}).items()
        }
        default_config = CompanionConfig.defaults()
        for key, entry in default_config.apps.items():
            if key not in configured_apps:
                configured_apps[key] = entry
                migrated = True
        raw["apps"] = configured_apps
        defaults = asdict(default_config)
        defaults.update(raw)
        config = CompanionConfig(**defaults)
        if migrated:
            self.save(config)
        return config

    def save(self, config: CompanionConfig) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def api_token(self) -> str:
        # Imported lazily to keep configuration loading independent from the
        # authorization subsystem while reusing its exact-file ACL hardening.
        from .auth import harden_authorization_file

        if self.secrets_path.exists():
            value = json.loads(self.secrets_path.read_text(encoding="utf-8"))
            if value.get("api_token"):
                harden_authorization_file(self.secrets_path)
                return str(value["api_token"])
        token = secrets.token_urlsafe(32)
        self.secrets_path.write_text(
            json.dumps({"api_token": token}, indent=2), encoding="utf-8"
        )
        harden_authorization_file(self.secrets_path)
        return token

    def public_config(self, config: CompanionConfig) -> dict[str, Any]:
        value = asdict(config)
        value.pop("ollama_url", None)
        return value
