import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glaceon_companion.api import create_api
from glaceon_companion.config import PROJECT_ROOT, ConfigStore
from glaceon_companion.project_previews import CSP, ERROR_REPORTER, ProjectPreviews, html_with_error_reporter
from glaceon_companion.services import CompanionService


@pytest.fixture
def setup(tmp_path):
    store = ConfigStore(tmp_path / 'private')
    config = store.load()
    config.workspace_directory = str(tmp_path / 'projects')
    root = Path(config.workspace_directory)
    project = root / 'jardin'
    project.mkdir(parents=True)
    (project / 'index.html').write_text('<html><script src="app.js"></script><canvas></canvas></html>', encoding='utf-8')
    (project / 'app.js').write_text('document.body.dataset.ready="yes";', encoding='utf-8')
    (project / 'notas.md').write_text('<script>NO</script> & notas', encoding='utf-8')
    (root / 'otro').mkdir()
    (root / 'otro' / 'index.html').write_text('otro', encoding='utf-8')
    return store, config, root, ProjectPreviews(config)


def test_catalogue_prefers_index_and_lists_variants(setup):
    _, _, _, previews = setup
    project = next(p for p in previews.catalogue() if p['title'] == 'jardin')
    assert project['entry'] == 'jardin/index.html'
    assert project['kind'] == 'html'
    assert len(project['id']) == 32
    assert {e['kind'] for e in project['entries']} == {'html', 'text'}
    assert project['id'] == ProjectPreviews._id(project['entry'])


@pytest.mark.parametrize('name', ['.secret.html', 'secrets.json', 'config.json', 'authorization.json', 'work-tasks.json', 'program.exe', 'key.env'])
def test_private_and_unsupported_files_not_listed(setup, name):
    _, _, root, previews = setup
    (root / 'jardin' / name).write_text('private', encoding='utf-8')
    assert all(Path(e['entry']).name != name for p in previews.catalogue() for e in p['entries'])


@pytest.mark.parametrize('folder', ['.git', '.expo', 'node_modules', '.venv', '__pycache__'])
def test_generated_directories_skipped(setup, folder):
    _, _, root, previews = setup
    target = root / 'jardin' / folder
    target.mkdir()
    (target / 'index.html').write_text('private', encoding='utf-8')
    assert all(folder not in e['entry'] for p in previews.catalogue() for e in p['entries'])


def ticket(previews, entry='jardin/index.html'):
    session = previews.issue(ProjectPreviews._id(entry))
    return session, session['path'].split('/')[2]


def test_ticket_covers_only_its_project_and_can_load_local_module(setup):
    _, _, root, previews = setup
    session, cap = ticket(previews)
    assert session['expires_in'] == 1800
    assert previews.resource(cap, 'index.html')[0] == root / 'jardin/index.html'
    assert previews.resource(cap, 'app.js')[1] == 'text/javascript'
    assert 'sandbox allow-scripts;' in CSP
    assert 'allow-same-origin' not in CSP
    assert "frame-src 'none'" in CSP


@pytest.mark.parametrize('asset', ['../otro/index.html', '%2e%2e/index.html', 'other/../../index.html', 'C:/secrets.json', 'index.html:secret', 'otro\\index.html', '.git/config', 'secrets.json', '/index.html', 'https://example.com', 'index.html\x00'])
def test_preview_denies_unsafe_assets(setup, asset):
    _, _, _, previews = setup
    _, cap = ticket(previews)
    with pytest.raises((ValueError, OSError)):
        previews.resource(cap, asset)


def test_links_and_hardlinks_not_exposed(setup, tmp_path):
    _, _, root, previews = setup
    outside = tmp_path / 'private.html'
    outside.write_text('secret', encoding='utf-8')
    hardlink = root / 'jardin' / 'linked.html'
    os.link(outside, hardlink)
    with pytest.raises(ValueError):
        previews._safe_path('jardin/linked.html')
    try:
        (root / 'jardin' / 'symlink.html').symlink_to(outside)
    except OSError:
        pass  # Windows without symbolic-link privilege still checks hard links.
    else:
        with pytest.raises(ValueError):
            previews._safe_path('jardin/symlink.html')


def test_expiry_restart_workspace_change_and_deleted_file(setup, tmp_path):
    _, config, root, previews = setup
    now = [10.0]
    previews.clock = lambda: now[0]
    _, cap = ticket(previews)
    now[0] += 1801
    with pytest.raises(ValueError):
        previews.resource(cap, 'index.html')
    _, cap = ticket(previews)
    with pytest.raises(ValueError):
        ProjectPreviews(config).resource(cap, 'index.html')
    config.workspace_directory = str(tmp_path / 'different')
    with pytest.raises(ValueError):
        previews.resource(cap, 'index.html')
    config.workspace_directory = str(root)
    _, cap = ticket(previews)
    (root / 'jardin' / 'index.html').unlink()
    with pytest.raises(ValueError):
        previews.resource(cap, 'index.html')


def test_text_result_is_escaped_and_html_is_not_wrapped(setup):
    _, _, _, previews = setup
    _, cap = ticket(previews, 'jardin/notas.md')
    _, mime, text = previews.resource(cap, 'notas.md')
    assert mime == 'text/html' and '&lt;script&gt;NO&lt;/script&gt; &amp; notas' in text
    assert '<script>NO</script>' not in text
    _, cap = ticket(previews)
    assert ERROR_REPORTER in previews.resource(cap, 'index.html')[2]


@pytest.mark.parametrize('document', ['<!DOCTYPE html><HTML><HEAD><script>throw Error("x")</script></HEAD></HTML>', '<!doctype html><script>throw Error("x")</script>', '<canvas></canvas>'])
def test_errors_are_reported_before_project_scripts_without_pc_bridge(document):
    wrapped = html_with_error_reporter(document)
    assert wrapped.index(ERROR_REPORTER) <= wrapped.index('<script>throw') if '<script>throw' in wrapped else ERROR_REPORTER in wrapped
    assert wrapped.startswith('<!') if document.startswith('<!') else True
    assert 'fetch(' not in ERROR_REPORTER and 'postMessage' not in ERROR_REPORTER
    assert 'textContent=' in ERROR_REPORTER and 'innerHTML' not in ERROR_REPORTER


def test_related_requires_real_successful_tools_and_handles_command_changes(setup):
    _, _, root, previews = setup
    result = {'success': True, 'action': 'read_file', 'data': {'path': str(root / 'jardin/index.html')}}
    assert previews.related([result])[0]['title'] == 'jardin'
    assert not previews.related([{**result, 'success': False}])
    assert not previews.related([{'message': 'He creado un jardín'}])
    assert not previews.related([{**result, 'data': {'path': str(root.parent / 'private.html')}}])
    assert not previews.related([{'success': True, 'action': 'run_python', 'data': {}}])
    os.utime(root / 'jardin/index.html', (2000, 2000))
    os.utime(root / 'otro/index.html', (1000, 1000))
    os.utime(root / 'jardin/app.js', (1000, 1000))
    os.utime(root / 'jardin/notas.md', (1000, 1000))
    assert [p['title'] for p in previews.related([{'success': True, 'action': 'run_python', 'data': {}}], since=1500)] == ['jardin']


def test_authenticated_catalogue_capability_assets_and_old_chat(setup):
    store, config, root, _ = setup
    service = CompanionService(store, config)
    auth = {'Authorization': 'Bearer preview-test'}
    app = create_api(service, 'preview-test', PROJECT_ROOT / 'src/glaceon_companion/static')
    conversation = service.create_conversation('Resultado')
    metadata = {'action_results': [{'success': True, 'action': 'read_file', 'data': {'path': str(root / 'jardin/index.html')}}]}
    old = service.database.add_message('assistant', 'Antiguo', conversation_id=conversation['id'], origin='api', metadata=metadata)
    try:
        with TestClient(app) as client:
            assert client.get('/api/projects').status_code == 401
            projects = client.get('/api/projects', headers=auth).json()['projects']
            project = next(p for p in projects if p['title'] == 'jardin')
            route = f"/api/projects/{project['id']}/preview"
            assert client.post(route).status_code == 401
            assert client.post('/api/projects/not-found/preview', headers=auth).status_code == 404
            session = client.post(route, headers=auth).json()
            assert 'preview-test' not in str(session)
            page = client.get(session['path'])  # No owner Bearer in generated code.
            assert page.status_code == 200 and '<canvas>' in page.text
            assert page.headers['content-security-policy'] == CSP
            assert page.headers['cache-control'] == 'no-store'
            assert page.headers['referrer-policy'] == 'no-referrer'
            assert page.headers['access-control-allow-origin'] == '*'
            assert 'set-cookie' not in page.headers
            prefix = session['path'].rsplit('/', 1)[0]
            assert client.get(prefix + '/app.js').status_code == 200
            assert client.get(prefix + '/%2e%2e/otro/index.html').status_code == 404
            assert client.get(prefix + '/%5c..%5cindex.html').status_code == 404
            assert client.get('/project-preview/unknown/index.html').status_code == 404
            history = service.conversation_messages(conversation['id'])['messages']
            assert history[0]['metadata']['project_previews'][0]['title'] == 'jardin'
            assert 'project_previews' not in service.database.get_message(old['id'])['metadata']
            stored = service._record_assistant_message('Nuevo', conversation_id=conversation['id'], origin='api', metadata=metadata)
            assert stored['metadata']['project_previews'][0]['title'] == 'jardin'
            assert len(service.list_conversations()['conversations']) == 1
    finally:
        service.close()
