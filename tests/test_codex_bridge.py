from __future__ import annotations

from collections import defaultdict
import sys
from typing import Any

import pytest

from glaceon_companion.codex_bridge import (
    AmbiguousTaskError,
    CodexAppServerClient,
    CodexBridge,
    CodexProtocolError,
    NoActiveTurnError,
)


THREAD_A = "019f79db-0ad8-7c81-aa05-5b4c261a4821"
THREAD_B = "019f79db-0ad8-7c81-aa05-5b4c261a4822"
TURN_A = "019f79db-0ad8-7c81-aa05-5b4c261a4999"


FAKE_APP_SERVER = r"""
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        print(json.dumps({"id": message["id"], "result": {}}), flush=True)
    elif method == "initialized":
        continue
    elif method == "thread/list":
        # Un app-server puede iniciar solicitudes (p. ej. permisos). Arfoxia debe
        # rechazarlas, nunca confirmarlas de manera automática.
        print(json.dumps({"id": "server-request", "method": "requestApproval", "params": {}}), flush=True)
        rejection = json.loads(sys.stdin.readline())
        denied = rejection.get("error", {}).get("code") == -32601
        result = {"data": [], "nextCursor": None, "serverRequestDenied": denied}
        print(json.dumps({"id": message["id"], "result": result}), flush=True)
"""


def task(thread_id: str, name: str, status: str = "active") -> dict[str, Any]:
    return {
        "id": thread_id,
        "name": name,
        "preview": f"Vista previa de {name}",
        "status": {"type": status, "activeFlags": []} if status == "active" else {"type": status},
        "cwd": "C:\\proyectos\\demo",
        "updatedAt": 42,
    }


class FakeClient:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self.responses = defaultdict(list, responses)
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.requests.append((method, params or {}))
        assert self.responses[method], f"No hay respuesta simulada para {method}"
        return self.responses[method].pop(0)


def bridge_with(responses: dict[str, list[Any]]) -> tuple[CodexBridge, FakeClient]:
    fake = FakeClient(responses)
    return CodexBridge(lambda: fake), fake


def test_jsonl_stdio_client_initializes_and_never_auto_approves_server_requests():
    command = (sys.executable, "-u", "-c", FAKE_APP_SERVER)

    with CodexAppServerClient(command, timeout_seconds=3) as client:
        result = client.request("thread/list", {"limit": 1})

    assert result["serverRequestDenied"] is True


def test_lists_tasks_over_thread_list_without_mutating_anything():
    bridge, fake = bridge_with(
        {"thread/list": [{"data": [task(THREAD_A, "Proyecto hielo")], "nextCursor": None}]}
    )

    result = bridge.list_tasks(limit=10)

    assert result[0].name == "Proyecto hielo"
    assert result[0].status == "active"
    assert [method for method, _ in fake.requests] == ["thread/list"]
    assert fake.requests[0][1]["sourceKinds"] == CodexBridge.SOURCE_KINDS


def test_opens_only_the_resolved_task_deep_link():
    fake = FakeClient(
        {"thread/list": [{"data": [task(THREAD_A, "Proyecto hielo")], "nextCursor": None}]}
    )
    opened: list[str] = []
    bridge = CodexBridge(lambda: fake, uri_opener=opened.append)

    result = bridge.open_task("Proyecto hielo")

    assert result.thread_id == THREAD_A
    assert opened == [f"codex://threads/{THREAD_A}"]


def test_resolver_prefers_one_exact_accent_insensitive_title():
    bridge, _ = bridge_with(
        {
            "thread/list": [
                {
                    "data": [
                        task(THREAD_A, "Añadir métricas"),
                        task(THREAD_B, "Añadir métricas antiguas", "idle"),
                    ],
                    "nextCursor": None,
                }
            ]
        }
    )

    resolved = bridge.resolve_task("ANADIR METRICAS")

    assert resolved.thread_id == THREAD_A


def test_resolver_rejects_an_ambiguous_partial_title():
    bridge, fake = bridge_with(
        {
            "thread/list": [
                {
                    "data": [
                        task(THREAD_A, "Proyecto hielo principal"),
                        task(THREAD_B, "Proyecto hielo secundario"),
                    ],
                    "nextCursor": None,
                }
            ]
        }
    )

    with pytest.raises(AmbiguousTaskError) as error:
        bridge.resolve_task("proyecto hielo")

    assert len(error.value.candidates) == 2
    assert [method for method, _ in fake.requests] == ["thread/list"]


def test_pause_rereads_turn_and_interrupts_using_only_ids():
    bridge, fake = bridge_with(
        {
            "thread/list": [
                {"data": [task(THREAD_A, "Proyecto hielo")], "nextCursor": None}
            ],
            "thread/read": [
                {
                    "thread": {
                        "id": THREAD_A,
                        "turns": [
                            {"id": THREAD_B, "status": "completed"},
                            {"id": TURN_A, "status": "inProgress"},
                        ],
                    }
                }
            ],
            "turn/interrupt": [{}],
        }
    )

    result = bridge.pause_task("Proyecto hielo")

    assert result.success
    assert result.turn_id == TURN_A
    assert fake.requests[-1] == (
        "turn/interrupt",
        {"threadId": THREAD_A, "turnId": TURN_A},
    )


def test_pause_does_nothing_when_no_turn_is_active():
    bridge, fake = bridge_with(
        {
            "thread/list": [
                {"data": [task(THREAD_A, "Proyecto hielo", "idle")], "nextCursor": None}
            ],
            "thread/read": [
                {
                    "thread": {
                        "id": THREAD_A,
                        "turns": [{"id": TURN_A, "status": "completed"}],
                    }
                }
            ],
        }
    )

    with pytest.raises(NoActiveTurnError):
        bridge.pause_task("Proyecto hielo")

    assert "turn/interrupt" not in [method for method, _ in fake.requests]


def test_pause_rejects_a_mismatched_thread_response():
    bridge, fake = bridge_with(
        {
            "thread/list": [
                {"data": [task(THREAD_A, "Proyecto hielo")], "nextCursor": None}
            ],
            "thread/read": [
                {
                    "thread": {
                        "id": THREAD_B,
                        "turns": [{"id": TURN_A, "status": "inProgress"}],
                    }
                }
            ],
        }
    )

    with pytest.raises(CodexProtocolError):
        bridge.pause_task("Proyecto hielo")

    assert "turn/interrupt" not in [method for method, _ in fake.requests]
