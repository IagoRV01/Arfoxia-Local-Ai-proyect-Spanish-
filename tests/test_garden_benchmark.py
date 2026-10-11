import importlib.util
import json
from pathlib import Path

import httpx
import pytest


def harness():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark_japanese_garden.py"
    spec = importlib.util.spec_from_file_location("garden_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_client(module, monkeypatch, *, fail=False):
    requests = []
    class Store:
        def api_token(self):
            return "test-token"
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["headers"]["Authorization"] == "Bearer test-token"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url):
            return httpx.Response(200, request=httpx.Request("GET", url),
                                  json={"model": "test-model", "requested_mode": "dual"})
        def post(self, url, *, json):
            requests.append((url, json))
            if url.endswith("/api/chat") and fail:
                raise httpx.ReadTimeout("private diagnostic must not be recorded")
            result = {"id": "explicit-chat"} if url.endswith("/api/conversations") else {"message": "Done"}
            return httpx.Response(200, request=httpx.Request("POST", url), json=result)
    monkeypatch.setattr(module, "ConfigStore", Store)
    monkeypatch.setattr(module.httpx, "Client", Client)
    return requests


def test_timeout_preserves_identity_without_retry_or_secret_details(tmp_path, monkeypatch):
    module = harness()
    requests = install_client(module, monkeypatch, fail=True)
    folder = tmp_path / "garden"
    module.run(folder)
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    saved = json.loads((folder / "report-request.json").read_text(encoding="utf-8"))
    assert report["outcome"] == "request_failed_result_unknown"
    assert report["request_error"] == "ReadTimeout"
    assert saved["client_message_id"] == requests[-1][1]["client_message_id"]
    assert saved["conversation_id"] == "explicit-chat"
    assert len(requests) == 2
    assert "private diagnostic" not in str(report)


def test_guided_iteration_reuses_chat_and_keeps_initial_report(tmp_path, monkeypatch):
    module = harness()
    requests = install_client(module, monkeypatch)
    (tmp_path / "report.json").write_text("initial", encoding="utf-8")
    module.run(tmp_path, followup="Corrige el error observado", conversation_id="same-chat")
    assert len(requests) == 1 and requests[0][1]["conversation_id"] == "same-chat"
    assert (tmp_path / "report.json").read_text() == "initial"
    result_path = next(path for path in tmp_path.glob("iteration-*.json")
                       if not path.name.endswith(("-request.json", "-raw-reply.json")))
    assert json.loads(result_path.read_text(encoding="utf-8"))["guided_iteration"] is True


def test_iteration_requires_explicit_chat_and_existing_folder(tmp_path):
    with pytest.raises(ValueError):
        harness().run(tmp_path, followup="Corrige")


def test_benchmark_rejects_protected_application_tree_before_creating_files(tmp_path, monkeypatch):
    module = harness()
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    destination = tmp_path / "generated"
    with pytest.raises(ValueError, match="fuera del programa"):
        module.run(destination)
    assert not destination.exists()
