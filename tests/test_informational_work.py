"""Regressions for informational queries accidentally trapped in the agent loop."""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from test_search_routing import TrackingSearch
from test_service_tools import FakeOllama, make_service
from test_work_tasks import start, wait_result
from glaceon_companion.services import required_web_action, web_answer_request, progress_only_reply
from glaceon_companion.temporal import TemporalContext
from test_developer_tools import call

WEATHER = 'Me podrías decir cual es el tiempo para mañana en Allariz y Ourense ?'
QWEN = 'Hola Arfoxia, qué tal ? Me gustaría que buscaras que potencia va a tener qwen 4 comparando a modelos equivalentes de Anthropic y OpenAI'


@pytest.mark.parametrize('question', [WEATHER, QWEN,
    'Quiero que busques información oficial sobre Qwen 4 y la compares con Anthropic y OpenAI',
    'Verifica en internet si hay datos confirmados de Qwen 4'])
def test_web_answer_ends_normally_after_search_without_finish_task(tmp_path, question):
    service=make_service(tmp_path)
    service._temporal_context_factory=lambda: TemporalContext.current(datetime(2026,10,22,12,tzinfo=ZoneInfo('Europe/Madrid')))
    search=TrackingSearch()
    service.online_search=search
    answer='Las fuentes consultadas no ofrecen datos suficientes para una conclusión fiable. [Fuente](https://example.com/allariz-horas)'
    fake=FakeOllama([{'message':{'content':'Consultaré las fuentes.'}}] +
        [{'message':{'content':answer}}]*3)
    service.ollama=fake
    try:
        row=wait_result(service,start(service,question))
        assert row['status']=='completed'
        assert row['result']['message'].startswith('Las fuentes consultadas no ofrecen datos suficientes')
        assert 'https://example.com/allariz-horas' in row['result']['message']
        assert len(fake.requests)==2
        assert len(search.search_calls)==1
        if question==WEATHER:
            query,args=search.search_calls[0]
            assert 'Allariz' in query and 'Ourense' in query
            assert args['date_from']=='2026-10-23' and args['date_to']=='2026-10-23'
        assert [r['action'] for r in row['result']['action_results']]==['web_search']
        assert len(service.database.list_conversations()['items'])==1
    finally: service.close()


def test_polite_imperfect_search_is_routed_and_query_has_no_greeting():
    action,args=required_web_action(QWEN)
    assert action=='web_search'
    query=args['query'].casefold()
    assert 'qwen 4' in query and 'anthropic' in query and 'openai' in query
    assert 'hola' not in query and 'qué tal' not in query and 'me gustaría' not in query


@pytest.mark.parametrize('text', ['No quiero que buscaras datos', 'No busques noticias',
    'No consultaras internet para esto'])
def test_negation_of_new_search_forms_still_blocks_forced_search(text):
    assert required_web_action(text) is None


@pytest.mark.parametrize('text', ['Busca datos y guárdalos en un archivo',
    'Busca fuentes y crea un PDF', 'Investiga el problema y ejecuta este script',
    'Search then create a project', 'Busca el sitio y abre su enlace'])
def test_lookup_with_file_or_pc_deliverable_is_not_answer_only(text):
    assert not web_answer_request(text)


@pytest.mark.parametrize('text', ['Busca cómo guardar archivos en Python',
    'Busca cómo guardar y ejecutar un script', 'Investiga qué programa crea PDF',
    'Quiero que busques si Qwen 4 supera a otros modelos', 'Haz una tabla con los datos encontrados'])
def test_search_topics_or_inline_tables_do_not_become_pc_jobs(text):
    assert web_answer_request(text)


@pytest.mark.parametrize('reply', ['Voy a buscar la previsión.', 'Consultaré las fuentes.',
    '¡Gla-ceon! *agita la cola* Voy a consultar el tiempo.', 'Let me check that.'])
def test_progress_notices_are_not_final_answers(reply):
    assert progress_only_reply(reply)


@pytest.mark.parametrize('reply', ['No encontré información verificable.',
    'Déjame explicarte: las fuentes no confirman ese dato.',
    'En Allariz se prevén 15 °C y en Ourense 17 °C.',
    '[Fuente](https://example.com)'])
def test_substantive_answers_are_not_progress_notices(reply):
    assert not progress_only_reply(reply)


def test_promise_after_search_is_nudged_without_repeating_search_or_requiring_finish(tmp_path):
    service=make_service(tmp_path)
    search=TrackingSearch(); service.online_search=search
    fake=FakeOllama([{'message':{'content':'Voy a buscar.'}},
        {'message':{'content':'Voy a consultar las fuentes.'}},
        {'message':{'content':'No encontré datos suficientes en las fuentes consultadas.'}}])
    service.ollama=fake
    try:
        row=wait_result(service,start(service,WEATHER))
        assert row['status']=='completed' and len(search.search_calls)==1
        assert len(fake.requests)==3
        assert all('finish_task' not in option['tools'] for option in fake.options)
        assert 'no necesitas finish_task' in str(fake.requests[-1])
        assert all('run_python' not in option['tools'] for option in fake.options)
    finally: service.close()


@pytest.mark.parametrize('truncated',[False,True])
def test_three_promises_or_incomplete_generations_still_stop(tmp_path,truncated):
    service=make_service(tmp_path); service.online_search=TrackingSearch()
    reply={'message':{'content':'La previsión indica datos incompletos' if truncated else 'Voy a buscar.'}}
    if truncated: reply['done_reason']='length'
    service.ollama=FakeOllama([{'message':{'content':'Buscaré.'}}]+[reply]*3)
    try:
        row=wait_result(service,start(service,WEATHER))
        assert row['status']=='blocked'
    finally: service.close()


def test_search_failure_can_be_explained_without_a_false_loop_error(tmp_path):
    from glaceon_companion.online_search import OnlineSearchError
    class Failure:
        def search_payload(self,*args,**kwargs): raise OnlineSearchError('Proveedor no disponible')
    service=make_service(tmp_path); service.online_search=Failure()
    service.ollama=FakeOllama([{'message':{'content':'Buscaré.'}},
        {'message':{'content':'La consulta falló; no tengo fuentes verificadas para responder.'}}])
    try:
        row=wait_result(service,start(service,WEATHER))
        assert row['status']=='completed' and 'consulta falló' in row['result']['message']
        assert not row['result']['action_results'][0]['success']
        assert not row['result'].get('sources')
    finally: service.close()


def test_plain_answer_does_not_finish_a_file_deliverable(tmp_path):
    service=make_service(tmp_path); service.online_search=TrackingSearch()
    service.ollama=FakeOllama([{'message':{'content':'Buscaré.'}}]+
        [{'message':{'content':'He encontrado algunas fuentes.'}}]*3)
    try:
        row=wait_result(service,start(service,'Busca datos y guarda el informe en un archivo'))
        assert row['status']=='blocked'
    finally: service.close()


def test_question_with_readonly_calculation_can_answer_naturally(tmp_path):
    service=make_service(tmp_path)
    service.ollama=FakeOllama([call('calculate',{'expression':'2+2'}),{'message':{'content':'Son 4.'}}])
    try:
        row=wait_result(service,start(service,'¿Cuánto es 2+2?'))
        assert row['status']=='completed' and row['result']['message']=='Son 4.'
    finally: service.close()
