from __future__ import annotations

from collections import deque
from types import MethodType

from glaceon_companion.link_availability import (
    LinkAvailabilityChecker,
    _ResponseHead,
)


PUBLIC_DNS = [
    (2, 1, 6, "", ("93.184.216.34", 443)),
]


class FakeStream:
    def __init__(self, status: int, chunks=(), headers=None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._chunks = list(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_bytes(self):
        yield from self._chunks


class FakeClient:
    def __init__(self, responses: deque[FakeStream], calls: list[dict]) -> None:
        self.responses = responses
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.popleft()


def fake_client_factory(responses: list[FakeStream], calls: list[dict]):
    queue = deque(responses)

    def factory(**kwargs):
        calls.append({"client_options": kwargs})
        return FakeClient(queue, calls)

    return factory


def test_youtube_oembed_and_playability_confirm_a_public_video():
    calls: list[dict] = []
    checker = LinkAvailabilityChecker(
        client_factory=fake_client_factory(
            [
                FakeStream(200),
                FakeStream(
                    200,
                    [b'"playabilityStatus":{"status":"OK"}'],
                ),
            ],
            calls,
        )
    )

    result = checker.check("https://youtu.be/dQw4w9WgXcQ?t=43")

    assert result.available
    request = next(item for item in calls if item.get("url"))
    assert request["url"] == "https://www.youtube.com/oembed"
    assert request["params"]["url"].endswith("watch?v=dQw4w9WgXcQ")


def test_youtube_oembed_rejection_falls_back_to_watch_playability():
    calls: list[dict] = []
    page = (
        b'prefix "playabilityStatus":{"status":"OK",'
        b'"playableInEmbed":false} suffix'
    )
    checker = LinkAvailabilityChecker(
        client_factory=fake_client_factory(
            [FakeStream(401), FakeStream(200, [page])],
            calls,
        )
    )

    result = checker.check("https://www.youtube.com/watch?v=dHTvpUlWFbk")

    assert result.available
    assert any(item.get("url") == "https://www.youtube.com/watch" for item in calls)


def test_youtube_removed_private_or_unplayable_video_is_not_recommended():
    for status in ("ERROR", "UNPLAYABLE", "LOGIN_REQUIRED"):
        calls: list[dict] = []
        page = f'"playabilityStatus":{{"status":"{status}"}}'.encode()
        checker = LinkAvailabilityChecker(
            client_factory=fake_client_factory(
                [FakeStream(404), FakeStream(200, [page])],
                calls,
            )
        )

        result = checker.check("https://www.youtube.com/watch?v=AAAAAAAAAAA")

        assert result.status == "unavailable"
        assert status.casefold() in result.reason


def test_youtube_requires_standard_https_target_and_returns_canonical_url():
    calls: list[dict] = []
    checker = LinkAvailabilityChecker(
        client_factory=fake_client_factory(
            [
                FakeStream(200),
                FakeStream(
                    200,
                    [b'"playabilityStatus":{"status":"OK"}'],
                ),
            ],
            calls,
        )
    )

    result = checker.check("https://youtu.be/dQw4w9WgXcQ?t=43")

    assert result.final_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert checker.check(
        "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ"
    ).status == "unavailable"
    assert checker.check(
        "https://user@www.youtube.com/watch?v=dQw4w9WgXcQ"
    ).status == "unavailable"
    assert len([item for item in calls if item.get("url")]) == 2


def test_oembed_metadata_is_not_enough_when_watch_page_is_unplayable():
    calls: list[dict] = []
    checker = LinkAvailabilityChecker(
        client_factory=fake_client_factory(
            [
                FakeStream(200),
                FakeStream(
                    200,
                    [b'"playabilityStatus":{"status":"UNPLAYABLE"}'],
                ),
            ],
            calls,
        )
    )

    result = checker.check("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert result.status == "unavailable"
    assert result.reason == "youtube_unplayable"


def test_generic_link_follows_only_revalidated_public_https_redirects(monkeypatch):
    checker = LinkAvailabilityChecker(resolver=lambda *args, **kwargs: PUBLIC_DNS)
    responses = deque(
        [
            _ResponseHead(302, {"location": "https://cdn.example.org/final"}),
            _ResponseHead(200, {}),
            _ResponseHead(200, {}),
        ]
    )
    visited: list[tuple[str, str]] = []

    def request(self, method, url):
        visited.append((method, url))
        return responses.popleft()

    monkeypatch.setattr(
        checker,
        "_request_public_headers",
        MethodType(request, checker),
    )

    result = checker.check("https://example.com/old")

    assert result.available
    assert result.final_url == "https://cdn.example.org/final"
    assert visited == [
        ("HEAD", "https://example.com/old"),
        ("HEAD", "https://cdn.example.org/final"),
        ("GET", "https://cdn.example.org/final"),
    ]


def test_generic_404_uses_bounded_get_fallback_and_stays_unavailable(monkeypatch):
    checker = LinkAvailabilityChecker(resolver=lambda *args, **kwargs: PUBLIC_DNS)
    responses = deque([_ResponseHead(404, {}), _ResponseHead(404, {})])
    methods: list[str] = []

    def request(self, method, url):
        methods.append(method)
        return responses.popleft()

    monkeypatch.setattr(
        checker,
        "_request_public_headers",
        MethodType(request, checker),
    )

    result = checker.check("https://example.com/missing")

    assert result.status == "unavailable"
    assert methods == ["HEAD", "GET"]


def test_generic_head_success_is_confirmed_by_bounded_get(monkeypatch):
    checker = LinkAvailabilityChecker(resolver=lambda *args, **kwargs: PUBLIC_DNS)
    responses = deque([_ResponseHead(200, {}), _ResponseHead(404, {})])
    monkeypatch.setattr(
        checker,
        "_request_public_headers",
        lambda method, url: responses.popleft(),
    )

    result = checker.check("https://example.com/soft-404")

    assert result.status == "unavailable"
    assert result.reason == "http_404"


def test_absolute_probe_deadline_stops_a_slow_youtube_fallback():
    class AdvancingClock:
        value = 0.0

        def __call__(self):
            current = self.value
            self.value += 0.4
            return current

    calls: list[dict] = []
    checker = LinkAvailabilityChecker(
        timeout_seconds=1,
        clock=AdvancingClock(),
        client_factory=fake_client_factory(
            [
                FakeStream(200),
                FakeStream(
                    200,
                    [b"padding", b"more padding", b"still no status"],
                ),
            ],
            calls,
        ),
    )

    result = checker.check("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert result.status == "unknown"
    assert result.reason == "youtube_watch_failed"


def test_private_dns_and_redirects_to_local_hosts_are_blocked(monkeypatch):
    mixed_dns = [
        *PUBLIC_DNS,
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ]
    mixed = LinkAvailabilityChecker(resolver=lambda *args, **kwargs: mixed_dns)
    assert mixed.check("https://example.com").status == "unavailable"

    checker = LinkAvailabilityChecker(resolver=lambda *args, **kwargs: PUBLIC_DNS)
    monkeypatch.setattr(
        checker,
        "_request_public_headers",
        lambda method, url: _ResponseHead(
            302,
            {"location": "https://127.0.0.1/private"},
        ),
    )
    assert checker.check("https://example.com").status == "unavailable"


def test_availability_cache_avoids_repeating_a_recent_probe(monkeypatch):
    checker = LinkAvailabilityChecker(resolver=lambda *args, **kwargs: PUBLIC_DNS)
    calls = 0

    def request(method, url):
        nonlocal calls
        calls += 1
        return _ResponseHead(200, {})

    monkeypatch.setattr(checker, "_request_public_headers", request)

    first = checker.check("https://example.com/article")
    second = checker.check("https://example.com/article")

    assert first == second
    assert calls == 2
