import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('ps4_probe_transport', Path(__file__).parents[1] / 'ports/ps4/probe_transport.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class FTP:
    def __init__(self, files=None, corrupt=False):
        self.files = dict(files or {})
        self.corrupt = corrupt
        self.changes = []

    def cwd(self, _): pass
    def nlst(self, _=None): return list(self.files)
    def storbinary(self, command, stream):
        name = command.split(' ', 1)[1]
        self.files[name] = stream.read()
        self.changes.append(('store', name))
    def retrbinary(self, command, receive):
        name = command.rsplit('/', 1)[-1].split(' ', 1)[-1]
        receive(b'wrong' if self.corrupt else self.files[name])
    def rename(self, old, new):
        old, new = old.rsplit('/', 1)[-1], new.rsplit('/', 1)[-1]
        assert new not in self.files
        self.files[new] = self.files.pop(old)
        self.changes.append(('rename', old, new))


def test_stage_verifies_neutral_extension_before_prx(monkeypatch):
    monkeypatch.setattr(transport, 'LIVE_LOADS_DISABLED', False)  # In-memory FTP only.
    ftp = FTP({'unrelated.txt': b'keep'})
    transport.stage(ftp, b'owned')
    assert ftp.files == {'unrelated.txt': b'keep', 'arfoxia_probe.prx': b'owned'}
    assert ftp.changes[0] == ('store', 'arfoxia_probe.upload-bin')


def test_corrupt_transfer_is_never_named_as_executable(monkeypatch):
    monkeypatch.setattr(transport, 'LIVE_LOADS_DISABLED', False)  # In-memory FTP only.
    ftp = FTP(corrupt=True)
    with pytest.raises(ValueError, match='readback'):
        transport.stage(ftp, b'owned')
    assert 'arfoxia_probe.prx' not in ftp.files


@pytest.mark.parametrize('name', ['arfoxia_probe.prx', 'arfoxia_probe.upload-bin'])
def test_stage_preserves_existing_file(name, monkeypatch):
    monkeypatch.setattr(transport, 'LIVE_LOADS_DISABLED', False)  # In-memory FTP only.
    ftp = FTP({name: b'keep'})
    with pytest.raises(ValueError, match='already staged'):
        transport.stage(ftp, b'owned')
    assert not ftp.changes


def test_verification_restores_original_name_on_mismatch(monkeypatch):
    monkeypatch.setattr(transport, 'LIVE_LOADS_DISABLED', False)  # In-memory FTP only.
    ftp = FTP({'arfoxia_probe.prx': b'keep'})
    with pytest.raises(ValueError, match='match'):
        transport.verify_staged(ftp, b'other')
    assert ftp.files == {'arfoxia_probe.prx': b'keep'}


@pytest.mark.parametrize('log', ['load.txt', 'probe.txt', 'arfoxia_probe.verify-bin'])
def test_no_blind_retry_after_execution_or_interrupted_verification(log, monkeypatch):
    monkeypatch.setattr(transport, 'LIVE_LOADS_DISABLED', False)  # In-memory FTP only.
    ftp = FTP({'arfoxia_probe.prx': b'keep', log: b'prior'})
    with pytest.raises(ValueError):
        transport.verify_staged(ftp, b'keep')
    assert not ftp.changes


def test_read_limits_remote_diagnostic_size():
    with pytest.raises(ValueError, match='size limit'):
        transport.read_bounded(FTP({'log': b'12345'}), 'log', 4)


def test_rejects_elf_or_unrelated_loader():
    with pytest.raises(ValueError, match='PRX'):
        transport.validate(b'\x7fELF' + b'x'*100, b'x'*100)
    with pytest.raises(ValueError, match='scoped'):
        transport.validate(bytes.fromhex('4f153d1d') + b'x'*100, b'\xe9' + b'x'*100)


def test_status_does_not_open_binloader_socket():
    import inspect
    source = inspect.getsource(transport.main)
    status = source.split("if args.action == 'status':", 1)[1].split('return', 1)[0]
    assert 'send_once' not in status and 'create_connection' not in status


def test_send_uses_one_connection_with_real_bytes_and_no_ping(monkeypatch):
    monkeypatch.setattr(transport, 'LIVE_LOADS_DISABLED', False)  # Mock sockets only.
    events = []
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def sendall(self, data): events.append(('send', data))
        def shutdown(self, mode): events.append(('shutdown', mode))
    def connect(address, timeout):
        events.append(('connect', address, timeout))
        return Socket()
    monkeypatch.setattr(transport.socket, 'create_connection', connect)
    transport.send_once('ps4.example', b'real payload')
    assert events == [('connect', ('ps4.example', 9090), 8), ('send', b'real payload'), ('shutdown', transport.socket.SHUT_WR)]


def test_refused_binloader_is_not_retried(monkeypatch):
    monkeypatch.setattr(transport, 'LIVE_LOADS_DISABLED', False)  # Mock sockets only.
    attempts = []
    def connect(*args, **kwargs):
        attempts.append(args)
        raise ConnectionRefusedError('listener closed')
    monkeypatch.setattr(transport.socket, 'create_connection', connect)
    with pytest.raises(ConnectionRefusedError):
        transport.send_once('ps4.example', b'payload')
    assert len(attempts) == 1


def test_known_system_crash_disables_all_real_payload_sending(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Quarantined probe must never open a network socket')
    monkeypatch.setattr(transport.socket, 'create_connection', forbidden)
    assert transport.LIVE_LOADS_DISABLED
    with pytest.raises(ValueError, match='CE-36329-3'):
        transport.send_once('ps4.example', b'anything')


@pytest.mark.parametrize('action', ['stage', 'send'])
def test_quarantine_rejects_cli_before_ftp_connection(action, monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['probe_transport.py', action, '--host', 'ps4.example', '--home-menu'])
    def forbidden(*args, **kwargs):
        pytest.fail('Quarantined probe must never contact FTP for staging/sending')
    monkeypatch.setattr(transport.ftplib, 'FTP', forbidden)
    with pytest.raises(ValueError, match='CE-36329-3'):
        transport.main()


@pytest.mark.parametrize('action', [transport.stage, transport.verify_staged])
def test_direct_ftp_api_cannot_bypass_quarantine(action):
    class ForbiddenFTP:
        def __getattr__(self, _):
            pytest.fail('Quarantine must reject before any FTP operation')
    with pytest.raises(ValueError, match='CE-36329-3'):
        action(ForbiddenFTP(), b'owned')


def test_native_probe_does_not_resolve_or_invoke_classes():
    source = (Path(__file__).parents[1] / 'ports/ps4/native/probe.c').read_text()
    for symbol in ('mono_class_from_name', 'mono_class_get_methods', 'mono_method_full_name',
                   'mono_runtime_invoke', 'mono_compile_method', 'mprotect'):
        assert symbol not in source
    assert 'if (ARFOXIA_PS4_PROBE_QUARANTINED) return -4;' in source
