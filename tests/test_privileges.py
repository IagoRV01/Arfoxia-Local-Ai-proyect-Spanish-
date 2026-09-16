import os
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from glaceon_companion import privileges


def project(tmp_path):
    executable = tmp_path / '.venv/Scripts/pythonw.exe'
    executable.parent.mkdir(parents=True)
    executable.touch()
    (tmp_path / 'launcher.pyw').touch()
    return tmp_path


def test_missing_launcher_never_requests_elevation(tmp_path):
    assert not privileges.launch_as_administrator(tmp_path, [])


def test_owner_registered_task_is_reused_without_uac(tmp_path, monkeypatch):
    root = project(tmp_path)
    xml = ('<?xml version="1.0" encoding="UTF-16"?><Task><Actions><Exec><Command>' + str(root / '.venv/Scripts/pythonw.exe') +
           '</Command><Arguments>' + subprocess.list2cmdline([str(root / 'launcher.pyw')]) +
           '</Arguments></Exec></Actions></Task>').encode('oem' if os.name == 'nt' else 'utf-8')
    calls = []
    monkeypatch.setattr(privileges.subprocess, 'run', lambda args, **kw:
        calls.append(args) or SimpleNamespace(returncode=0, stdout=xml))
    assert privileges.launch_as_administrator(root, [])
    assert calls[-1][1] == '/Run'


@pytest.mark.parametrize('accepted', [True, False])
def test_elevation_uses_windows_runas_and_respects_cancellation(tmp_path, monkeypatch, accepted):
    root = project(tmp_path)
    launch = Mock(return_value=42 if accepted else 5)
    monkeypatch.setattr(privileges.ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(ShellExecuteW=launch)), raising=False)
    monkeypatch.setattr(privileges.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    assert privileges.launch_as_administrator(root, []) is accepted
    assert launch.call_args.args[1] == 'runas'


def test_foreign_task_is_never_started(tmp_path, monkeypatch):
    root = project(tmp_path)
    calls = []
    monkeypatch.setattr(privileges.subprocess, 'run', lambda args, **kw:
        calls.append(args) or SimpleNamespace(returncode=0, stdout=b'<Task><Actions><Exec><Command>foreign.exe</Command><Arguments>x</Arguments></Exec></Actions></Task>'))
    launch = Mock(return_value=5)
    monkeypatch.setattr(privileges.ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(ShellExecuteW=launch)), raising=False)
    assert not privileges.launch_as_administrator(root, [])
    assert len(calls) == 1
    launch.assert_called_once()
