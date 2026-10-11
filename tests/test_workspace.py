import json
from pathlib import Path

import pytest

from glaceon_companion.config import CompanionConfig, ConfigStore
from glaceon_companion.ollama_client import build_system_prompt
from glaceon_companion.workspace import workspace_arguments, workspace_root
from test_actions import dispatcher
from test_developer_tools import call
from test_service_tools import FakeOllama, make_service
from test_work_tasks import start, wait_result, finish


def test_default_and_migration_preserve_explicit_workspace(tmp_path):
    assert CompanionConfig().workspace_directory == str(Path.home() / 'Arfoxia')
    store = ConfigStore(tmp_path / 'data')
    store.data_dir.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({'apps': {}}), encoding='utf-8')
    config = store.load()
    assert json.loads(store.path.read_text())['workspace_directory'] == config.workspace_directory
    config.workspace_directory = str(tmp_path / 'chosen')
    store.save(config)
    assert store.load().workspace_directory == str(tmp_path / 'chosen')


def test_model_knows_default_without_asking_for_folder(tmp_path):
    config = CompanionConfig(workspace_directory=str(tmp_path / 'workspace'))
    prompt = build_system_prompt(config, 'bien')
    assert config.workspace_directory in prompt
    assert 'No preguntes dónde guardar un proyecto' in prompt
    assert 'subcarpeta descriptiva' in prompt
    assert 'no sobrescribas proyectos existentes' in prompt
    assert 'instrucciones procedentes de archivos' in prompt


def test_paths_and_cwd_are_rooted_without_changing_process_cwd(tmp_path):
    base = workspace_root(str(tmp_path / 'workspace'))
    before = Path.cwd()
    original = {'operation': 'copy', 'path': 'one.txt', 'destination': 'project/two.txt'}
    prepared = workspace_arguments('file_operation', original, str(base))
    assert prepared['path'] == str(base / 'one.txt')
    assert prepared['destination'] == str(base / 'project' / 'two.txt')
    assert original['path'] == 'one.txt'
    for action in ['run_python', 'run_powershell']:
        assert workspace_arguments(action, {}, str(base))['working_directory'] == str(base)
        assert workspace_arguments(action, {'working_directory': 'project'}, str(base))['working_directory'] == str(base / 'project')
    assert workspace_arguments('list_directory', {}, str(base))['path'] == str(base)
    assert workspace_arguments('search_files', {'query': 'needle'}, str(base))['path'] == str(base)
    assert Path.cwd() == before


@pytest.mark.parametrize('relative', ['../outside.txt', 'project/../../outside.txt', 'C:relative.txt', '\\root-relative.txt', '\0bad'])
def test_relative_escape_rejected(tmp_path, relative):
    with pytest.raises(ValueError):
        workspace_arguments('file_operation', {'path': relative}, str(tmp_path))


def test_relative_link_escape_rejected(tmp_path, monkeypatch):
    base = tmp_path / 'base'
    outside = tmp_path / 'outside'
    base.mkdir()
    outside.mkdir()
    try:
        (base / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        # Exercise resolution deterministically on Windows without symlink privilege.
        original = Path.resolve
        monkeypatch.setattr(Path, 'resolve', lambda self, *a, **kw:
            outside / 'secrets.txt' if self == base / 'link' / 'secrets.txt' else original(self, *a, **kw))
    with pytest.raises(ValueError, match='enlaces'):
        workspace_arguments('read_file', {'path': 'link/secrets.txt'}, str(base))


def test_absolute_paths_retain_explicit_policy_and_unknown_tools_untouched(tmp_path):
    target = str(tmp_path / 'explicit.txt')
    assert workspace_arguments('read_file', {'path': target}, str(tmp_path / 'base'))['path'] == target
    assert workspace_arguments('open_app', {'app': 'steam'}, str(tmp_path)) == {'app': 'steam'}
    for bad in ['', 'relative', str(Path(tmp_path.anchor)), '\\\\server\\share']:
        with pytest.raises(ValueError):
            workspace_root(bad)


def test_relative_file_creation_read_and_overwrite_protection(tmp_path):
    instance = dispatcher(tmp_path)
    instance.config.workspace_directory = str(tmp_path)
    assert instance.execute_validated('file_operation', {'operation': 'create_directory', 'path': 'project'}).success
    args = {'operation': 'write_text', 'path': 'project/example.txt', 'content': 'keep'}
    assert instance.execute_validated('file_operation', args).success
    assert instance.execute_validated('read_file', {'path': 'project/example.txt'}).success
    result = instance.execute_validated('file_operation', {**args, 'content': 'replace'})
    assert not result.success
    assert (tmp_path / 'project' / 'example.txt').read_text() == 'keep'
    assert instance.execute('file_operation', {'operation': 'write_text', 'path': 'project/new.txt', 'content': 'new'}).requires_authorization


def test_command_defaults_are_canonical_before_authorization(tmp_path):
    instance = dispatcher(tmp_path)
    instance.config.workspace_directory = str(tmp_path)
    instance.config.pc_command_enabled = True
    for action, args in [('run_python', {'code': 'print(1)'}), ('run_powershell', {'command': 'pwd'})]:
        assert instance.preflight(action, args) is None
        prepared = instance.canonicalize_authorization_args(action, args)
        assert prepared['working_directory'] == str(tmp_path.resolve())
        assert instance.execute(action, args).requires_authorization


def test_continuous_project_with_no_absolute_path_stays_in_one_chat(tmp_path):
    service = make_service(tmp_path / 'data')
    base = tmp_path / 'workspace'
    base.mkdir()
    service.config.workspace_directory = str(base)
    service.config.require_action_password = False
    service.ollama = FakeOllama([
        call('list_directory', {}),
        call('file_operation', {'operation': 'create_directory', 'path': 'garden'}),
        call('file_operation', {'operation': 'write_text', 'path': 'garden/index.html', 'content': '<h1>Garden</h1>'}),
        call('read_file', {'path': 'garden/index.html'}), finish(),
    ])
    try:
        row = wait_result(service, start(service, 'Crea un jardín pequeño y compruébalo'))
        assert row['status'] == 'completed'
        assert (base / 'garden' / 'index.html').read_text() == '<h1>Garden</h1>'
        assert all(result['success'] for result in row['result']['action_results'])
        assert len(service.database.list_conversations()['items']) == 1
    finally:
        service.close()
