import json

from glaceon_companion.config import CompanionConfig, ConfigStore


def test_identity_defaults_are_arfoxia_male_and_trilingual():
    config = CompanionConfig.defaults()

    assert config.name == "Arfoxia"
    assert config.species == "Glaceon"
    assert config.gender == "male"
    assert config.owner_name == "Gori"
    assert config.language == "auto"
    assert config.supported_languages == ["es", "en", "gl"]
    assert config.quick_chat_inactivity_ms == 15_000
    assert config.eevee_companion_enabled is True
    assert config.bed_enabled is False
    assert config.adaptive_model_enabled is True
    assert config.large_model == "qwen3.5:9b-q4_K_M"
    assert config.large_model_vram_threshold_gb == 12.0
    assert config.large_context_tokens == 32768
    assert config.large_keep_alive == "-1"
    assert config.model_residency_version == 1
    assert config.power_model == "qwen3.6:27b-q4_K_M"
    assert config.power_context_tokens == 8192
    assert config.power_keep_alive == "-1"
    assert config.ai_gpu_uuid == "GPU-1ad4d697-126f-1101-233d-e079c4eb6f3b"
    assert config.gaming_gpu_uuid == "GPU-a068595b-3e42-ee40-6292-5572abbbdc72"
    assert config.gaming_gpu_model == "qwen3.5:4b"
    assert config.gaming_gpu_ollama_url == "http://127.0.0.1:11435"
    assert config.gaming_gpu_context_tokens == 4096
    assert config.gaming_gpu_keep_alive == "-1"
    assert config.power_secondary_gpu_limit_gb == 2.0
    assert config.mobile_dev_server_enabled is True
    assert config.mobile_dev_server_port == 8081
    assert config.mobile_dev_server_host == "pciagorv.tail122075.ts.net"


def test_legacy_glaceon_name_is_migrated_to_arfoxia(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.write_text(
        json.dumps({"name": "Glaceon", "language": "es", "apps": {}}),
        encoding="utf-8",
    )

    config = store.load()

    assert config.name == "Arfoxia"
    assert config.gender == "male"
    assert config.owner_name == "Gori"
    assert config.language == "auto"
    assert config.supported_languages == ["es", "en", "gl"]
    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    assert persisted["name"] == "Arfoxia"
    assert persisted["gender"] == "male"
    assert persisted["owner_name"] == "Gori"
    assert persisted["language"] == "auto"
    assert persisted["quick_chat_inactivity_ms"] == 15_000
    assert persisted["eevee_companion_enabled"] is True
    assert persisted["bed_enabled"] is False
    assert persisted["bed_screen_name"] == ""
    assert persisted["adaptive_model_enabled"] is True
    assert persisted["large_model"] == "qwen3.5:9b-q4_K_M"
    assert persisted["large_model_vram_threshold_gb"] == 12.0
    assert persisted["large_context_tokens"] == 32768
    assert persisted["large_keep_alive"] == "-1"
    assert persisted["model_residency_version"] == 1
    assert persisted["power_model"] == "qwen3.6:27b-q4_K_M"
    assert persisted["power_context_tokens"] == 8192
    assert persisted["power_keep_alive"] == "-1"
    assert persisted["ai_gpu_uuid"] == "GPU-1ad4d697-126f-1101-233d-e079c4eb6f3b"
    assert (
        persisted["gaming_gpu_uuid"]
        == "GPU-a068595b-3e42-ee40-6292-5572abbbdc72"
    )
    assert persisted["gaming_gpu_model"] == "qwen3.5:4b"
    assert persisted["gaming_gpu_ollama_url"] == "http://127.0.0.1:11435"
    assert persisted["gaming_gpu_context_tokens"] == 4096
    assert persisted["gaming_gpu_keep_alive"] == "-1"
    assert persisted["power_secondary_gpu_limit_gb"] == 2.0
    assert persisted["mobile_dev_server_enabled"] is True
    assert persisted["mobile_dev_server_port"] == 8081
    assert persisted["mobile_dev_server_host"] == "pciagorv.tail122075.ts.net"


def test_migration_preserves_an_existing_custom_name(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.write_text(
        json.dumps({"name": "Nébula", "language": "es", "apps": {}}),
        encoding="utf-8",
    )

    config = store.load()

    assert config.name == "Nébula"
    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    assert persisted["name"] == "Nébula"


def test_existing_config_gains_safe_chatgpt_and_codex_launchers(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.write_text(json.dumps({"name": "Arfoxia", "apps": {}}), encoding="utf-8")

    config = store.load()

    assert config.apps["chatgpt"].command[0] == "explorer.exe"
    assert config.apps["codex"].command == config.apps["chatgpt"].command
    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    assert persisted["online_search_enabled"] is True
    assert persisted["codex_bridge_enabled"] is True


def test_v06_enables_power_once_but_respects_a_later_manual_disable(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.write_text(
        json.dumps(
            {
                "name": "Arfoxia",
                "apps": {},
                "allow_power_actions": False,
            }
        ),
        encoding="utf-8",
    )

    migrated = store.load()
    assert migrated.allow_power_actions is True
    assert migrated.privileged_actions_version == 1

    migrated.allow_power_actions = False
    store.save(migrated)
    reloaded = store.load()
    assert reloaded.allow_power_actions is False
    assert reloaded.privileged_actions_version == 1


def test_model_residency_migrates_once_and_respects_later_manual_change(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.write_text(
        json.dumps(
            {
                "name": "Arfoxia",
                "apps": {},
                "large_keep_alive": "2m",
                "power_keep_alive": "5m",
            }
        ),
        encoding="utf-8",
    )

    migrated = store.load()
    assert migrated.large_keep_alive == "-1"
    assert migrated.power_keep_alive == "-1"
    assert migrated.model_residency_version == 1

    migrated.large_keep_alive = "10m"
    store.save(migrated)
    reloaded = store.load()
    assert reloaded.large_keep_alive == "10m"
    assert reloaded.model_residency_version == 1
