import asyncio
import json
import os
import hashlib
from types import SimpleNamespace
import httpx
import pytest
from glaceon_companion.actions import ActionResult
from glaceon_companion.coding_agent import CodingEvidence, enabled, compact_screenshots
from glaceon_companion.config import CompanionConfig
from glaceon_companion.ollama_client import OllamaClient
from glaceon_companion.dual_gpu import DualGpuRuntime
from test_dual_gpu import snapshot
from test_service_tools import FakeOllama, make_service
from test_developer_tools import call
from test_work_tasks import start, wait_result, finish


@pytest.mark.parametrize('text', ['Crea una calculadora en Python', 'Arregla app.js',
    'Implement a web app and run tests', 'Refactoriza el código y comprueba sus tests'])
def test_coding_task_only_uses_target_model(text):
    assert enabled(SimpleNamespace(tier='dual',model='qwen3.8:27b-q4_K_M'),text)
    assert not enabled(SimpleNamespace(tier='small',model='qwen3.8:27b-q4_K_M'),text)
    assert not enabled(SimpleNamespace(tier='dual',model='other:27b'),text)


@pytest.mark.parametrize('text', ['Hola', '¿Qué es Python?', 'Explica cómo funciona un compilador',
    'Busca noticias de hoy', 'Crea una lista de la compra'])
def test_questions_and_unrelated_tasks_are_not_coding_jobs(text):
    assert not enabled(SimpleNamespace(tier='dual',model='qwen3.8:27b-q4_K_M'),text)


def test_evidence_survives_read_results_but_failed_execution_blocks_finish():
    ledger=CodingEvidence()
    ledger.observe('file_operation',{'path':'demo.py'},ActionResult(True,'file_operation','written'),0)
    ledger.observe('read_file',{},ActionResult(True,'read_file','read'),1)
    assert not ledger.can_finish
    passed=ActionResult(True,'run_python','ok',data={'exit_code':0,'timed_out':False})
    ledger.observe('run_python',{},passed,2)
    assert ledger.can_finish
    ledger.observe('run_python',{},ActionResult(False,'run_python','test failed',data={'exit_code':1}),3)
    ledger.observe('read_file',{},ActionResult(True,'read_file','read'),4)
    assert not ledger.can_finish and 'demo.py' in ledger.note()
    ledger.observe('run_python',{},passed,5)
    assert ledger.can_finish
    ledger.observe('file_operation',{'path':'demo.py'},ActionResult(True,'file_operation','changed'),6)
    assert not ledger.can_finish


def test_screenshot_context_retains_latest_without_mutating_archived_messages():
    messages=[{'role':'user','images':['attachment'],'content':'Crea una app'},
        {'role':'tool','tool_name':'take_screenshot','images':['old'],'content':'old'},
        {'role':'tool','tool_name':'take_screenshot','images':['new'],'content':'new'}]
    compact=compact_screenshots(messages)
    assert compact[0]['images']==['attachment'] and compact[2]['images']==['new']
    assert 'images' not in compact[1] and messages[1]['images']==['old']


def test_dual_coding_keeps_extra_high_and_gpu_options_but_more_reasoning_room(monkeypatch):
    client=OllamaClient(CompanionConfig())
    monkeypatch.setattr(DualGpuRuntime,'owned',property(lambda _:True))
    requests=[]
    chunks=[{'message':{'thinking':'x'*9000}}, {'message':{'content':'Working'},'done':True}]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,text='\n'.join(json.dumps(c) for c in chunks),
            headers={'content-type':'application/x-ndjson'})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    result=asyncio.run(client.chat([{'role':'user','content':'Crea una calculadora en Python'}],'bien',
        turn_text='Crea una calculadora en Python',selection=client._dual_selection(snapshot(client.config))))
    assert len(requests)==1 and result['message']['content']=='Working'
    payload=requests[0]
    assert 'AGENTE DE CÓDIGO' in payload['messages'][0]['content']
    assert payload['think']=='high' and payload['keep_alive']==-1
    assert payload['options']==client.dual.options()
    assert payload['options']['num_ctx']==32768 and 'main_gpu' not in payload['options']


def test_coding_work_cannot_finish_after_read_or_failed_tests(tmp_path):
    service=make_service(tmp_path)
    path=tmp_path/'example.py'
    service.config.require_action_password=False
    fake=FakeOllama([
        call('file_operation',{'operation':'write_text','path':str(path),'content':'value=1'}),
        call('read_file',{'path':str(path)}),finish(),
        call('run_python',{'code':'assert False'}),
        call('read_file',{'path':str(path)}),finish(),
        call('run_python',{'code':'assert 1 == 1'}),finish(),
    ])
    service.ollama=fake
    selection=OllamaClient(service.config)._dual_selection(snapshot(service.config))
    async def select(): return selection
    service._select_turn_model=select
    original=service._execute_chat_action
    def execute(action,args,**kw):
        if action=='run_python':
            ok=args['code']!='assert False'
            return ActionResult(ok,action,'ok' if ok else 'failed',
                data={'exit_code':0 if ok else 1,'timed_out':False})
        return original(action,args,**kw)
    service._execute_chat_action=execute
    try:
        row=wait_result(service,start(service,'Crea un programa Python y ejecuta los tests'))
        assert row['status']=='completed'
        results=row['result']['action_results']
        assert sum(r['action']=='finish_task' and not r['success'] for r in results)==2
        assert row['result']['coding_agent']['execution_verified']
        assert all(option['coding_agent'] for option in fake.options)
        assert any('Registro del agente' in msg.get('content','') for msg in fake.requests[-1])
        assert len(service.database.list_conversations()['items'])==1
    finally: service.close()


@pytest.mark.skipif(os.name != 'nt', reason='Real Arfoxia command runner uses Windows PowerShell')
def test_real_python_tests_fail_then_patch_and_pass_without_model_download(tmp_path):
    service=make_service(tmp_path)
    service.config.require_action_password=False
    service.config.pc_command_enabled=True
    service.config.workspace_directory=str(tmp_path)
    path=tmp_path/'calculator.py'
    source='def add(a, b):\n    return a - b\n'
    test_source='import unittest\nfrom calculator import add\nclass TestAdd(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n'
    runner='import unittest,sys; result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(".",pattern="test_*.py")); sys.exit(not result.wasSuccessful())'
    service.ollama=FakeOllama([
        call('file_operation',{'operation':'write_text','path':str(path),'content':source}),
        call('file_operation',{'operation':'write_text','path':str(tmp_path/'test_calculator.py'),'content':test_source}),
        call('run_python',{'code':runner,'working_directory':str(tmp_path)}),
        call('read_file',{'path':str(path)}),
        call('file_operation',{'operation':'replace_text','path':str(path),
            'old_text':'return a - b','new_text':'return a + b',
            'expected_sha256':hashlib.sha256(source.encode()).hexdigest()}),
        call('run_python',{'code':runner,'working_directory':str(tmp_path)}),
        finish('Calculadora corregida','unittest: una prueba correcta después de corregir add'),
    ])
    selection=OllamaClient(service.config)._dual_selection(snapshot(service.config))
    async def select(): return selection
    service._select_turn_model=select
    try:
        row=wait_result(service,start(service,'Crea una calculadora en Python y ejecuta los tests'))
        assert row['status']=='completed'
        executions=[r for r in row['result']['action_results'] if r['action']=='run_python']
        assert [r['success'] for r in executions]==[False,True]
        assert 'FAILED' in executions[0]['data']['stdout']
        assert 'OK' in executions[1]['data']['stdout']
        assert path.read_text()=='def add(a, b):\n    return a + b\n'
        assert row['result']['coding_agent']['execution_verified']
    finally: service.close()


def test_coding_can_consult_docs_then_use_local_tools(tmp_path):
    from test_service_tools import FakeSearch
    service=make_service(tmp_path)
    service.config.require_action_password=False
    service.online_search=FakeSearch()
    path=tmp_path/'example.py'
    fake=FakeOllama([
        call('web_search',{'query':'Python official documentation'}),
        call('file_operation',{'operation':'write_text','path':str(path),'content':'value=1'}),
        call('run_python',{'code':'assert 1 == 1'}),finish(),
    ])
    service.ollama=fake
    selection=OllamaClient(service.config)._dual_selection(snapshot(service.config))
    async def select(): return selection
    service._select_turn_model=select
    original=service._execute_chat_action
    def execute(action,args,**kw):
        if action=='run_python':
            return ActionResult(True,action,'ok',data={'exit_code':0,'timed_out':False})
        return original(action,args,**kw)
    service._execute_chat_action=execute
    try:
        row=wait_result(service,start(service,'Crea una app Python y busca documentación actual en internet'))
        assert row['status']=='completed' and path.read_text()=='value=1'
        for option in fake.options:
            assert {'file_operation','web_search','run_python'} <= option['tools']
    finally: service.close()
