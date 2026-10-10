import asyncio
from pathlib import Path

import pytest

from glaceon_companion.developer_tools import calculate, local_tool, validate_python
from glaceon_companion.actions import ActionResult
from glaceon_companion.web_reader import TextExtractor, WebPageReader
from test_actions import dispatcher
from test_service_tools import make_service, FakeOllama, chat_in_new_conversation


def test_read_and_search_are_bounded_and_skip_dependencies(tmp_path):
    (tmp_path / "demo.txt").write_text("first\nneedle\nlast", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.txt").write_text("needle")
    result = local_tool("read_file", {"path": str(tmp_path / "demo.txt"), "start_line": 2, "max_lines": 1})
    assert result["content"] == "2: needle" and result["truncated"]
    assert len(local_tool("search_files", {"path": str(tmp_path), "query": "needle"})["matches"]) == 1
    assert local_tool("list_directory", {"path": str(tmp_path), "limit": 1})["truncated"]


@pytest.mark.parametrize("expression", ["__import__('os')", "2**100000", "[1]*99999", "True", "sqrt(-1)"])
def test_calculator_rejects_code_and_unbounded_work(expression):
    with pytest.raises((ValueError, ArithmeticError)):
        calculate(expression)


def test_calculator_and_binary_files(tmp_path):
    assert calculate("sqrt(4) + 2**3") == 10
    path = tmp_path / "binary"
    path.write_bytes(b"\0x")
    with pytest.raises(ValueError):
        local_tool("read_file", {"path": str(path)})
    with pytest.raises(ValueError):
        local_tool("read_file", {"path": "relative.txt"})
    with pytest.raises(ValueError):
        validate_python({"code": "print(1)", "working_directory": str(tmp_path), "timeout_seconds": 121})


def test_python_uses_existing_sensitive_policy_and_redacts_source(tmp_path):
    instance = dispatcher(tmp_path)
    assert instance.is_sensitive("run_python")
    result = instance.execute_validated("run_python", {"code": "print(1)"})
    assert not result.success
    assert "desactivado" in result.message
    assert instance._redact_arguments("run_python", {"code": "private"})["code"]["redacted"]


def test_web_reader_respects_disabled_web_config(tmp_path):
    instance = dispatcher(tmp_path)
    instance.config.online_search_enabled = False
    assert not instance.execute_validated("read_webpage", {"url": "https://example.com"}).success


def test_web_reader_filters_scripts_and_private_redirects():
    parser = TextExtractor()
    parser.feed("<p>Visible</p><script>secret</script><style>hidden</style>")
    assert "Visible" in "".join(parser.parts) and "secret" not in "".join(parser.parts)
    reader = WebPageReader(resolver=lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))])
    with pytest.raises(ValueError):
        reader.read("https://127.0.0.1/")
    reader._fetch = lambda url: (302, {"location": "https://192.168.0.1/"}, b"", False)
    with pytest.raises(ValueError, match="Redirección"):
        reader.read("https://example.com/")
    reader._fetch = lambda url: (200, {"content-type": "text/html"}, b"<h1>Test</h1><script>ignore me</script>", False)
    assert reader.read("https://example.com/")["content"] == "Test"
    payload = reader.read("https://example.com/")
    assert payload["results"][0]["availability"] == "verified"
    assert make_verified_urls(payload) == {"https://example.com/"}


def make_verified_urls(payload):
    from glaceon_companion.services import CompanionService
    return CompanionService._verified_urls_from_actions([
        ("read_webpage", ActionResult(True, "read_webpage", "Página leída", data=payload))])


def call(name, args):
    return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}}


def test_chat_can_calculate_then_verify_in_same_conversation(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([call("calculate", {"expression": "2+2"}),
                                call("calculate", {"expression": "4*2"}),
                                {"message": {"content": "Resultado verificado: 8"}}])
    try:
        result = asyncio.run(chat_in_new_conversation(service, "Calcula dos más dos y después multiplícalo por dos"))
        assert len(result["action_results"]) == 2
        assert all(r["success"] for r in result["action_results"])
        rows = service.database.list_conversations()["items"]
        assert len(rows) == 1 and rows[0]["id"] == result["conversation_id"]
    finally:
        service.close()


def test_later_round_still_requires_authorization(tmp_path):
    service = make_service(tmp_path)
    service.config.pc_command_enabled = True
    service.ollama = FakeOllama([call("calculate", {"expression": "1+1"}),
                                call("run_python", {"code": "print(2)", "working_directory": str(tmp_path)})])
    try:
        result = asyncio.run(chat_in_new_conversation(service, "Calcula y comprueba con Python"))
        assert result["requires_authorization"] and result["challenge_id"]
        assert result["action_results"][-1]["requires_authorization"]
    finally:
        service.close()


def test_workflow_has_finite_rounds_and_blocks_out_of_scope_tools(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([call("calculate", {"expression": "1+1"}) for _ in range(7)])
    try:
        result = asyncio.run(chat_in_new_conversation(service, "Calcula algo"))
        assert len(result["action_results"]) == 6
        assert "incompleta" in result["message"]
        assert service.ollama.options[-1]["tools"] is False
    finally:
        service.close()


def test_web_followup_cannot_execute_pc_code(tmp_path):
    from test_service_tools import FakeSearch
    service = make_service(tmp_path)
    service.online_search = FakeSearch()
    service.ollama = FakeOllama([{"message": {"content": "Consultaré las fuentes"}},
                                call("run_python", {"code": "print('not allowed')"}),
                                {"message": {"content": "Respuesta con fuentes"}}])
    try:
        result = asyncio.run(chat_in_new_conversation(service, "Busca información en internet sobre jardines japoneses"))
        assert result["action_results"][-1]["action"] == "run_python"
        assert not result["action_results"][-1]["success"]
        assert "no habilitada" in result["action_results"][-1]["message"]
    finally:
        service.close()


def test_web_reader_rejects_mixed_public_private_dns():
    reader = WebPageReader(resolver=lambda *a, **k: [
        (None, None, None, None, ("8.8.8.8", 443)),
        (None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        reader.read("https://example.com/")


def test_empty_generation_reports_failure_instead_of_greeting(tmp_path):
    service = make_service(tmp_path)
    service.ollama = FakeOllama([{"message": {"content": "", "thinking": "private reasoning"},
                                "done_reason": "length"}])
    try:
        result = asyncio.run(chat_in_new_conversation(service, "Crea el programa solicitado"))
        assert result["generation_empty"] and result["generation_limit_reached"]
        assert "no se ha completado" in result["message"]
        assert "private reasoning" not in str(result)
    finally:
        service.close()
