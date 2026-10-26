import io
import json
import subprocess
import sqlite3
from types import SimpleNamespace
import urllib.error

import httpx
import pytest
from fastapi.testclient import TestClient

from glaceon_companion import remote_sunshine_agent as agent
from glaceon_companion.api import create_api
from glaceon_companion.config import ConfigStore, PROJECT_ROOT
from glaceon_companion.game_streaming import GameStreamingManager, PairingRateLimitedError
from glaceon_companion.services import CompanionService
from glaceon_companion.sunshine_ssh import SunshineSSHBridge, SunshineSSHError


def bridge_for(tmp_path):
    return SunshineSSHBridge(ConfigStore(tmp_path), SimpleNamespace(devices={'bc250': {'ssh_alias': 'test-bc250'}}))


def ready():
    return {'success': True, 'ports': {'47990': True}, 'running': True, 'web_ready': True,
        'host': '192.168.1.50', 'tailscale_ip': '', 'tailscale_ready': False,
        'credentials_verified': True, 'paired_clients': 0, 'paired_device_names': []}


def test_separate_protected_credentials_preserve_local_account_and_owner_token(tmp_path):
    store = ConfigStore(tmp_path)
    token = store.api_token()
    store.save_sunshine_credentials('windows', 'windows-secret')
    store.save_sunshine_credentials('linux', 'linux-secret', target='bc250')
    assert store.sunshine_credentials() == ('windows', 'windows-secret')
    assert store.sunshine_credentials('bc250') == ('linux', 'linux-secret')
    assert store.api_token() == token
    assert 'linux-secret' not in json.dumps(store.public_config(store.load()))
    if __import__('os').name == 'nt':
        assert 'linux-secret' not in store.secrets_path.read_text()
    with pytest.raises(ValueError): store.sunshine_credentials('untrusted-host')


def test_rpc_uses_trusted_alias_strict_host_key_and_stdin_not_argv_for_secrets(tmp_path, monkeypatch):
    bridge = bridge_for(tmp_path)
    calls = []
    monkeypatch.setattr('glaceon_companion.sunshine_ssh.shutil.which', lambda name: 'ssh.exe')
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"success":true}')
    monkeypatch.setattr('glaceon_companion.sunshine_ssh.subprocess.run', run)
    bridge._rpc('pair', credentials=('private-user', 'very-secret-pass'), pin='0927', name='iPhone')
    command, options = calls[0]
    assert command[-2] == 'test-bc250'
    assert 'StrictHostKeyChecking=yes' in command and 'BatchMode=yes' in command
    assert 'very-secret-pass' not in str(command) and '0927' not in str(command)
    assert json.loads(options['input']) == {'operation': 'pair', 'username': 'private-user',
        'password': 'very-secret-pass', 'pin': '0927', 'name': 'iPhone'}
    assert options['shell'] is False and options['timeout'] == 28
    assert '-L' not in command and '-R' not in command


@pytest.mark.parametrize('alias', ['-oProxyCommand=oops', 'pc;touch file', 'pc/../../other'])
def test_unsafe_ssh_alias_is_rejected_before_spawning(tmp_path, alias, monkeypatch):
    bridge = bridge_for(tmp_path); bridge.travel.devices['bc250']['ssh_alias'] = alias
    monkeypatch.setattr('glaceon_companion.sunshine_ssh.subprocess.run', lambda *a, **kw: pytest.fail('spawned'))
    with pytest.raises(SunshineSSHError): bridge._rpc('status')


def test_unregistered_device_does_not_connect(tmp_path):
    bridge = SunshineSSHBridge(ConfigStore(tmp_path), None)
    assert not bridge.available()
    with pytest.raises(SunshineSSHError): bridge._rpc('status')


@pytest.mark.parametrize('output,code', [('{"success":true,"oops":', 0), ('secret password', 255), ('[]', 0), ('{"success":1}', 0)])
def test_ssh_failures_do_not_echo_remote_output_or_credentials(tmp_path, monkeypatch, output, code):
    bridge = bridge_for(tmp_path)
    monkeypatch.setattr('glaceon_companion.sunshine_ssh.shutil.which', lambda name: 'ssh')
    monkeypatch.setattr('glaceon_companion.sunshine_ssh.subprocess.run', lambda *a, **kw:
        SimpleNamespace(returncode=code, stdout=output, stderr='secret password'))
    with pytest.raises(SunshineSSHError) as error: bridge._rpc('status', credentials=('u', 'secret password'))
    assert 'secret password' not in str(error.value)


def test_configure_verifies_before_saving_and_never_replaces_local_credentials(tmp_path, monkeypatch):
    bridge = bridge_for(tmp_path)
    bridge.store.save_sunshine_credentials('local', 'keep-local')
    monkeypatch.setattr(bridge, '_rpc', lambda *a, **kw: {**ready(), 'credentials_verified': False})
    with pytest.raises(SunshineSSHError): bridge.configure('u', 'bad')
    assert bridge.store.sunshine_credentials('bc250') is None
    monkeypatch.setattr(bridge, '_rpc', lambda *a, **kw: ready())
    bridge.configure('u', 'correct')
    assert bridge.store.sunshine_credentials('bc250') == ('u', 'correct')
    assert bridge.store.sunshine_credentials() == ('local', 'keep-local')


def test_status_is_targeted_and_does_not_claim_this_iphone_is_paired(tmp_path, monkeypatch):
    bridge = bridge_for(tmp_path)
    monkeypatch.setattr(bridge, '_rpc', lambda *a, **kw: {**ready(), 'password': 'must-not-return', 'pin': '9973'})
    value = bridge.status()
    assert value['target'] == 'bc250' and value['pin_submission_available']
    assert not value['paired'] and not value['remote_ready']
    assert 'must-not-return' not in json.dumps(value) and '9973' not in json.dumps(value)


@pytest.mark.parametrize('pin', ['１２３４', '١٢٣٤', '12ab', '12345', ' 1234', '12;4'])
def test_agent_rejects_invalid_pin_without_http(pin, monkeypatch):
    monkeypatch.setattr(agent, 'sunshine_request', lambda *a, **kw: pytest.fail('HTTP'))
    with pytest.raises(ValueError): agent.run({'operation': 'pair', 'pin': pin, 'name': 'iPhone', 'username': 'u', 'password': 'p'})


@pytest.mark.parametrize('payload', [{'operation':'delete'}, {'operation':'status', 'url':'https://elsewhere'},
    {'operation':'pair', 'pin':'1234', 'name':''}, {'operation':'status','username':'u:other'}])
def test_agent_has_no_generic_admin_or_url_surface(payload):
    with pytest.raises(ValueError): agent.run(payload)


def test_agent_pair_posts_only_documented_pin_payload(monkeypatch):
    calls=[]
    def request(path, credentials, payload):
        calls.append((path, credentials, payload)); return {'status': True, 'password': 'never-return'}
    monkeypatch.setattr(agent,'sunshine_request',request)
    assert agent.run({'operation':'pair','pin':'0032','name':'iPhone','username':'u','password':'p'}) == {'success':True}
    assert calls == [('/api/pin',('u','p'),{'pin':'0032','name':'iPhone'})]


def test_missing_credentials_never_attempts_submission(monkeypatch):
    monkeypatch.setattr(agent,'sunshine_request',lambda *a,**kw:pytest.fail('HTTP'))
    assert not agent.run({'operation':'pair','pin':'0032','name':'iPhone'})['success']


def test_agent_status_filters_disabled_clients_and_cannot_expose_certificates(monkeypatch):
    monkeypatch.setattr(agent,'port_open',lambda port:True)
    monkeypatch.setattr(agent,'connection_host',lambda:('192.168.1.50',''))
    monkeypatch.setattr(agent,'sunshine_request',lambda *a,**kw:{'status':True,'named_certs':[
        {'name':'iPhone','cert':'private-cert'}, {'name':'disabled','enabled':False}, {'name':'revoked','revoked':True}]})
    value=agent.run({'operation':'status','username':'u','password':'p'})
    assert value['credentials_verified'] and value['paired_clients']==1
    assert value['paired_device_names']==['iPhone'] and 'private-cert' not in json.dumps(value)


def test_status_unauthorized_is_not_reported_as_verified(monkeypatch):
    monkeypatch.setattr(agent,'port_open',lambda port:True)
    monkeypatch.setattr(agent,'connection_host',lambda:('192.168.1.50',''))
    def failure(*args): raise urllib.error.HTTPError('loopback',401,'unauthorized',{},None)
    monkeypatch.setattr(agent,'sunshine_request',failure)
    assert not agent.run({'operation':'status','username':'u','password':'p'})['credentials_verified']


@pytest.mark.parametrize('code,reason', [(401,'unauthorized'),(403,'forbidden'),(404,'unsupported_api'),(500,'server_error')])
def test_credential_diagnostics_distinguish_rejection_from_server_failure(monkeypatch, code, reason):
    monkeypatch.setattr(agent,'port_open',lambda port:True)
    monkeypatch.setattr(agent,'connection_host',lambda:('192.168.1.50',''))
    def fail(*a): raise urllib.error.HTTPError('loopback',code,'private-secret',{},None)
    monkeypatch.setattr(agent,'sunshine_request',fail)
    value=agent.run({'operation':'status','username':'u','password':'p'})
    assert value['credential_check']==reason and not value['credentials_verified']
    assert 'private-secret' not in json.dumps(value)


def test_tls_exception_is_only_loopback_and_redirects_never_forward_credentials(monkeypatch):
    captured=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def read(self,size): return b'{"status":true}'
    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            assert timeout==12
            return Response()
    monkeypatch.setattr(agent.urllib.request,'build_opener',lambda *a:Opener())
    agent.sunshine_request('/api/pin',('u','secret'),{'pin':'0032','name':'Phone'})
    assert captured[0].full_url=='https://127.0.0.1:47990/api/pin'
    assert agent.NoRedirect().redirect_request(None,None,302,None,None,'https://evil') is None
    with pytest.raises(ValueError): agent.sunshine_request('https://evil',('u','secret'))


def test_remote_pair_rate_limit_and_bad_target_validation(tmp_path, monkeypatch):
    store=ConfigStore(tmp_path); manager=GameStreamingManager(store.load(),store)
    calls=[]
    monkeypatch.setattr(manager.bc250,'pair',lambda pin,name:calls.append((pin,name)) or {'ready':True})
    for _ in range(5): manager.pair('0032','iPhone','bc250')
    with pytest.raises(PairingRateLimitedError): manager.pair('0032','iPhone','bc250')
    with pytest.raises(ValueError): manager.pair('0032','iPhone','arbitrary-host')
    assert len(calls)==5


def test_remote_streaming_respects_the_owner_disable_setting(tmp_path, monkeypatch):
    store=ConfigStore(tmp_path); manager=GameStreamingManager(store.load(),store)
    manager.config.game_streaming_enabled=False
    monkeypatch.setattr(manager.bc250,'_rpc',lambda *a,**kw:pytest.fail('remote RPC'))
    from glaceon_companion.game_streaming import GameStreamingError
    with pytest.raises(GameStreamingError): manager.status('bc250')
    with pytest.raises(GameStreamingError): manager.pair('0032','Phone','bc250')


def test_accepted_pin_is_not_retried_when_status_followup_fails(tmp_path, monkeypatch):
    bridge=bridge_for(tmp_path)
    bridge.store.save_sunshine_credentials('u','p',target='bc250')
    calls=[]
    monkeypatch.setattr(bridge,'_rpc',lambda *a,**kw:calls.append((a,kw)) or {'success':True})
    def failed_status(): raise SunshineSSHError('offline')
    monkeypatch.setattr(bridge,'status',failed_status)
    value=bridge.pair('0032','Phone')
    assert len(calls)==1 and 'aceptó' in value['message'] and 'ready' not in value


def test_api_scopes_remote_target_and_preserves_authorization_and_audit(tmp_path):
    store=ConfigStore(tmp_path); service=CompanionService(store,store.load())
    service.authorization.configure('private-owner-password')
    service.travel.devices['bc250']={'ssh_alias':'test-bc250'}
    calls=[]
    service.pair_game_streaming=lambda pin,name,target='local':calls.append((pin,name,target)) or {'ready':True,'target':target}
    app=create_api(service,'owner-token',PROJECT_ROOT/'src/glaceon_companion/static')
    headers={'Authorization':'Bearer owner-token'}
    try:
        with TestClient(app) as client:
            assert client.get('/api/gaming/targets').status_code==401
            assert client.post('/api/gaming/bc250/setup').status_code==401
            assert len(client.get('/api/gaming/targets',headers=headers).json()['targets'])==2
            assert client.get('/api/gaming/status?target=somewhere',headers=headers).status_code==422
            assert client.post('/api/gaming/pair',headers=headers,json={'pin':'0032','target':'bc250','host':'evil'}).status_code==422
            response=client.post('/api/gaming/pair',headers=headers,json={'pin':'0032','name':'Phone','target':'bc250'}).json()
            assert response['requires_authorization'] and 'BC-250' in response['authorization_summary'] and not calls
            assert service.authorize_action(response['challenge_id'],'private-owner-password').success
            assert calls==[('0032','Phone','bc250')]
            # The action audit redacts the PIN, as in the existing Windows bridge.
            connection=sqlite3.connect(service.database.path)
            try:
                rows=connection.execute('SELECT arguments FROM action_audit WHERE action=?',('game_streaming_pair',)).fetchall()
                assert rows and '0032' not in str(rows)
            finally: connection.close()
    finally: service.close()
