import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from glaceon_companion.api import create_api
from glaceon_companion.config import PROJECT_ROOT
from glaceon_companion.work_tasks import WorkTasks, WorkStopped
from glaceon_companion.work_tasks import is_work_request
from glaceon_companion.actions import ActionResult
from test_developer_tools import call
from test_service_tools import FakeOllama, make_service


def wait_result(service, row):
    until = time.monotonic() + 8
    while time.monotonic() < until:
        row = service.get_work_task(row['id'])
        if row['status'] not in {'queued', 'running', 'cancelling'}:
            return row
        time.sleep(.01)
    raise AssertionError('Task did not finish')


def start(service, text='Crea y comprueba el resultado solicitado', client='request-12345678'):
    conversation = service.create_conversation('Work')
    row = service.start_work_task(text, conversation_id=conversation['id'], client_message_id=client)
    return row


def finish(summary='Hecho', verification='Resultado comprobado con herramientas'):
    return call('finish_task', {'summary': summary, 'verification': verification})


@pytest.mark.parametrize('text', [
    'Hazme una calculadora y pruébala',
    'Créame un programa pequeño',
    'Necesito que repares este archivo',
    'Configura este proyecto',
    'Generate a small working application',
    'Develop and test a calculator',
])
def test_common_work_prompts_do_not_end_at_a_promise(text):
    assert is_work_request(text)


def test_more_than_six_rounds_and_one_chat(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([call('calculate', {'expression': f'{i}+1'}) for i in range(10)] + [finish()])
    try:
        row = wait_result(service, start(service))
        assert row['status'] == 'completed'
        assert row['result']['task_calls'] == 11
        assert len(row['result']['action_results']) == 10
        assert len(service.database.list_conversations()['items']) == 1
        assert all('finish_task' in opts['tools'] for opts in service.ollama.options)
        assert len(service.ollama.requests[-1]) < 20
    finally:
        service.close()


def test_promise_is_not_completion_and_checks_required(tmp_path):
    service = make_service(tmp_path)
    target = tmp_path / 'done.txt'
    service.config.require_action_password = False
    service.ollama = FakeOllama([
        {'message': {'content': 'Voy a hacerlo'}},
        finish(),
        call('file_operation', {'operation':'write_text', 'path':str(target), 'content':'done'}),
        finish(),  # forbidden: no read/test after write
        call('read_file', {'path':str(target)}), finish(),
    ])
    try:
        row = wait_result(service, start(service))
        assert row['status'] == 'completed' and target.read_text() == 'done'
        assert sum(not item['success'] for item in row['result']['action_results']) == 2
    finally:
        service.close()


def test_three_promises_stop_without_false_success(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([{'message': {'content':'Lo reviso ahora'}}] * 3)
    try:
        row = wait_result(service, start(service))
        assert row['status'] == 'blocked'
        assert 'no se ha completado' in row['result']['message']
    finally:
        service.close()


def test_question_normal_has_no_extra_loop(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([{'message':{'content':'Hola'}}])
    try:
        row = wait_result(service, start(service, 'Hola, ¿qué tal?'))
        assert row['result']['message'] == 'Hola'
        assert len(service.ollama.requests) == 1
    finally:
        service.close()


def test_important_question_pauses_and_generic_continue_is_rejected(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([
        call('ask_user', {'question':'¿Continúo?', 'reason':'Necesito saber si continuar trabajando'}),
        call('ask_user', {'question':'¿Debo sustituir el archivo existente o conservarlo?', 'reason':'Cambiar el destino sobreescribiría trabajo anterior del propietario.'}),
    ])
    try:
        row = wait_result(service, start(service))
        assert row['status'] == 'needs_input'
        assert 'sustituir' in row['result']['message']
    finally:
        service.close()


def test_identical_write_not_repeated(tmp_path):
    service = make_service(tmp_path)
    service.config.require_action_password = False
    target = tmp_path / 'once.txt'
    write = call('file_operation', {'operation':'append_text','path':str(target),'content':'one'})
    target.write_text('')
    service.ollama = FakeOllama([write, write, call('read_file',{'path':str(target)}), finish()])
    try:
        row = wait_result(service, start(service))
        assert target.read_text() == 'one'
        assert not row['result']['action_results'][1]['success']
    finally:
        service.close()


def test_permissions_still_apply_and_web_cannot_enable_pc_code(tmp_path):
    from test_service_tools import FakeSearch
    service = make_service(tmp_path)
    service.online_search = FakeSearch()
    service.ollama = FakeOllama([{'message':{'content':'Buscaré'}}, call('run_python',{'code':'print(1)'}),
        call('ask_user', {'question':'¿Qué fuente necesitas?', 'reason':'Las fuentes disponibles no contienen la información solicitada.'})])
    try:
        row = wait_result(service, start(service, 'Busca en internet datos actuales'))
        assert not row['result']['action_results'][1]['success']
    finally:
        service.close()
    service = make_service(tmp_path / 'auth')
    service.config.pc_command_enabled = True
    service.ollama = FakeOllama([call('run_python', {'code':'print(1)'})])
    try:
        row = wait_result(service, start(service))
        assert row['status'] == 'needs_input'
        assert row['result']['requires_authorization']
    finally:
        service.close()


def test_job_retry_deduplicates_and_reboot_never_replays(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([{'message':{'content':'Hola'}}])
    try:
        row = wait_result(service, start(service, 'Hola'))
        again = service.start_work_task('Hola',conversation_id=row['conversation_id'],client_message_id=row['client_message_id'])
        assert again['id'] == row['id']
        saved = json.loads(service.work_tasks.path.read_text())
        assert 'Hola' not in json.dumps(saved)
        saved[row['id']]['status'] = 'running'
        service.work_tasks.path.write_text(json.dumps(saved))
        registry = WorkTasks(service.work_tasks.path)
        assert registry.get(row['id'])['status'] == 'interrupted'
        assert not registry.threads
    finally:
        service.close()


def test_stop_cancels_generation_not_resident_model(tmp_path):
    service = make_service(tmp_path)
    entered = threading.Event()
    class Waiting:
        async def chat(self,*args,**kwargs):
            entered.set()
            await asyncio.sleep(60)
            raise AssertionError('Should have been cancelled')
    service.ollama = Waiting()
    try:
        row = start(service)
        assert entered.wait(3)
        service.work_tasks.stop(row['id'])
        assert wait_result(service,row)['status'] == 'cancelled'
    finally:
        service.close()


def test_tasks_api_authentication_and_request_identity(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([{'message':{'content':'Hola'}}])
    conversation = service.create_conversation('API Work')
    headers = {'Authorization':'Bearer test-token'}
    try:
        with TestClient(create_api(service,'test-token',PROJECT_ROOT/'src/glaceon_companion/static')) as client:
            assert client.get('/api/tasks?conversation_id='+conversation['id']).status_code == 401
            body = dict(message='Hola',conversation_id=conversation['id'],client_message_id='request-12345678')
            assert client.post('/api/tasks',json=body).status_code == 401
            row = client.post('/api/tasks',headers=headers,json=body)
            assert row.status_code == 202
            wait_result(service,row.json())
            assert client.post('/api/tasks',headers=headers,json=body).json()['id'] == row.json()['id']
            assert client.get('/api/tasks/'+row.json()['id'],headers=headers).json()['result']['message']=='Hola'
            assert client.post('/api/tasks/'+row.json()['id']+'/stop').status_code == 401
    finally:
        service.close()


@pytest.mark.parametrize('text', ['¿Puedes crear un programa?', 'Puedes arreglar ese archivo', 'Continúa donde lo dejaste', 'Quiero que construyas una app'])
def test_question_wording_can_still_be_an_instruction(text):
    assert is_work_request(text)


@pytest.mark.parametrize('text', ['¿Cómo crear un programa?', 'Qué puedo programar', 'Hola', 'Explícame cómo corregirlo'])
def test_explanations_are_not_automatic_implementation(text):
    assert not is_work_request(text)


def test_answer_to_important_question_keeps_pending_goal(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([call('ask_user', {'question':'¿Qué opción debo calcular?', 'reason':'La elección entre dos opciones cambia el resultado requerido.'})])
    try:
        previous = wait_result(service, start(service))
        service.ollama.responses.extend([{'message': {'content':'Voy a continuar'}}, call('calculate', {'expression':'2+2'}), finish()])
        row = service.start_work_task('Sí, la primera opción',conversation_id=previous['conversation_id'],client_message_id='answer-12345678')
        row = wait_result(service,row)
        assert row['status'] == 'completed' and row['result']['action_results']
        assert any('Encargo anterior pendiente' in str(message) for message in service.ollama.requests[-1])
        assert len(service.database.list_conversations()['items']) == 1
    finally:
        service.close()


def test_cancel_during_tool_waits_for_it_but_never_starts_next(tmp_path):
    service = make_service(tmp_path)
    entered, release = threading.Event(), threading.Event()
    executed = []
    def action(name,args,**kwargs):
        executed.append(name)
        entered.set()
        assert release.wait(3)
        return ActionResult(True,name,'Real operation finished')
    service._execute_chat_action = action
    service.ollama = FakeOllama([{'message':{'tool_calls':[
        {'function':{'name':'calculate','arguments':{'expression':'1+1'}}},
        {'function':{'name':'calculate','arguments':{'expression':'2+2'}}},
    ]}}])
    try:
        row=start(service)
        assert entered.wait(3)
        service.work_tasks.stop(row['id'])
        release.set()
        assert wait_result(service,row)['status']=='cancelled'
        assert executed == ['calculate']
    finally:
        release.set()
        service.close()


def test_safety_call_limit_is_not_a_success(tmp_path, monkeypatch):
    from glaceon_companion.work_tasks import WorkSession
    monkeypatch.setattr(WorkSession,'MAX_CALLS',3)
    service=make_service(tmp_path)
    service.ollama=FakeOllama([call('calculate',{'expression':f'{i}+1'}) for i in range(3)])
    try:
        row=wait_result(service,start(service))
        assert row['status']=='blocked' and row['result']['task_calls']==3
        assert 'incompleto' in row['result']['message']
    finally:
        service.close()


def test_corrupt_progress_file_is_preserved_and_not_silently_reset(tmp_path):
    path=tmp_path/'work-tasks.json'
    path.write_text('damaged private journal')
    registry=WorkTasks(path)
    assert registry.storage_error
    with pytest.raises(ValueError,match='dañado'):
        registry.start('chat','client-12345678',True,None)
    assert path.read_text()=='damaged private journal'


def test_repeated_invalid_finish_is_stopped(tmp_path):
    service=make_service(tmp_path)
    service.ollama=FakeOllama([finish()]*3)
    try:
        assert wait_result(service,start(service))['status']=='blocked'
    finally:
        service.close()


def test_explicit_calculator_check_is_not_a_web_search(tmp_path):
    from test_service_tools import FakeSearch
    service=make_service(tmp_path)
    service.online_search=FakeSearch()
    service.ollama=FakeOllama([call('calculate',{'expression':'(12+8)*3'}),call('calculate',{'expression':'sqrt(144)'}),finish()])
    try:
        row=wait_result(service,start(service,'Comprueba con calculate dos cuentas y verifica los resultados'))
        assert row['status']=='completed'
        assert all(item['action']=='calculate' for item in row['result']['action_results'])
    finally:
        service.close()


def test_failed_tool_invalidates_previous_completion_evidence(tmp_path):
    service=make_service(tmp_path)
    service.ollama=FakeOllama([call('calculate',{'expression':'2+2'}),call('calculate',{'expression':'sqrt(-1)'}),
        finish(),call('calculate',{'expression':'sqrt(4)'}),finish()])
    try:
        row=wait_result(service,start(service))
        assert row['status']=='completed'
        assert not row['result']['action_results'][2]['success']  # premature finish rejected
    finally:
        service.close()
