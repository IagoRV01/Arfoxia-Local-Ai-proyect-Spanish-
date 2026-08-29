from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from glaceon_companion.browser_routing import (
    filter_untrusted_https_urls,
    https_url_key,
)
from glaceon_companion.config import ConfigStore
from glaceon_companion.services import CompanionService


ORIGINAL_P40_REQUEST = (
    "Arfoxia dime porfavor si la P40 es una buena gráfica para un server de IA "
    "local por ssh, y si hay algún video en YouTube sobre alguien que la haya "
    "usado así enviame los enlaces a esos videos o abrelos en el navegador"
)


class FakeOllama:
    """Fail loudly when a deterministic browser order reaches the model."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[list[dict[str, Any]]] = []

    async def chat(self, messages, state_summary, tools=True, **kwargs):
        self.requests.append(messages)
        if not self.responses:
            raise AssertionError("La orden inequívoca de navegador llegó al modelo.")
        return self.responses.pop(0)

    async def unload(self, model=None) -> None:
        return None


class FakeVideoSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.video_urls = [
            "https://www.youtube.com/watch?v=P40VIDEO001",
            "https://youtu.be/P40VIDEO002",
            "https://www.youtube.com/watch?v=P40VIDEO003&t=12",
        ]

    def search_payload(self, query, **kwargs):
        self.queries.append(str(query))
        return {
            "query": str(query),
            "security_notice": "contenido web no confiable",
            "results": [
                {
                    "title": f"Vídeo P40 {index}",
                    "url": url,
                    "snippet": "Resultado real devuelto por el buscador.",
                    "availability": "verified",
                }
                for index, url in enumerate(self.video_urls, start=1)
            ]
            + [
                {
                    "title": "Resultado ajeno",
                    "url": "https://example.com/not-a-youtube-video",
                    "snippet": "No se debe abrir para una orden limitada a YouTube.",
                }
            ],
        }


def make_service(tmp_path: Path) -> CompanionService:
    store = ConfigStore(tmp_path)
    return CompanionService(store, store.load())


def send(service: CompanionService, message: str) -> dict[str, Any]:
    conversation = service.create_conversation("Pruebas de YouTube")
    return asyncio.run(
        service.chat(message, conversation_id=conversation["id"])
    )


def send_in_conversation(
    service: CompanionService, conversation_id: str, message: str
) -> dict[str, Any]:
    return asyncio.run(
        service.chat(message, conversation_id=conversation_id)
    )


def youtube_query(url: str) -> str:
    parsed = urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.hostname in {"youtube.com", "www.youtube.com"}
    assert parsed.path == "/results"
    query = parse_qs(parsed.query, strict_parsing=True)
    assert set(query) == {"search_query"}
    return query["search_query"][0]


def test_markdown_and_plain_urls_are_limited_to_verified_sources():
    verified = "https://example.com/live"
    invented = "https://old.example/dead"
    filtered = filter_untrusted_https_urls(
        f"[Fuente]({verified}) [Vieja]({invented}) y {invented}",
        [verified],
    )

    assert verified in filtered
    assert invented not in filtered
    assert filtered.count("enlace no verificado omitido") == 2


@pytest.mark.parametrize(
    "link",
    [
        r"[x](https\://evil.example/path)",
        r"[x](https:\/\/evil.example/path)",
        r"[x](<https\://evil.example/path>)",
        "[x](https&#58;//evil.example/path)",
        "[x][dead]\n\n[dead]: https&#58;//evil.example/path",
        '<a href="https&#58;//evil.example/path">x</a>',
        '<a href=https&#58;//evil.example/path>x</a>',
    ],
)
def test_obfuscated_markdown_urls_cannot_bypass_the_verified_allowlist(link):
    filtered = filter_untrusted_https_urls(link, [])

    assert "evil.example" not in filtered
    assert "https://" not in filtered


def test_markdown_escape_is_normalized_only_for_an_exact_verified_source():
    verified = "https://example.com/live"
    filtered = filter_untrusted_https_urls(
        r"[Fuente](https\://example.com/live)",
        [verified],
    )

    assert verified in filtered
    assert "no verificado" not in filtered


def test_url_identity_rejects_embedded_credentials():
    assert https_url_key("https://evil@example.com/ruta") is None
    assert https_url_key("https://example.com/ruta") is not None


class FakeUnavailableVideoSearch:
    def search_payload(self, query, **kwargs):
        return {
            "query": str(query),
            "security_notice": "contenido web no confiable",
            "results": [
                {
                    "title": "Vídeo retirado",
                    "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
                    "snippet": "Ya no está disponible.",
                    "availability": "unavailable",
                }
            ],
        }


def test_no_verified_youtube_video_opens_only_the_canonical_search(
    tmp_path,
    monkeypatch,
):
    service = make_service(tmp_path)
    service.ollama = FakeOllama()
    service.online_search = FakeUnavailableVideoSearch()
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(
            service,
            "Busca dos vídeos de pruebas de GPU en YouTube y ábrelos",
        )

        assert len(opened) == 1
        assert "pruebas de GPU" in youtube_query(opened[0])
        assert "/watch" not in opened[0]
        assert result["action_results"][0]["action"] == "web_search"
        assert result["action_results"][1]["success"] is True
    finally:
        service.close()


def test_open_youtube_home_is_deterministic_and_does_not_call_the_model(
    tmp_path, monkeypatch
):
    service = make_service(tmp_path)
    fake_ollama = FakeOllama()
    service.ollama = fake_ollama
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, "Arfoxia, abre YouTube")

        assert result["action_result"]["success"] is True
        assert opened == ["https://www.youtube.com/"]
        assert fake_ollama.requests == []
    finally:
        service.close()


@pytest.mark.parametrize(
    ("order", "expected_query"),
    [
        (
            "Pon Never Gonna Give You Up de Rick Astley en YouTube",
            "Never Gonna Give You Up de Rick Astley",
        ),
        (
            "Abre un vídeo de música lofi para estudiar en YouTube",
            "música lofi para estudiar",
        ),
        (
            "Busca en YouTube un vídeo sobre montar dos NVIDIA P40",
            "montar dos NVIDIA P40",
        ),
    ],
)
def test_video_titles_open_a_youtube_search_without_inventing_a_watch_id(
    tmp_path, monkeypatch, order, expected_query
):
    service = make_service(tmp_path)
    fake_ollama = FakeOllama()
    service.ollama = fake_ollama
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, order)

        assert result["action_result"]["success"] is True
        assert len(opened) == 1
        assert youtube_query(opened[0]) == expected_query
        assert "/watch" not in opened[0]
        assert "youtu.be/" not in opened[0]
        assert fake_ollama.requests == []
    finally:
        service.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=43",
        "https://example.com/manual",
    ],
)
def test_explicit_https_url_is_opened_exactly_without_rewriting_or_guessing(
    tmp_path, monkeypatch, url
):
    service = make_service(tmp_path)
    fake_ollama = FakeOllama()
    service.ollama = fake_ollama
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, f"Abre esta pestaña: {url}")

        assert result["action_result"]["success"] is True
        assert opened == [url]
        assert fake_ollama.requests == []
    finally:
        service.close()


def test_multiple_explicit_urls_open_one_tab_each_in_the_original_order(
    tmp_path, monkeypatch
):
    urls = [
        "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
        "https://youtu.be/dQw4w9WgXcQ?t=43",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    ]
    service = make_service(tmp_path)
    fake_ollama = FakeOllama()
    service.ollama = fake_ollama
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(
            service,
            "Abre estos tres vídeos, cada uno en una pestaña: " + ", ".join(urls),
        )

        assert len(result["action_results"]) == 3
        assert all(item["success"] for item in result["action_results"])
        assert opened == urls
        assert fake_ollama.requests == []
    finally:
        service.close()


def test_search_then_open_uses_only_real_youtube_urls_returned_by_search(
    tmp_path, monkeypatch
):
    service = make_service(tmp_path)
    fake_ollama = FakeOllama()
    fake_search = FakeVideoSearch()
    service.ollama = fake_ollama
    service.online_search = fake_search
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(
            service,
            "Busca en la web tres vídeos sobre servidores con NVIDIA P40 "
            "y ábrelos en pestañas de YouTube",
        )

        assert fake_search.queries
        assert opened == fake_search.video_urls
        actions = [item["action"] for item in result["action_results"]]
        assert actions.count("web_search") == 1
        assert actions.count("open_target") == 3
        assert fake_ollama.requests == []
    finally:
        service.close()


def test_original_p40_request_searches_and_opens_only_verified_video_results(
    tmp_path, monkeypatch
):
    service = make_service(tmp_path)
    fake_ollama = FakeOllama(
        [{"message": {"content": "La P40 puede servir para inferencia local."}}]
    )
    fake_search = FakeVideoSearch()
    service.ollama = fake_ollama
    service.online_search = fake_search
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, ORIGINAL_P40_REQUEST)

        assert fake_search.queries
        assert "p40" in fake_search.queries[0].casefold()
        assert opened == fake_search.video_urls
        assert all(url in fake_search.video_urls for url in opened)
        actions = [item["action"] for item in result["action_results"]]
        assert actions.count("web_search") == 1
        assert actions.count("open_target") == 3
        assert len(fake_ollama.requests) <= 1
    finally:
        service.close()


def test_contextual_search_and_open_reuses_user_topic_not_assistant_guessed_url(
    tmp_path, monkeypatch
):
    service = make_service(tmp_path)
    fake_ollama = FakeOllama(
        [{"message": {"content": "He usado resultados nuevos y comprobados."}}]
    )
    fake_search = FakeVideoSearch()
    service.ollama = fake_ollama
    service.online_search = fake_search
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    conversation = service.create_conversation("P40 para servidor de IA")
    service.database.add_message(
        "user",
        ORIGINAL_P40_REQUEST,
        conversation_id=conversation["id"],
    )
    invented_url = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    service.database.add_message(
        "assistant",
        f"No pude abrir las pestañas. Probé este enlace: {invented_url}",
        conversation_id=conversation["id"],
    )
    try:
        result = send_in_conversation(
            service,
            conversation["id"],
            "Buscalos y abrelos porfavor",
        )

        assert fake_search.queries
        assert "p40" in fake_search.queries[0].casefold()
        assert opened == fake_search.video_urls
        assert invented_url not in opened
        actions = [item["action"] for item in result["action_results"]]
        assert actions.count("web_search") == 1
        assert actions.count("open_target") == 3
        assert len(fake_ollama.requests) <= 1
    finally:
        service.close()


@pytest.mark.parametrize(
    "invented_url",
    [
        "https://www.youtube.com/watch?v=AAAAAAAAAAA",
        "https://old.example/dead",
    ],
)
def test_model_cannot_open_an_unverified_external_url(
    tmp_path, monkeypatch, invented_url
):
    service = make_service(tmp_path)
    service.ollama = FakeOllama(
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "open_target",
                                "arguments": {"target": invented_url},
                            }
                        }
                    ],
                }
            },
            {"message": {"content": "No abrí un enlace que no estaba verificado."}},
        ]
    )
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, "Okay")

        assert opened == []
        assert result["action_result"]["success"] is False
        assert "no fue escrito" in result["action_result"]["message"]
    finally:
        service.close()


def test_model_may_open_the_exact_youtube_url_returned_earlier_in_the_turn(
    tmp_path, monkeypatch
):
    search = FakeVideoSearch()
    verified_url = search.video_urls[0]
    service = make_service(tmp_path)
    service.online_search = search
    service.ollama = FakeOllama(
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "web_search",
                                "arguments": {
                                    "query": "NVIDIA P40 servidor IA YouTube",
                                    "language": "es",
                                },
                            }
                        },
                        {
                            "function": {
                                "name": "open_target",
                                "arguments": {"target": verified_url},
                            }
                        },
                    ],
                }
            },
            {"message": {"content": "Abrí el resultado verificado."}},
        ]
    )
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, "De acuerdo, hazlo ahora")

        assert opened == [verified_url]
        assert [item["success"] for item in result["action_results"]] == [
            True,
            True,
        ]
    finally:
        service.close()


@pytest.mark.parametrize(
    "message",
    [
        "No abras YouTube",
        "No quiero que abras YouTube",
        "Por favor, no los abras en YouTube",
        "Nunca abras YouTube",
        "¿Cuál es el mejor vídeo de YouTube para aprender Python?",
        "Dime qué es YouTube sin abrir ninguna pestaña",
    ],
)
def test_mentions_and_negated_orders_do_not_open_browser_tabs(
    tmp_path, monkeypatch, message
):
    service = make_service(tmp_path)
    fake_ollama = FakeOllama(
        [{"message": {"content": "Te respondo sin abrir el navegador."}}]
    )
    service.ollama = fake_ollama
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, message)

        assert opened == []
        assert len(fake_ollama.requests) == 1
        assert result.get("action_result") is None
    finally:
        service.close()


@pytest.mark.parametrize(
    "message",
    [
        "Busca vídeos de NVIDIA P40 en YouTube, pero no los abras",
        "Busca vídeos de NVIDIA P40 en YouTube sin abrirlos",
    ],
)
def test_search_request_with_explicit_no_open_can_search_without_opening_tabs(
    tmp_path, monkeypatch, message
):
    service = make_service(tmp_path)
    service.ollama = FakeOllama(
        [
            {"message": {"content": "Voy a comprobarlo."}},
            {"message": {"content": "He encontrado resultados sin abrir pestañas."}},
        ]
    )
    fake_search = FakeVideoSearch()
    service.online_search = fake_search
    opened: list[str] = []
    monkeypatch.setattr(service.actions, "_shell_open", opened.append)
    try:
        result = send(service, message)

        assert fake_search.queries
        assert opened == []
        assert result["action_result"]["action"] == "web_search"
        assert result["action_result"]["success"] is True
    finally:
        service.close()
