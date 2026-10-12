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


def test_stage_verifies_neutral_extension_before_prx():
    ftp = FTP({'unrelated.txt': b'keep'})
    transport.stage(ftp, b'owned')
    assert ftp.files == {'unrelated.txt': b'keep', 'arfoxia_probe.prx': b'owned'}
    assert ftp.changes[0] == ('store', 'arfoxia_probe.upload-bin')


def test_corrupt_transfer_is_never_named_as_executable():
    ftp = FTP(corrupt=True)
    with pytest.raises(ValueError, match='readback'):
        transport.stage(ftp, b'owned')
    assert 'arfoxia_probe.prx' not in ftp.files


@pytest.mark.parametrize('name', ['arfoxia_probe.prx', 'arfoxia_probe.upload-bin'])
def test_stage_preserves_existing_file(name):
    ftp = FTP({name: b'keep'})
    with pytest.raises(ValueError, match='already staged'):
        transport.stage(ftp, b'owned')
    assert not ftp.changes


def test_verification_restores_original_name_on_mismatch():
    ftp = FTP({'arfoxia_probe.prx': b'keep'})
    with pytest.raises(ValueError, match='match'):
        transport.verify_staged(ftp, b'other')
    assert ftp.files == {'arfoxia_probe.prx': b'keep'}


@pytest.mark.parametrize('log', ['load.txt', 'probe.txt', 'arfoxia_probe.verify-bin'])
def test_no_blind_retry_after_execution_or_interrupted_verification(log):
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
