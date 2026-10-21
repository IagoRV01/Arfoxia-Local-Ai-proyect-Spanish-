import inspect
from pathlib import Path
import pytest
from ports.ps4 import repeat_control as control

HOST = '192.168.50.10'
READY = b'CLIENT_CONTROL_BASELINE 1\n'


@pytest.mark.parametrize('sequence', [1, 99, 4294967295])
@pytest.mark.parametrize('session', [1, 4294967295])
@pytest.mark.parametrize('mode', range(5))
def test_protocol_roundtrip(sequence, session, mode):
    value = control.encode(sequence, session, mode)
    assert len(value) == 34 and control.decode(value) == (sequence, session, mode)


@pytest.mark.parametrize('bad', [0, -1, 4294967296, True, 1.0])
@pytest.mark.parametrize('field', [0, 1, 2])
def test_invalid_fields(bad, field):
    fields = [1, 1, 1]
    # Zero is a valid stop mode, but no other value in this list is a mode.
    if field == 2 and bad == 0 and type(bad) is int:
        return
    fields[field] = bad
    with pytest.raises(ValueError):
        control.encode(*fields)


@pytest.mark.parametrize('value', [b'', b'ARFOXIA10:0000000001:0000000001:5\n',
    b'ARFOXIA10:0000000000:0000000001:1\n', b'ARFOXIA10:0000000001:4294967296:1\n',
    b'ARFOXIA10:0000000001:0000000001:1\r', b'ARFOXIA10:0000000001:0000000001:1\nEXTRA'])
def test_malformed(value):
    with pytest.raises(ValueError):
        control.decode(value)


class FTP:
    def __init__(self, files, events, corrupt=False):
        self.files, self.events, self.corrupt = files, events, corrupt
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def connect(self, host, port):
        assert host == HOST and port == 2121
    def login(self): pass
    def cwd(self, path): assert path == control.REMOTE
    def nlst(self): return list(self.files)
    def retrbinary(self, cmd, callback, *args, **kwargs): callback(self.files[cmd[5:]])
    def storbinary(self, cmd, stream):
        assert cmd == 'STOR ' + control.TEMP
        self.events.append('store')
        self.files[control.TEMP] = b'bad' if self.corrupt else stream.read()
    def rename(self, source, destination):
        assert source == control.TEMP and destination == control.CONTROL
        old_epoch = control.decode(self.files[destination])[1] if destination in self.files else 0
        self.events.append('rename')
        self.files[destination] = self.files.pop(source)
        _, epoch, mode = control.decode(self.files[destination])
        if mode and epoch > old_epoch and control.LOG in self.files:
            self.files[control.LOG] += f'CLIENT_SESSION_STARTED {epoch}\n'.encode()


def invoke(files, mode='walk', **kwargs):
    events = []
    result = control.write_control(HOST, mode, ftp_factory=lambda **kw: FTP(files, events), **kwargs)
    assert events == ['store', 'rename']
    return result


def test_prepare_only_stops_and_preserves_v9_files():
    files = {'control-v9.txt': b'old', 'dispatch-v9.txt': b'keep'}
    assert invoke(files, 'stop', prepare=True) == (1, 1)
    assert control.decode(files[control.CONTROL]) == (1, 1, 0)
    assert files['control-v9.txt'] == b'old' and files['dispatch-v9.txt'] == b'keep'
    with pytest.raises(ValueError): invoke(files, 'stop', prepare=True)


def test_separate_reviewed_trial_namespace_preserves_previous_logs(monkeypatch):
    previous = {control.CONTROL: control.encode(20, 3, 4), control.LOG: READY, control.LOAD_LOG: b'old'}
    monkeypatch.setattr(control, 'CONTROL', 'control-v11.txt')
    monkeypatch.setattr(control, 'TEMP', 'control-v11.upload-verify')
    monkeypatch.setattr(control, 'LOG', 'dispatch-v11.txt')
    monkeypatch.setattr(control, 'LOAD_LOG', 'dispatch-load-v11.txt')
    files = previous.copy()
    assert invoke(files, 'stop', prepare=True) == (1, 1)
    assert all(files[key] == value for key, value in previous.items())


@pytest.mark.parametrize('revision', [10, 11])
def test_configure_reviewed_revision_only_changes_control_paths(monkeypatch, revision):
    for name in ('CONTROL', 'TEMP', 'LOG', 'LOAD_LOG'):
        monkeypatch.setattr(control, name, getattr(control, name))
    control.configure_revision(revision)
    assert control.CONTROL == f'control-v{revision}.txt'
    assert control.LOG == f'dispatch-v{revision}.txt'
    assert control.LOAD_LOG == f'dispatch-load-v{revision}.txt'
    assert control.TEMP == f'control-v{revision}.upload-verify'


@pytest.mark.parametrize('revision', [9, 12, True, '11'])
def test_unknown_revision_preserves_existing_namespace(revision):
    before = control.CONTROL, control.LOG, control.TEMP, control.LOAD_LOG
    with pytest.raises(ValueError): control.configure_revision(revision)
    assert before == (control.CONTROL, control.LOG, control.TEMP, control.LOAD_LOG)


def test_explicit_start_and_repeated_sessions():
    files = {control.CONTROL: control.encode(1, 1, 0), control.LOG: READY}
    assert invoke(files, start=True) == (2, 2)
    assert invoke(files, 'sit', session=2) == (3, 2)
    assert invoke(files, 'stop', session=2) == (4, 2)
    assert invoke(files, start=True) == (5, 3)
    assert control.decode(files[control.CONTROL]) == (5, 3, 1)
    before = files.copy()
    with pytest.raises(ValueError, match='Another session'):
        invoke(files, 'stop', session=2)
    assert files == before


def test_explicit_finish_owned_session_only():
    files = {control.CONTROL: control.encode(1, 7, 0), control.LOG: READY}
    assert invoke(files, 'finish', session=7) == (2, 7)
    assert control.decode(files[control.CONTROL]) == (2, 7, 4)
    with pytest.raises(ValueError): invoke(files, 'finish', start=True)


@pytest.mark.parametrize('log', [b'', READY+b'PREVIEW_CLEANED 1\n',
    READY+b'CLIENT_PROCESS_FINISHED 1\n', READY+b'CLIENT_SCENE_CHANGED_STOP 1\n',
    READY+b'FRAME_NOT_ON_UI_HALTED 1\n', READY+b'PREVIEW_MANAGED_EXCEPTION 1\n',
    READY+b'PHASE_QUEUE_CLEANUP 0\n', b'x'*65537], ids=['empty', 'cleaned', 'finished',
    'scene-changed', 'wrong-thread', 'exception', 'cleanup-queued', 'oversize'])
def test_unready_or_finished_trial_never_writes(log):
    files = {control.CONTROL: control.encode(1, 1, 0), control.LOG: log}
    before = files.copy()
    with pytest.raises(ValueError): invoke(files, start=True)
    assert files == before


@pytest.mark.parametrize('kwargs', [{}, {'start': True, 'session': 1},
    {'prepare': True}, {'start': True, 'prepare': True}, {'session': True}])
def test_invalid_actions_before_network(kwargs):
    def factory(**kw): pytest.fail('No network expected')
    with pytest.raises(ValueError): control.write_control(HOST, 'walk', ftp_factory=factory, **kwargs)


@pytest.mark.parametrize('files', [{control.TEMP: b'partial'},
    {control.CONTROL: b'unknown'}, {control.LOG: READY},
    {control.CONTROL: control.encode(4294967295, 1, 0), control.LOG: READY},
    {control.CONTROL: control.encode(1, 4294967295, 0), control.LOG: READY}])
def test_unknown_partial_missing_and_overflow_preserved(files):
    before = files.copy()
    with pytest.raises((ValueError, KeyError)): invoke(files, start=True)
    assert files == before


def test_failed_readback_preserves_original():
    files = {control.CONTROL: control.encode(1, 1, 0), control.LOG: READY}
    events = []
    with pytest.raises(ValueError, match='verification'):
        control.write_control(HOST, 'walk', start=True,
            ftp_factory=lambda **kw: FTP(files, events, corrupt=True))
    assert files[control.CONTROL] == control.encode(1, 1, 0)
    assert events == ['store'] and control.TEMP in files


def test_historical_log_is_not_an_acknowledgement():
    files = {control.LOG: READY+b'CLIENT_SESSION_STARTED 2\n'}
    events, now = [], [0.0]
    def pause(seconds): now[0] += seconds
    with pytest.raises(ValueError, match='No acknowledgement'):
        control.wait_started(FTP(files, events), 3, clock=lambda: now[0], pause=pause)
    assert 4 <= now[0] < 4.2 and not events


def test_current_epoch_acknowledged_without_waiting():
    ftp = FTP({control.LOG: READY+b'CLIENT_SESSION_STARTED 3\n'}, [])
    def no_pause(seconds): pytest.fail('Already acknowledged')
    control.wait_started(ftp, 3, pause=no_pause)


def test_epoch_ack_has_exact_line_match_and_signed_native_value():
    ftp = FTP({control.LOG: READY+b'CLIENT_SESSION_STARTED -1\n'}, [])
    control.wait_started(ftp, 4294967295)
    now = [0.0]
    ftp.files[control.LOG] = READY+b'CLIENT_SESSION_STARTED 30\n'
    with pytest.raises(ValueError):
        control.wait_started(ftp, 3, clock=lambda: now[0], pause=lambda t: now.__setitem__(0, now[0]+t))


@pytest.mark.parametrize('host', ['8.8.8.8', '0.0.0.0', '224.0.0.1', 'ps4.example'])
def test_private_explicit_address_only(host):
    def factory(**kw): pytest.fail('No network expected')
    with pytest.raises(ValueError): control.write_control(host, 'walk', start=True, ftp_factory=factory)


def test_repeatable_is_opt_in_hidden_and_has_no_extra_sdk_probes():
    root = Path(__file__).resolve().parents[1]/'ports/ps4'
    dispatch = (root/'native/dispatch_probe.c').read_text()
    native = (root/'native/sprite_preview.h').read_text()
    controller = inspect.getsource(control)
    assert '#define ARFOXIA_PS4_REPEATABLE_CLIENT 0' in dispatch
    assert 'Repeatable client requires resident owner control' in dispatch
    assert 'ARFOXIA_PS4_REPEATABLE_CLIENT ? 0 : 1' in native
    assert 'CLIENT_UI_VISIBLE' in native and 'CLIENT_CONTROL_BASELINE' in native
    assert native.index('CLIENT_SCENE_CHANGED_STOP') < native.index('CLIENT_UI_VISIBLE')
    assert 'arfoxia_session_step(session,data,count)' in native
    for forbidden in ('9090', 'sendall', 'subprocess', 'plugins.ini', 'arfoxia_sdk'):
        assert forbidden not in controller
