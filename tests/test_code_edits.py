import hashlib
import pytest
from glaceon_companion.developer_tools import local_tool
from test_actions import dispatcher


def edit(path, old, new):
    return dict(operation="replace_text", path=str(path), old_text=old, new_text=new,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def test_read_hash_edit_preserves_other_code_and_newlines(tmp_path):
    path = tmp_path/"sample.py"
    path.write_bytes(b'\xef\xbb\xbfdef add(a, b):\r\n    return a - b\r\n# keep\r\n')
    data = local_tool("read_file", {"path":str(path)})
    args = edit(path, 'def add(a, b):\n    return a - b', 'def add(a, b):\n    return a + b')
    assert data["sha256"] == args["expected_sha256"]
    result = dispatcher(tmp_path).execute_validated("file_operation", args)
    assert result.success
    assert path.read_bytes() == b'\xef\xbb\xbfdef add(a, b):\r\n    return a + b\r\n# keep\r\n'
    assert result.data["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('scenario', ['stale', 'duplicate', 'missing', 'empty', 'nochange', 'nul'])
def test_ambiguous_or_stale_edit_never_overwrites(tmp_path, scenario):
    path = tmp_path/"sample.py"
    path.write_text('return 1\nreturn 1' if scenario=='duplicate' else 'return 1')
    args = edit(path, 'return 1', 'return 2')
    if scenario=='stale': path.write_text('user changed it')
    if scenario=='missing': args['old_text']='missing'
    if scenario=='empty': args['old_text']=''
    if scenario=='nochange': args['new_text']=args['old_text']
    if scenario=='nul': args['new_text']='\0'
    before = path.read_bytes()
    result = dispatcher(tmp_path).execute_validated("file_operation", args)
    assert not result.success and path.read_bytes()==before


def test_edit_keeps_authorization_and_redacts_source(tmp_path):
    path=tmp_path/'sample.py'; path.write_text('private-source')
    action=dispatcher(tmp_path)
    args=edit(path,'private-source','private-replacement')
    result=action.execute('file_operation',args)
    assert result.requires_authorization and path.read_text()=='private-source'
    redacted=action._redact_arguments('file_operation',args)
    assert redacted['old_text']['redacted'] and redacted['new_text']['redacted']
    assert 'private-source' not in str(redacted)
    bound=action.canonicalize_authorization_args('file_operation',args)
    path.write_text('changed during approval')
    assert not action.execute_validated('file_operation',bound).success
    assert path.read_text()=='changed during approval'


def test_edit_protected_program_source_still_refused(tmp_path):
    from glaceon_companion.config import PROJECT_ROOT
    path=PROJECT_ROOT/'src/glaceon_companion/actions.py'
    args=edit(path,'dummy-anchor','new')
    result=dispatcher(tmp_path).execute_validated('file_operation',args)
    assert not result.success and 'protegidos' in result.message
