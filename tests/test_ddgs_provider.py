import time

import pytest

from glaceon_companion.ddgs_provider import ResilientDDGSProvider
from glaceon_companion.online_search import OnlineSearchClient, OnlineSearchError


def test_failed_primary_recovers_using_an_independent_engine_and_keeps_query_constraints():
    calls = []
    class Engine:
        def news(self, query, **arguments):
            calls.append((query, arguments))
            if arguments["backend"] == "auto":
                raise RuntimeError("provider-private-token")
            return [{"title": "Fuente", "url": "https://example.com/2026/10/10/news", "date": "2026-10-10"}]
    provider = ResilientDDGSProvider(8, factory=lambda **kwargs: Engine())
    client = OnlineSearchClient(provider_factory=lambda: provider, validate_result_urls=False)
    payload = client.search_payload("noticias España", search_type="news", timelimit="d",
                                    date_from="2026-10-10", date_to="2026-10-10")
    assert len(payload["results"]) == 1
    assert [call[1]["backend"] for call in calls] == ["auto", "bing"]
    assert all(call[0] == "noticias España" and call[1]["timelimit"] == "d" for call in calls)
    assert payload["diagnostics"]["engine"] == "bing"
    assert "provider-private-token" not in str(payload)


def test_slow_auto_does_not_hold_up_successful_fallback():
    class Engine:
        def text(self, query, **arguments):
            if arguments["backend"] == "auto":
                time.sleep(0.4)
            return [{"title": "Fuente", "href": "https://example.com"}]
    provider = ResilientDDGSProvider(0.2, factory=lambda **kwargs: Engine())
    start = time.monotonic()
    rows = provider.text("consulta", max_results=5)
    assert time.monotonic() - start < 0.3
    assert rows
    assert provider.diagnostics["attempts"][0]["status"] == "timeout"
    assert provider.diagnostics["engine"] == "yahoo"


def test_all_failed_engines_report_failure_without_exception_secrets():
    class Engine:
        def text(self, *args, **kwargs):
            raise RuntimeError("credential-secret")
    provider = ResilientDDGSProvider(8, factory=lambda **kwargs: Engine())
    search = OnlineSearchClient(provider_factory=lambda: provider)
    with pytest.raises(OnlineSearchError) as failure:
        search.search("consulta")
    assert failure.value.diagnostics["status"] == "provider_failed"
    assert len(failure.value.diagnostics["attempts"]) == 3
    assert "credential-secret" not in str(failure.value.diagnostics)


def test_empty_primary_tries_other_engines_without_changing_query():
    calls = []
    class Engine:
        def text(self, query, **arguments):
            calls.append((query, arguments["backend"]))
            return [] if arguments["backend"] == "auto" else [{"title": "Dato", "href": "https://example.com"}]
    provider = ResilientDDGSProvider(8, factory=lambda **kwargs: Engine())
    assert provider.text("mis palabras exactas", max_results=5)
    assert calls == [("mis palabras exactas", "auto"), ("mis palabras exactas", "yahoo")]


def test_unknown_links_are_distinguished_from_an_empty_search_and_never_cited():
    from glaceon_companion.link_availability import LinkAvailability

    class Engine:
        def text(self, *args, **kwargs):
            return [{"title": "Dato", "href": "https://example.com"}]
    search = OnlineSearchClient(provider_factory=Engine, availability_checker=lambda url: LinkAvailability("unknown"))
    payload = search.search_payload("consulta")
    assert payload["results"] == []
    assert payload["diagnostics"]["status"] == "links_unverified"
    assert payload["diagnostics"]["raw_results"] == 1
    assert payload["diagnostics"]["links_unknown"] == 1


def test_news_with_wrong_date_is_not_relabeled_as_today():
    class Engine:
        def news(self, *args, **kwargs):
            return [{"title": "Dato antiguo", "url": "https://example.com", "date": "2026-10-09"}]
    search = OnlineSearchClient(provider_factory=Engine, validate_result_urls=False)
    payload = search.search_payload("noticias", search_type="news", date_from="2026-10-10", date_to="2026-10-10")
    assert payload["results"] == []
    assert payload["diagnostics"]["status"] == "date_filtered"
