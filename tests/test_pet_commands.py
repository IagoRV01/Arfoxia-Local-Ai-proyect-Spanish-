import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from glaceon_companion.api import create_api
from glaceon_companion.config import ConfigStore, PROJECT_ROOT
from glaceon_companion.pet_commands import posture_command
from glaceon_companion.services import CompanionService


@pytest.mark.parametrize('text,expected', [
    ('Siéntate', 'sit'), ('Arfoxia, quédate sentado mientras juego', 'sit'),
    ('Por favor, siéntate sin dormir', 'sit'), ('Quédate sentado mientras juego a Minecraft', 'sit'),
    ('Vuelve a pasear', 'resume'), ('Levántate, por favor', 'resume'),
    ('No te sientes', None), ('No vuelvas a pasear', None),
    ('¿Puedes explicar qué significa siéntate?', None), ('"siéntate"', None),
    ('Busca cómo sentarse', None), ('Siéntate y apaga el PC', None),
])
def test_only_explicit_posture_orders_are_routed(text, expected):
    assert posture_command(text) == expected


def test_seated_mode_persists_and_old_state_payloads_still_load(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    assert not service.state.seated
    service.interact('sit')
    assert service.database.load_state().seated
    payload = service.state.as_public_dict()
    payload.pop('seated')
    payload.pop('mood')
    with service.database._connection:
        service.database._connection.execute('UPDATE pet_state SET payload=? WHERE id=1', (json.dumps(payload),))
    assert not service.database.load_state().seated
    service.close()


def test_authenticated_mobile_controls_sitting_and_resuming(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    try:
        with TestClient(create_api(service, 'token', PROJECT_ROOT / 'src/glaceon_companion/static')) as client:
            assert client.post('/api/interact', json={'kind': 'sit'}).status_code == 401
            headers = {'Authorization': 'Bearer token'}
            seated = client.post('/api/interact', json={'kind': 'sit'}, headers=headers)
            assert seated.status_code == 200
            assert seated.json()['seated'] and not seated.json()['asleep']
            assert client.get('/api/state', headers=headers).json()['mood'] == 'sentado'
            resumed = client.post('/api/interact', json={'kind': 'resume'}, headers=headers)
            assert not resumed.json()['seated']
    finally:
        service.close()


def test_chat_posture_commands_do_not_call_or_load_ollama_and_keep_chat(tmp_path):
    store = ConfigStore(tmp_path)
    service = CompanionService(store, store.load())
    async def forbidden(*args, **kwargs):
        raise AssertionError('Posture commands must not use Ollama')
    service._select_turn_model = forbidden
    service.ollama.chat = forbidden
    try:
        conversation = service.create_conversation('Juego')
        result = asyncio.run(service.chat('Siéntate mientras juego', conversation_id=conversation['id']))
        assert result['model_mode'] == 'direct'
        assert service.state.seated
        assert result['conversation_id'] == conversation['id']
        result = asyncio.run(service.chat('Vuelve a pasear', conversation_id=conversation['id']))
        assert not service.state.seated
        assert result['conversation_id'] == conversation['id']
        assert len(service.database.recent_messages(10, conversation_id=conversation['id'])) == 4
    finally:
        service.close()
