from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx


_YOUTUBE_STANDARD_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_YOUTUBE_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_PLAYABILITY = re.compile(
    rb'"playabilityStatus"\s*:\s*\{\s*"status"\s*:\s*"([A-Z_]+)"'
)
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_DEFINITELY_UNAVAILABLE = {410, 451}


@dataclass(frozen=True, slots=True)
class LinkAvailability:
    """Bounded result of a live availability probe."""

    status: str
    final_url: str | None = None
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.status == "available"


class LinkAvailabilityChecker:
    """Verify public HTTPS destinations without downloading files or media.

    YouTube video pages are soft-200 even when a video does not exist, so they
    use oEmbed plus a bounded read of official playability metadata. Other
    links use manually validated HEAD and header-only range GET requests.
    """

    MAX_REDIRECTS = 4
    MAX_CACHE_ITEMS = 256
    POSITIVE_TTL_SECONDS = 300.0
    NEGATIVE_TTL_SECONDS = 60.0
    MAX_YOUTUBE_PAGE_BYTES = 1_600_000

    def __init__(
        self,
        *,
        timeout_seconds: float = 4.0,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        client_factory: Callable[..., Any] = httpx.Client,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 10.0))
        self._resolver = resolver
        self._client_factory = client_factory
        self._clock = clock
        self._cache: OrderedDict[str, tuple[float, LinkAvailability]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._probe_local = threading.local()

    def check(self, url: str) -> LinkAvailability:
        target = str(url or "").strip()
        cached = self._cached(target)
        if cached is not None:
            return cached
        previous_deadline = getattr(self._probe_local, "deadline", None)
        self._probe_local.deadline = self._clock() + self.timeout_seconds
        try:
            video_id = self.youtube_video_id(target)
            if video_id is not None:
                canonical = f"https://www.youtube.com/watch?v={video_id}"
                result = self._check_youtube(canonical, video_id)
            else:
                result = self._check_https(target)
        finally:
            if previous_deadline is None:
                try:
                    del self._probe_local.deadline
                except AttributeError:
                    pass
            else:
                self._probe_local.deadline = previous_deadline
        self._remember(target, result)
        return result

    def _check_youtube(self, target: str, video_id: str) -> LinkAvailability:
        try:
            timeout = httpx.Timeout(self._remaining_seconds())
            with self._client_factory(
                timeout=timeout,
                follow_redirects=False,
                headers=self._headers(),
                trust_env=False,
            ) as client:
                with client.stream(
                    "GET",
                    "https://www.youtube.com/oembed",
                    params={"url": target, "format": "json"},
                ) as response:
                    status = int(response.status_code)
        except (httpx.HTTPError, OSError, ValueError):
            return LinkAvailability("unknown", reason="youtube_probe_failed")
        if status in {200, 400, 401, 403, 404}:
            # oEmbed can reject a real video when embedding is disabled. The
            # canonical watch page exposes whether it is actually playable in
            # the PC's current region, even when metadata exists.
            return self._check_youtube_watch(target=target, video_id=video_id)
        return LinkAvailability("unknown", reason=f"youtube_status_{status}")

    def _check_youtube_watch(
        self,
        *,
        target: str,
        video_id: str,
    ) -> LinkAvailability:
        try:
            timeout = httpx.Timeout(self._remaining_seconds())
            with self._client_factory(
                timeout=timeout,
                follow_redirects=False,
                headers=self._headers(),
                trust_env=False,
            ) as watch_client:
                with watch_client.stream(
                    "GET",
                    "https://www.youtube.com/watch",
                    params={
                        "v": video_id,
                        "hl": "es",
                        "gl": "ES",
                        "has_verified": "1",
                        "bpctr": "9999999999",
                    },
                ) as response:
                    if int(response.status_code) != 200:
                        return LinkAvailability(
                            "unknown",
                            reason=f"youtube_watch_{response.status_code}",
                        )
                    collected = bytearray()
                    playability_match: re.Match[bytes] | None = None
                    for chunk in response.iter_bytes():
                        self._remaining_seconds()
                        remaining = self.MAX_YOUTUBE_PAGE_BYTES - len(collected)
                        if remaining <= 0:
                            break
                        collected.extend(chunk[:remaining])
                        playability_match = _YOUTUBE_PLAYABILITY.search(collected)
                        if playability_match is not None:
                            break
                        if len(collected) >= self.MAX_YOUTUBE_PAGE_BYTES:
                            break
        except (httpx.HTTPError, OSError, ValueError):
            return LinkAvailability("unknown", reason="youtube_watch_failed")
        if playability_match is None:
            return LinkAvailability("unknown", reason="youtube_status_missing")
        playability = playability_match.group(1).decode("ascii")
        if playability == "OK":
            return LinkAvailability("available", final_url=target)
        if playability in {
            "ERROR",
            "UNPLAYABLE",
            "LOGIN_REQUIRED",
            "AGE_CHECK_REQUIRED",
            "CONTENT_CHECK_REQUIRED",
        }:
            return LinkAvailability(
                "unavailable",
                reason=f"youtube_{playability.casefold()}",
            )
        return LinkAvailability(
            "unknown",
            reason=f"youtube_{playability.casefold()}",
        )

    def _check_https(self, target: str) -> LinkAvailability:
        current = self._validated_public_https(target)
        if current is None:
            return LinkAvailability("unavailable", reason="unsafe_or_invalid_url")
        try:
            for _ in range(self.MAX_REDIRECTS + 1):
                response = self._request_public_headers("HEAD", current)
                status = int(response.status_code)
                location = response.headers.get("location")
                if status in _REDIRECT_CODES:
                    redirected = self._validated_public_https(
                        urljoin(current, str(location or ""))
                    )
                    if redirected is None:
                        return LinkAvailability(
                            "unavailable",
                            reason="unsafe_redirect",
                        )
                    current = redirected
                    continue
                if status in _DEFINITELY_UNAVAILABLE:
                    return LinkAvailability(
                        "unavailable",
                        reason=f"http_{status}",
                    )

                response = self._request_public_headers("GET", current)
                status = int(response.status_code)
                location = response.headers.get("location")
                if status in _REDIRECT_CODES:
                    redirected = self._validated_public_https(
                        urljoin(current, str(location or ""))
                    )
                    if redirected is None:
                        return LinkAvailability(
                            "unavailable",
                            reason="unsafe_redirect",
                        )
                    current = redirected
                    continue
                if 200 <= status < 300:
                    return LinkAvailability("available", final_url=current)
                if status in {404, 410, 451}:
                    return LinkAvailability(
                        "unavailable",
                        reason=f"http_{status}",
                    )
                return LinkAvailability("unknown", reason=f"http_{status}")
        except (httpx.HTTPError, OSError, ValueError):
            return LinkAvailability("unknown", reason="request_failed")
        return LinkAvailability("unknown", reason="too_many_redirects")

    def _request_public_headers(self, method: str, url: str) -> Any:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        self._remaining_seconds()
        addresses = self._public_addresses(hostname, 443)
        if not addresses:
            raise OSError("No public address")
        encoded_path = quote(
            parsed.path or "/",
            safe="/%:@!$&'()*+,;=-._~",
        )
        encoded_query = quote(
            parsed.query,
            safe="=&%:@!$'()*+,;/?-._~",
        )
        request_target = (
            f"{encoded_path}?{encoded_query}" if encoded_query else encoded_path
        )
        host_header = (
            f"[{hostname}]"
            if ":" in hostname
            else hostname.encode("idna").decode("ascii")
        )
        request_lines = [
            f"{method} {request_target} HTTP/1.1",
            f"Host: {host_header}",
            f"User-Agent: {self._headers()['User-Agent']}",
            "Accept: text/html,application/xhtml+xml,*/*;q=0.1",
            "Accept-Encoding: identity",
            "Connection: close",
        ]
        if method == "GET":
            request_lines.append("Range: bytes=0-0")
        request_bytes = ("\r\n".join(request_lines) + "\r\n\r\n").encode(
            "ascii"
        )
        context = ssl.create_default_context()
        last_error: OSError | None = None
        for address in addresses[:4]:
            raw_socket = None
            tls_socket = None
            stream = None
            try:
                raw_socket = socket.create_connection(
                    (address, 443),
                    timeout=self._remaining_seconds(),
                )
                raw_socket.settimeout(self._remaining_seconds())
                tls_socket = context.wrap_socket(
                    raw_socket,
                    server_hostname=hostname,
                )
                tls_socket.settimeout(self._remaining_seconds())
                tls_socket.sendall(request_bytes)
                stream = tls_socket.makefile("rb")
                tls_socket.settimeout(self._remaining_seconds())
                status_line = stream.readline(8_193)
                if len(status_line) > 8_192:
                    raise OSError("Oversized status line")
                parts = status_line.decode("iso-8859-1").strip().split(" ", 2)
                if len(parts) < 2 or not parts[1].isdigit():
                    raise OSError("Invalid HTTP status")
                headers: dict[str, str] = {}
                total = len(status_line)
                for _ in range(100):
                    tls_socket.settimeout(self._remaining_seconds())
                    line = stream.readline(8_193)
                    total += len(line)
                    if total > 65_536 or len(line) > 8_192:
                        raise OSError("Oversized HTTP headers")
                    if line in {b"\r\n", b"\n", b""}:
                        break
                    name, separator, value = line.decode("iso-8859-1").partition(":")
                    if separator:
                        headers[name.strip().casefold()] = value.strip()
                return _ResponseHead(int(parts[1]), headers)
            except (OSError, ssl.SSLError) as exc:
                last_error = OSError(str(exc))
            finally:
                if stream is not None:
                    stream.close()
                if tls_socket is not None:
                    tls_socket.close()
                elif raw_socket is not None:
                    raw_socket.close()
        raise last_error or OSError("Connection failed")

    def _validated_public_https(self, value: str) -> str | None:
        raw = str(value or "").strip()
        if not raw or len(raw) > 1_024 or any(char.isspace() for char in raw):
            return None
        try:
            parsed = urlsplit(raw)
            hostname = (parsed.hostname or "").casefold().rstrip(".")
            port = parsed.port or 443
        except ValueError:
            return None
        if (
            parsed.scheme.casefold() != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or port != 443
            or hostname == "localhost"
            or hostname.endswith((".localhost", ".local"))
        ):
            return None
        if not self._public_addresses(hostname, port):
            return None
        return parsed.geturl()

    def _public_addresses(self, hostname: str, port: int) -> list[str]:
        self._remaining_seconds()
        try:
            literal_address = ipaddress.ip_address(hostname)
        except ValueError:
            literal_address = None
        if literal_address is not None:
            return [str(literal_address)] if literal_address.is_global else []
        try:
            addresses = {
                str(item[4][0]).split("%", 1)[0]
                for item in self._resolver(
                    hostname,
                    port,
                    type=socket.SOCK_STREAM,
                )
            }
        except (OSError, TypeError, ValueError):
            return []
        if not addresses:
            return []
        try:
            if any(not ipaddress.ip_address(address).is_global for address in addresses):
                return []
        except ValueError:
            return []
        return sorted(addresses)

    @staticmethod
    def youtube_video_id(value: str) -> str | None:
        try:
            parsed = urlsplit(str(value or ""))
            port = parsed.port
        except ValueError:
            return None
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        if (
            parsed.scheme.casefold() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
        ):
            return None
        segments = [segment for segment in parsed.path.split("/") if segment]
        candidate = ""
        if hostname in _YOUTUBE_SHORT_HOSTS and len(segments) == 1:
            candidate = segments[0]
        elif hostname in _YOUTUBE_STANDARD_HOSTS and segments:
            route = segments[0].casefold()
            if route == "watch":
                values = parse_qs(parsed.query).get("v", [])
                candidate = values[0] if len(values) == 1 else ""
            elif route in {"shorts", "live", "v", "embed"} and len(segments) == 2:
                candidate = segments[1]
        return candidate if _YOUTUBE_VIDEO_ID.fullmatch(candidate) else None

    def _remaining_seconds(self) -> float:
        deadline = getattr(self._probe_local, "deadline", None)
        if deadline is None:
            return self.timeout_seconds
        remaining = float(deadline) - self._clock()
        if remaining <= 0:
            raise TimeoutError("Link availability deadline exceeded")
        return max(0.01, remaining)

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (compatible; ArfoxiaLinkCheck/1.0)",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
        }

    def _cached(self, key: str) -> LinkAvailability | None:
        now = self._clock()
        with self._cache_lock:
            item = self._cache.get(key)
            if item is None:
                return None
            stored_at, result = item
            ttl = (
                self.POSITIVE_TTL_SECONDS
                if result.available
                else self.NEGATIVE_TTL_SECONDS
            )
            if now - stored_at > ttl:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return result

    def _remember(self, key: str, result: LinkAvailability) -> None:
        with self._cache_lock:
            self._cache[key] = (self._clock(), result)
            self._cache.move_to_end(key)
            while len(self._cache) > self.MAX_CACHE_ITEMS:
                self._cache.popitem(last=False)


@dataclass(frozen=True, slots=True)
class _ResponseHead:
    status_code: int
    headers: dict[str, str]
