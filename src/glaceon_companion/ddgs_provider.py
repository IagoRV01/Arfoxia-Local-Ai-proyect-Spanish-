"""Recover a public-index search when DDGS's automatic engine selection fails."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from itertools import islice
import time
from typing import Any, Callable


class ResilientDDGSProvider:
    def __init__(self, timeout: float, factory: Callable[..., Any] | None = None) -> None:
        if factory is None:
            from ddgs import DDGS
            factory = DDGS
        self.factory = factory
        self.timeout = timeout
        self.diagnostics: dict[str, Any] = {"provider": "ddgs", "attempts": []}

    def text(self, query: str, **kwargs):
        return self._search("text", query, ("auto", "yahoo", "yandex"), kwargs)

    def news(self, query: str, **kwargs):
        return self._search("news", query, ("auto", "bing", "yahoo"), kwargs)

    def _search(self, category: str, query: str, backends: tuple[str, ...], arguments: dict):
        attempts = []
        self.diagnostics = {"provider": "ddgs", "attempts": attempts}
        deadline = time.monotonic() + self.timeout
        # A timed-out auto search must not hold up an independent fallback.
        # Each attempt also has finite HTTP timeouts; no API/server is started.
        executor = ThreadPoolExecutor(max_workers=len(backends), thread_name_prefix="arfoxia-search-engine")
        last_error: Exception | None = None
        had_empty_response = False

        def run(backend: str, budget: float):
            client = self.factory(timeout=min(3.0, budget), verify=True)
            method = getattr(client, category)
            return list(islice(method(query, backend=backend, **arguments), 20))

        try:
            for index, backend in enumerate(backends):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                budget = min(remaining, self.timeout / 2 if index == 0 else self.timeout / 4)
                future = executor.submit(run, backend, budget)
                try:
                    rows = future.result(timeout=budget)
                except TimeoutError as exc:
                    future.cancel()
                    last_error = exc
                    attempts.append({"engine": backend, "status": "timeout"})
                except Exception as exc:
                    last_error = exc
                    attempts.append({"engine": backend, "status": "failed"})
                else:
                    attempts.append({"engine": backend, "status": "ok" if rows else "empty"})
                    if rows:
                        self.diagnostics["engine"] = backend
                        return rows
                    had_empty_response = True
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if had_empty_response:
            return []
        raise RuntimeError("Search engines did not respond") from last_error
