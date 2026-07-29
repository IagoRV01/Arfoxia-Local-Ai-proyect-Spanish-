from __future__ import annotations

import threading
import time

import pytest

from glaceon_companion.online_search import (
    OnlineSearchClient,
    OnlineSearchError,
    SearchResult,
    UNTRUSTED_WEB_NOTICE,
)


class FakeProvider:
    def __init__(self, rows=(), error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.calls: list[dict] = []

    def text(self, query: str, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if self.error:
            raise self.error
        return iter(self.rows)


def client(provider: FakeProvider) -> OnlineSearchClient:
    return OnlineSearchClient(provider_factory=lambda: provider)


def test_search_is_bounded_safe_and_sanitized():
    provider = FakeProvider(
        [
            {
                "title": " <b>Resultado</b>\x00 fiable ",
                "href": "https://example.com/article?q=hielo#comments",
                "body": "Texto <em>útil</em>\n para Arfoxia.",
            },
            {
                "title": "Duplicado",
                "href": "https://example.com/article?q=hielo#otro",
                "body": "No debe repetirse.",
            },
            {"title": "Sin TLS", "href": "http://example.org", "body": "No"},
            {"title": "Local", "href": "https://127.0.0.1/private", "body": "No"},
            {"title": "Con credenciales", "href": "https://a:b@example.net", "body": "No"},
            {
                "title": "Segunda fuente",
                "url": "https://example.org/news",
                "snippet": "Otra fuente segura.",
            },
        ]
    )

    results = client(provider).search("noticias de Glaceon", max_results=999)

    assert provider.calls == [
        {
            "query": "noticias de Glaceon",
            "region": "es-es",
            "safesearch": "moderate",
            "max_results": 5,
        }
    ]
    assert results == [
        SearchResult(
            title="Resultado fiable",
            url="https://example.com/article?q=hielo",
            snippet="Texto útil para Arfoxia.",
        ),
        SearchResult(
            title="Segunda fuente",
            url="https://example.org/news",
            snippet="Otra fuente segura.",
        ),
    ]


def test_query_and_language_are_normalized_and_limited():
    provider = FakeProvider()
    query = "  novidades\n" + "x" * 400

    client(provider).search(query, language="gl", max_results=0)

    call = provider.calls[0]
    assert call["query"].startswith("novidades x")
    assert len(call["query"]) == OnlineSearchClient.MAX_QUERY_CHARS
    assert call["region"] == "es-es"
    assert call["safesearch"] == "moderate"
    assert call["max_results"] == 1


def test_english_uses_english_region():
    provider = FakeProvider()

    client(provider).search("latest weather", language="en")

    assert provider.calls[0]["region"] == "us-en"


@pytest.mark.parametrize("query", ["", " \n\t\x00 "])
def test_empty_query_is_rejected(query):
    provider = FakeProvider()

    with pytest.raises(ValueError, match="vacía"):
        client(provider).search(query)

    assert provider.calls == []


def test_provider_details_are_not_exposed_in_error_message():
    provider = FakeProvider(error=RuntimeError("secret-provider-token"))

    with pytest.raises(OnlineSearchError) as raised:
        client(provider).search("consulta")

    assert "secret-provider-token" not in str(raised.value)
    assert "no está disponible" in str(raised.value)


def test_tool_payload_marks_results_as_untrusted():
    provider = FakeProvider(
        [{"title": "Fuente", "href": "https://example.com", "body": "Dato"}]
    )

    payload = client(provider).search_payload("  dato actual  ")

    assert payload == {
        "query": "dato actual",
        "security_notice": UNTRUSTED_WEB_NOTICE,
        "results": [
            {"title": "Fuente", "url": "https://example.com", "snippet": "Dato"}
        ],
    }


class ResearchProvider:
    def __init__(
        self,
        rows_by_query: dict[str, list[dict]],
        *,
        failing_queries: set[str] | None = None,
    ) -> None:
        self.rows_by_query = rows_by_query
        self.failing_queries = failing_queries or set()
        self.calls: list[str] = []

    def text(self, query: str, **kwargs):
        self.calls.append(query)
        if query in self.failing_queries:
            raise RuntimeError("provider secret")
        return iter(self.rows_by_query.get(query, []))


def test_research_payload_merges_safely_with_domain_and_url_limits():
    provider = ResearchProvider(
        {
            "primera perspectiva": [
                {
                    "title": "Uno",
                    "href": "https://example.com/a#fragmento",
                    "body": "A",
                },
                {
                    "title": "Dos",
                    "href": "https://www.example.com/b",
                    "body": "B",
                },
                {
                    "title": "Tres",
                    "href": "https://example.com/c",
                    "body": "No cabe por el limite del dominio.",
                },
            ],
            "segunda perspectiva": [
                {
                    "title": "Duplicado",
                    "href": "https://example.com/a#otro",
                    "body": "No debe repetirse.",
                },
                {
                    "title": "Otra fuente",
                    "href": "https://example.org/d",
                    "body": "D",
                },
            ],
        }
    )

    payload = client(provider).research_payload(
        [" primera\n perspectiva ", "segunda perspectiva"]
    )

    assert payload == {
        "queries": ["primera perspectiva", "segunda perspectiva"],
        "security_notice": UNTRUSTED_WEB_NOTICE,
        "results": [
            {"title": "Uno", "url": "https://example.com/a", "snippet": "A"},
            {"title": "Dos", "url": "https://www.example.com/b", "snippet": "B"},
            {
                "title": "Otra fuente",
                "url": "https://example.org/d",
                "snippet": "D",
            },
        ],
        "partial": False,
        "failed_queries": [],
    }


def test_research_returns_partial_results_without_provider_details():
    provider = ResearchProvider(
        {
            "consulta correcta": [
                {
                    "title": "Fuente",
                    "href": "https://example.org/result",
                    "body": "Dato",
                }
            ]
        },
        failing_queries={"consulta fallida"},
    )

    payload = client(provider).research_payload(
        ["consulta fallida", "consulta correcta"]
    )

    assert payload["partial"] is True
    assert payload["failed_queries"] == ["consulta fallida"]
    assert payload["results"] == [
        {
            "title": "Fuente",
            "url": "https://example.org/result",
            "snippet": "Dato",
        }
    ]
    assert "provider secret" not in str(payload)


@pytest.mark.parametrize(
    "queries",
    [
        ["solo una"],
        ["a", "b", "c", "d", "e"],
        ["repetida", " REPETIDA "],
        "esto no es una lista",
    ],
)
def test_research_requires_two_to_four_distinct_queries(queries):
    provider = ResearchProvider({})

    with pytest.raises(ValueError):
        client(provider).research_payload(queries)

    assert provider.calls == []


def test_research_uses_at_most_two_concurrent_searches():
    state_lock = threading.Lock()
    state = {"active": 0, "maximum": 0}

    class ConcurrentProvider:
        def text(self, query: str, **kwargs):
            with state_lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            try:
                time.sleep(0.02)
                return iter(
                    [
                        {
                            "title": query,
                            "href": f"https://{query}.example.com/result",
                            "body": "Dato",
                        }
                    ]
                )
            finally:
                with state_lock:
                    state["active"] -= 1

    search = OnlineSearchClient(provider_factory=ConcurrentProvider)

    payload = search.research_payload(["uno", "dos", "tres", "cuatro"])

    assert state["maximum"] == 2
    assert len(payload["results"]) == 4


def test_research_aggregate_result_text_is_bounded():
    rows_by_query = {
        query: [
            {
                "title": "T" * OnlineSearchClient.MAX_TITLE_CHARS,
                "href": f"https://domain-{query}-{index}.example/result/"
                + "u" * 800,
                "body": "S" * OnlineSearchClient.MAX_SNIPPET_CHARS,
            }
            for index in range(5)
        ]
        for query in ("uno", "dos", "tres", "cuatro")
    }
    provider = ResearchProvider(rows_by_query)

    payload = client(provider).research_payload(["uno", "dos", "tres", "cuatro"])

    result_chars = sum(
        len(result["title"]) + len(result["url"]) + len(result["snippet"])
        for result in payload["results"]
    )
    assert len(payload["results"]) <= OnlineSearchClient.MAX_RESEARCH_RESULTS
    assert result_chars <= OnlineSearchClient.MAX_RESEARCH_CHARS
