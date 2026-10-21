import json
from types import SimpleNamespace
import pytest
from glaceon_companion import ps4_control


@pytest.mark.parametrize("host", ["8.8.8.8", "127.0.0.1", "0.0.0.0", "224.0.0.1", "::1", "ps4.local", "1.2.3.4;calc"])
def test_only_explicit_private_console_addresses(host):
    with pytest.raises(ValueError):
        ps4_control.validate_settings(host, 11)


@pytest.mark.parametrize("revision", [9, 12, True, "11", 11.0])
def test_only_reviewed_revision(revision):
    with pytest.raises(ValueError):
        ps4_control.validate_settings("192.168.50.10", revision)


def test_launch_uses_fixed_script_arguments_no_shell_and_saves_only_local_settings(tmp_path, monkeypatch):
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(ps4_control.subprocess, "Popen", lambda command, **kw: calls.append((command, kw)) or process)
    assert ps4_control.load_settings(tmp_path) == ("", 11)
    assert ps4_control.launch_controls(tmp_path, "192.168.50.10", 11) is process
    command, options = calls[0]
    assert command[0] == ps4_control.sys.executable
    assert command[1] == str(ps4_control.PROJECT_ROOT/"ports/ps4/repeat_control.py")
    assert command[2:] == ["--host", "192.168.50.10", "--revision", "11", "--panel"]
    assert "shell" not in options and options["close_fds"]
    assert options["cwd"] == ps4_control.PROJECT_ROOT
    assert ps4_control.load_settings(tmp_path) == ("192.168.50.10", 11)
    assert set(json.loads((tmp_path/"ps4-menu-control.json").read_text())) == {"host", "revision"}


@pytest.mark.parametrize("raw", ["bad", "[]", '{"host":"192.168.50.10"}', "x"*4097])
def test_corrupt_unknown_settings_preserved_before_any_launch(tmp_path, monkeypatch, raw):
    path = tmp_path/"ps4-menu-control.json"
    path.write_text(raw)
    monkeypatch.setattr(ps4_control.subprocess, "Popen", lambda *a, **kw: pytest.fail("No process expected"))
    with pytest.raises(ValueError):
        ps4_control.launch_controls(tmp_path, "192.168.50.10", 11)
    assert path.read_text() == raw


def test_launcher_does_not_touch_travel_or_console_transport():
    import inspect
    source = inspect.getsource(ps4_control)
    for forbidden in ("socket", "ftplib", "9090", "sendall", "travel.select", "travel.home", "shell=True"):
        assert forbidden not in source
