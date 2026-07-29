import json
from pathlib import Path
from queue import Queue

import pytest

import glaceon_companion.actions as actions_module
from glaceon_companion.actions import ActionDispatcher
from glaceon_companion.config import AppEntry, CompanionConfig
from glaceon_companion.database import Database


def dispatcher(tmp_path: Path) -> ActionDispatcher:
    config = CompanionConfig.defaults()
    database = Database(tmp_path / "test.sqlite3")
    return ActionDispatcher(config, database, tmp_path, Queue())


def test_unknown_action_is_rejected(tmp_path):
    result = dispatcher(tmp_path).execute("powershell", {"command": "whoami"})
    assert not result.success
    assert "no permitida" in result.message.lower()


def test_close_requires_local_authorization(tmp_path):
    result = dispatcher(tmp_path).execute("close_app", {"app": "steam"})
    assert result.requires_authorization
    assert not result.success


def test_power_disabled_even_after_confirmation(tmp_path, monkeypatch):
    action_dispatcher = dispatcher(tmp_path)
    action_dispatcher.config.allow_power_actions = False
    monkeypatch.setattr(
        actions_module.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("Una prueba no debe ejecutar shutdown.exe"),
    )
    result = action_dispatcher.execute(
        "power", {"operation": "shutdown"}, confirmed=True
    )
    assert not result.success
    assert "desactivadas" in result.message.lower()


def test_power_reports_success_only_after_shutdown_accepts_request(tmp_path, monkeypatch):
    action_dispatcher = dispatcher(tmp_path)
    action_dispatcher.config.allow_power_actions = True
    calls = []

    class Completed:
        returncode = 0

    monkeypatch.setattr(
        actions_module.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Completed(),
    )
    result = action_dispatcher.execute_validated(
        "power", {"operation": "restart"}
    )

    assert result.success
    assert calls[0][0] == ["shutdown.exe", "/r", "/t", "30"]
    assert calls[0][1]["shell"] is False


def test_power_cancel_reports_windows_failure(tmp_path, monkeypatch):
    action_dispatcher = dispatcher(tmp_path)

    class Completed:
        returncode = 1116

    monkeypatch.setattr(
        actions_module.subprocess, "run", lambda *args, **kwargs: Completed()
    )
    result = action_dispatcher.execute_validated(
        "power", {"operation": "cancel"}
    )

    assert not result.success
    assert "rechazó" in result.message


def test_dispatcher_exposes_immediate_and_sensitive_action_sets():
    assert {"open_app", "open_target", "take_screenshot"} <= ActionDispatcher.IMMEDIATE
    assert {"close_app", "lock_computer", "power", "file_operation"} <= (
        ActionDispatcher.SENSITIVE
    )


def test_pc_status_reports_each_gpu_and_extended_system_details(
    tmp_path, monkeypatch
):
    action_dispatcher = dispatcher(tmp_path)

    class Completed:
        stdout = (
            "0, GPU-GAMING, NVIDIA RTX 5060 Ti, 591.86, 00000000:04:00.0, "
            "12, 1024, 8151, 7127, 46, 31.5, 180.0\n"
            "1, GPU-1ad4d697-126f-1101-233d-e079c4eb6f3b, NVIDIA RTX 5060 Ti, "
            "591.86, 00000000:08:00.0, 98, 15400, 16311, 911, 71, 151.2, 180.0"
        )

    monkeypatch.setattr(
        actions_module.subprocess,
        "run",
        lambda command, **kwargs: Completed(),
    )

    result = action_dispatcher.execute("pc_status")

    assert result.success
    assert result.data["cpu_logical_cores"]
    assert result.data["memory_total_gb"] > 0
    assert result.data["disk_total_gb"] > 0
    assert result.data["system"]["uptime_seconds"] >= 0
    assert len(result.data["gpus"]) == 2
    assert result.data["gpus"][0]["role"] == "gaming"
    assert result.data["gpus"][1]["role"] == "ai"
    assert result.data["gpus"][1]["memory_total_mb"] == 16311.0
    assert result.data["gpu"]["memory_total_mb"] == 16311.0


def test_known_app_launch_uses_configured_argument_list_without_shell(tmp_path, monkeypatch):
    target = tmp_path / "steam.exe"
    target.write_bytes(b"")
    action_dispatcher = dispatcher(tmp_path)
    action_dispatcher.config.apps["steam"] = AppEntry(["%ARFOXIA_TEST_STEAM%"])
    monkeypatch.setenv("ARFOXIA_TEST_STEAM", str(target))
    calls = []
    monkeypatch.setattr(
        actions_module.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    result = action_dispatcher.execute("open_app", {"app": "Steam"})

    assert result.success
    assert calls == [([str(target)], {"close_fds": True, "shell": False})]


def test_open_target_accepts_known_alias_and_https_only(tmp_path, monkeypatch):
    target = tmp_path / "steam.exe"
    target.write_bytes(b"")
    action_dispatcher = dispatcher(tmp_path)
    action_dispatcher.config.apps["steam"] = AppEntry([str(target)])
    launched = []
    opened = []
    monkeypatch.setattr(
        actions_module.subprocess,
        "Popen",
        lambda command, **kwargs: launched.append((command, kwargs)),
    )
    monkeypatch.setattr(action_dispatcher, "_shell_open", opened.append)

    alias_result = action_dispatcher.execute("open_target", {"target": "steam"})
    https_result = action_dispatcher.execute(
        "open_target",
        {"target": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert alias_result.success
    assert https_result.success
    assert launched[0][0] == [str(target)]
    assert opened == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert "navegador predeterminado" in https_result.message
    assert https_result.data == {
        "target": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "destination": "default_browser",
        "launch_status": "accepted_by_windows",
        "youtube_kind": "video",
    }


@pytest.mark.parametrize(
    "target",
    [
        "https://www.youtube.com/watch?v=",
        "https://www.youtube.com/watch?v=abc",
        "https://youtu.be/too-short",
        "https://www.youtube.com/shorts/too-short",
        "https://www.youtube.com/results?search_query=",
        "https://www.youtube.com:invalid/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com\\@example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ bad",
        "https://www.youtube.com/results?search_query=ice%ZZmusic",
        "https://[::1",
    ],
)
def test_open_target_rejects_malformed_youtube_and_https_urls(
    tmp_path, monkeypatch, target
):
    action_dispatcher = dispatcher(tmp_path)
    opened = []
    monkeypatch.setattr(action_dispatcher, "_shell_open", opened.append)

    result = action_dispatcher.execute("open_target", {"target": target})

    assert not result.success
    assert not result.requires_authorization
    assert opened == []


@pytest.mark.parametrize(
    ("target", "youtube_kind"),
    [
        ("https://youtu.be/dQw4w9WgXcQ", "video"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "video"),
        (
            "https://www.youtube.com/results?search_query=glaceon+music",
            "search",
        ),
        ("https://www.youtube.com/", "page"),
        ("https://example.com/article", None),
    ],
)
def test_open_target_classifies_accepted_browser_targets(
    tmp_path, monkeypatch, target, youtube_kind
):
    action_dispatcher = dispatcher(tmp_path)
    monkeypatch.setattr(action_dispatcher, "_shell_open", lambda _target: None)

    result = action_dispatcher.execute("open_target", {"target": target})

    assert result.success
    assert result.data["youtube_kind"] == youtube_kind
    assert result.data["launch_status"] == "accepted_by_windows"


def test_open_target_does_not_claim_that_a_page_loaded_when_windows_rejects_it(
    tmp_path, monkeypatch
):
    action_dispatcher = dispatcher(tmp_path)

    def reject(_target):
        raise OSError("test-only ShellExecute failure")

    monkeypatch.setattr(action_dispatcher, "_shell_open", reject)

    result = action_dispatcher.execute(
        "open_target",
        {"target": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert not result.success
    assert "Windows no aceptó" in result.message
    assert "test-only" not in result.message


@pytest.mark.parametrize(
    "target",
    [
        "http://example.com",
        "javascript:alert(1)",
        "data:text/plain,test",
    ],
)
def test_non_https_uris_are_sensitive_and_rejected_after_validation(
    tmp_path, target
):
    action_dispatcher = dispatcher(tmp_path)

    assert action_dispatcher.is_sensitive("open_target", {"target": target})
    proposed = action_dispatcher.execute("open_target", {"target": target})
    rejected = action_dispatcher.execute_validated("open_target", {"target": target})

    assert not proposed.requires_authorization
    assert not proposed.success
    assert not rejected.success
    assert "protocolo" in rejected.message.lower()


@pytest.mark.parametrize("target", ["steam://open/main", "ms-settings:display"])
def test_authorized_windows_uri_opens_without_a_command_shell(
    tmp_path, monkeypatch, target
):
    action_dispatcher = dispatcher(tmp_path)
    opened = []
    monkeypatch.setattr("glaceon_companion.actions.os.startfile", opened.append)

    assert action_dispatcher.is_sensitive("open_target", {"target": target})
    result = action_dispatcher.execute_validated("open_target", {"target": target})

    assert result.success
    assert opened == [target]


def test_authorized_installed_app_name_is_resolved_from_path(tmp_path, monkeypatch):
    action_dispatcher = dispatcher(tmp_path)
    executable = tmp_path / "ExampleTool.exe"
    opened = []
    monkeypatch.setattr(
        "glaceon_companion.actions.shutil.which",
        lambda name: str(executable) if name.casefold() == "exampletool.exe" else None,
    )
    monkeypatch.setattr("glaceon_companion.actions.os.startfile", opened.append)

    proposed = action_dispatcher.execute("open_target", {"target": "ExampleTool"})
    result = action_dispatcher.execute_validated(
        "open_target", {"target": "ExampleTool"}
    )

    assert proposed.requires_authorization
    assert result.success
    assert opened == [str(executable.resolve())]


def test_open_target_any_file_requires_authorization(tmp_path, monkeypatch):
    document = tmp_path / "notas.txt"
    executable = tmp_path / "programa.exe"
    document.write_text("hola", encoding="utf-8")
    executable.write_bytes(b"")
    action_dispatcher = dispatcher(tmp_path)
    opened = []
    monkeypatch.setattr(action_dispatcher, "_shell_open", opened.append)

    assert action_dispatcher.is_sensitive(
        "open_target", {"target": str(document)}
    )
    assert action_dispatcher.is_sensitive(
        "open_target", {"target": str(executable)}
    )
    assert action_dispatcher.execute(
        "open_target", {"target": str(executable)}
    ).requires_authorization
    assert action_dispatcher.execute(
        "open_target", {"target": str(document)}
    ).requires_authorization
    result = action_dispatcher.execute_validated(
        "open_target", {"target": str(executable)}
    )

    assert result.success
    assert opened == [str(executable)]


def test_dynamic_sensitivity_handles_known_alias_and_power_cancel(tmp_path):
    action_dispatcher = dispatcher(tmp_path)

    assert not action_dispatcher.is_sensitive("open_app", {"app": "steam"})
    assert action_dispatcher.is_sensitive("open_app", {"app": "desconocida"})
    assert not action_dispatcher.is_sensitive("power", {"operation": "cancel"})
    assert action_dispatcher.is_sensitive("power", {"operation": "shutdown"})
    assert action_dispatcher.is_sensitive(
        "file_operation", {"operation": "create_directory"}
    )


@pytest.mark.parametrize(
    "target",
    [
        "relative\\file.txt",
        r"\\.\PhysicalDrive0",
        r"\\?\C:\Windows\file.txt",
        r"C:\temp\CON.txt",
    ],
)
def test_file_targets_reject_relative_device_and_reserved_paths(tmp_path, target):
    result = dispatcher(tmp_path).execute_validated(
        "file_operation",
        {"operation": "write_text", "path": target, "content": "test"},
    )

    assert not result.success


def test_file_operations_never_accept_a_filesystem_root(tmp_path):
    root = str(Path(tmp_path.anchor))
    result = dispatcher(tmp_path).execute_validated(
        "file_operation", {"operation": "trash", "path": root}
    )

    assert not result.success
    assert "raíz" in result.message.lower()


def test_create_directory_and_atomic_utf8_write_without_default_overwrite(tmp_path):
    action_dispatcher = dispatcher(tmp_path)
    folder = tmp_path / "proyecto"
    document = folder / "notas.txt"

    created = action_dispatcher.execute_validated(
        "file_operation", {"operation": "create_directory", "path": str(folder)}
    )
    written = action_dispatcher.execute_validated(
        "file_operation",
        {"operation": "write_text", "path": str(document), "content": "Ola, Gori 🧊"},
    )
    refused = action_dispatcher.execute_validated(
        "file_operation",
        {"operation": "write_text", "path": str(document), "content": "otro"},
    )
    overwritten = action_dispatcher.execute_validated(
        "file_operation",
        {
            "operation": "write_text",
            "path": str(document),
            "content": "nuevo",
            "overwrite": True,
        },
    )

    assert created.success and written.success and overwritten.success
    assert not refused.success
    assert document.read_text(encoding="utf-8") == "nuevo"
    assert not list(folder.glob(".*.tmp"))


def test_append_is_atomic_utf8_and_total_text_is_limited_to_one_mib(tmp_path):
    action_dispatcher = dispatcher(tmp_path)
    document = tmp_path / "registro.txt"
    document.write_text("uno", encoding="utf-8")

    appended = action_dispatcher.execute_validated(
        "file_operation",
        {"operation": "append_text", "path": str(document), "content": " + dous"},
    )
    oversized = action_dispatcher.execute_validated(
        "file_operation",
        {
            "operation": "append_text",
            "path": str(document),
            "content": "x" * (1024 * 1024),
        },
    )

    assert appended.success
    assert document.read_text(encoding="utf-8") == "uno + dous"
    assert not oversized.success
    assert "1 mib" in oversized.message.lower()


def test_copy_move_and_same_folder_rename_are_bounded(tmp_path):
    action_dispatcher = dispatcher(tmp_path)
    source = tmp_path / "source.txt"
    copied = tmp_path / "copied.txt"
    moved = tmp_path / "moved.txt"
    renamed = tmp_path / "renamed.txt"
    source.write_text("hielo", encoding="utf-8")

    copy_result = action_dispatcher.execute_validated(
        "file_operation",
        {"operation": "copy", "path": str(source), "destination": str(copied)},
    )
    move_result = action_dispatcher.execute_validated(
        "file_operation",
        {"operation": "move", "path": str(copied), "destination": str(moved)},
    )
    rename_result = action_dispatcher.execute_validated(
        "file_operation",
        {"operation": "rename", "path": str(moved), "destination": str(renamed)},
    )

    assert copy_result.success and move_result.success and rename_result.success
    assert source.read_text(encoding="utf-8") == "hielo"
    assert renamed.read_text(encoding="utf-8") == "hielo"
    assert not copied.exists() and not moved.exists()


def test_copy_does_not_overwrite_by_default(tmp_path):
    action_dispatcher = dispatcher(tmp_path)
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("nuevo", encoding="utf-8")
    destination.write_text("conservar", encoding="utf-8")

    result = action_dispatcher.execute_validated(
        "file_operation",
        {"operation": "copy", "path": str(source), "destination": str(destination)},
    )

    assert not result.success
    assert destination.read_text(encoding="utf-8") == "conservar"


def test_rename_rejects_a_destination_in_another_folder(tmp_path):
    action_dispatcher = dispatcher(tmp_path)
    source = tmp_path / "source.txt"
    other = tmp_path / "other"
    other.mkdir()
    source.write_text("dato", encoding="utf-8")

    result = action_dispatcher.execute_validated(
        "file_operation",
        {
            "operation": "rename",
            "path": str(source),
            "destination": str(other / "renamed.txt"),
        },
    )

    assert not result.success
    assert source.exists()


def test_trash_uses_recycle_integration_and_has_no_permanent_fallback(
    tmp_path, monkeypatch
):
    action_dispatcher = dispatcher(tmp_path)
    document = tmp_path / "trash-me.txt"
    document.write_text("dato", encoding="utf-8")
    recycled = []
    monkeypatch.setattr(actions_module, "send2trash", recycled.append)

    result = action_dispatcher.execute_validated(
        "file_operation", {"operation": "trash", "path": str(document)}
    )

    assert result.success
    assert recycled == [str(document)]

    monkeypatch.setattr(actions_module, "send2trash", None)
    unavailable = action_dispatcher.execute_validated(
        "file_operation", {"operation": "trash", "path": str(document)}
    )
    assert not unavailable.success
    assert document.exists()


def test_file_operation_rejects_unexpected_arguments(tmp_path):
    document = tmp_path / "notas.txt"
    result = dispatcher(tmp_path).execute_validated(
        "file_operation",
        {
            "operation": "write_text",
            "path": str(document),
            "content": "hola",
            "command": "whoami",
        },
    )

    assert not result.success
    assert "no permitidos" in result.message.lower()
    assert not document.exists()


def test_file_content_is_redacted_from_confirmation_and_audit(tmp_path):
    action_dispatcher = dispatcher(tmp_path)
    document = tmp_path / "secreto.txt"
    secret = "contenido que no debe quedar en el audit log"

    result = action_dispatcher.execute(
        "file_operation",
        {"operation": "write_text", "path": str(document), "content": secret},
    )
    audit_json = action_dispatcher.database._connection.execute(
        "SELECT arguments FROM action_audit ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    audited = json.loads(audit_json)

    assert result.requires_authorization
    assert result.data["arguments"]["content"] == {
        "redacted": True,
        "length_bytes": len(secret.encode("utf-8")),
    }
    assert secret not in audit_json
    assert audited["content"] == {
        "redacted": True,
        "length_bytes": len(secret.encode("utf-8")),
    }


@pytest.mark.parametrize(
    "name", ["authorization.json", "secrets.json", "config.json", "companion.sqlite3"]
)
def test_internal_security_files_cannot_be_modified_even_after_authorization(
    tmp_path, name
):
    action_dispatcher = dispatcher(tmp_path)
    target = action_dispatcher.data_dir / name
    result = action_dispatcher.execute_validated(
        "file_operation",
        {
            "operation": "write_text",
            "path": str(target),
            "content": "tamper",
            "overwrite": True,
        },
    )

    assert not result.success
    assert "protegido" in result.message.lower() or "protegida" in result.message.lower()
    assert not target.exists()


def test_invalid_unicode_content_is_redacted_without_breaking_error_boundary(tmp_path):
    action_dispatcher = dispatcher(tmp_path)
    target = tmp_path / "invalid.txt"
    result = action_dispatcher.execute(
        "file_operation",
        {"operation": "write_text", "path": str(target), "content": "\ud800"},
    )
    audit_json = action_dispatcher.database._connection.execute(
        "SELECT arguments FROM action_audit ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]

    assert not result.success
    assert not result.requires_authorization
    assert "invalid_utf8" in audit_json
