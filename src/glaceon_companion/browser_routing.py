from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import quote_plus, urlsplit

from .markdown_regions import protect_code, restore_code


_HTTPS_URL = re.compile(r"https://[^\s<>{}\[\]\"']+", re.IGNORECASE)
_MARKDOWN_AUTOLINK = re.compile(r"<([^<>\r\n]+)>")
_MARKDOWN_REFERENCE_DEFINITION = re.compile(
    r"(?m)^(?P<indent>[ \t]{0,3})\[(?P<id>[^\]\r\n]+)\]:"
    r"[ \t]*(?P<destination>[^\r\n]+)$"
)
_MARKDOWN_REFERENCE_LINK = re.compile(
    r"!?\[(?P<label>[^\]\r\n]+)\]"
    r"\[(?P<id>[^\]\r\n]*)\]"
)
_HTML_URL_ATTRIBUTE = re.compile(
    r"(?P<prefix>\b(?:href|src)\s*=\s*)"
    r"(?:(?P<quote>['\"])(?P<quoted>[^'\"\r\n]*)(?P=quote)|"
    r"(?P<bare>[^\s>]+))",
    re.IGNORECASE,
)
_MARKDOWN_ESCAPABLE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")
_OPEN_WORD = re.compile(
    r"\b(?:"
    r"abre(?:me|lo|los|la|las)?|abras|abrir|"
    r"pon(?:me|lo|los|la|las)?|"
    r"reproduce(?:me|lo|los|la|las)?|"
    r"busca(?:me|lo|los|la|las)?|"
    r"encuentra(?:me|lo|los|la|las)?|"
    r"open|play|find"
    r")\b",
    re.IGNORECASE,
)
_SEARCH_WORD = re.compile(
    r"\b(?:busca(?:me|lo|los|la|las)?|buscar|search|find)\b",
    re.IGNORECASE,
)
_YOUTUBE_WORD = re.compile(r"\b(?:youtube|youtu\.be)\b", re.IGNORECASE)
_VIDEO_WORD = re.compile(r"\b(?:vídeo|vídeos|video|videos)\b", re.IGNORECASE)
_PLURAL_OPEN = re.compile(
    r"\b(?:abrelos|abrelas|ponlos|ponlas|reproducelos|reproducelas|"
    r"buscalos|buscalas|encuentralos|encuentralas)\b",
    re.IGNORECASE,
)
_NEGATED_OPEN = re.compile(
    r"\b(?:"
    r"(?:no|non|never|nunca|don'?t|do\s+not)\s+"
    r"(?:(?:quiero|deseo|quieras|debes?|deber[ií]as?|puedes?)\s+"
    r"(?:que\s+)?)?"
    r"(?:(?:me|lo|los|la|las)\s+){0,2}"
    r"(?:(?:vayas?\s+a)\s+)?"
    r"(?:"
    r"abras|abrir(?:me|lo|los|la|las)?|abre(?:me|lo|los|la|las)?|"
    r"busques|buscar(?:me|lo|los|la|las)?|busca(?:me|lo|los|la|las)?|"
    r"encuentres|encontrar(?:me|lo|los|la|las)?|"
    r"open(?:ing)?|play|search|find"
    r")|"
    r"(?:sin|sen|without)\s+"
    r"(?:abrir(?:me|lo|los|la|las)?|abre(?:me|lo|los|la|las)?|open(?:ing)?)|"
    r"evita(?:me)?\s+"
    r"(?:abrir(?:me|lo|los|la|las)?|abre(?:me|lo|los|la|las)?)"
    r")\b",
    re.IGNORECASE,
)
_COMPOUND_QUESTION = re.compile(
    r"\b(?:"
    r"dime|dimelo|explica|explicame|opinas|opinion|compara|comparame|"
    r"merece|sirve|es\s+(?:una?\s+)?buena|ventajas|inconvenientes|"
    r"tell\s+me|explain|compare|is\s+it\s+good"
    r")\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "un": 1,
    "uno": 1,
    "una": 1,
    "one": 1,
    "dos": 2,
    "two": 2,
    "tres": 3,
    "three": 3,
    "cuatro": 4,
    "four": 4,
    "cinco": 5,
    "five": 5,
}
_YOUTUBE_VIDEO_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


@dataclass(frozen=True, slots=True)
class BrowserPlan:
    """A typed browser operation derived only from user-authored text."""

    kind: str
    targets: tuple[str, ...] = ()
    query: str = ""
    count: int = 1
    needs_model_followup: bool = False


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def _normalized(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def has_open_intent(text: str) -> bool:
    normalized = _normalized(text)
    if not normalized or _NEGATED_OPEN.search(_fold(normalized)):
        return False
    return _OPEN_WORD.search(_fold(normalized)) is not None


def _trim_url_punctuation(value: str) -> str:
    value = value.rstrip(".,;!¡¿")
    while value and value[-1] in ")]}":
        opening = {")": "(", "]": "[", "}": "{"}[value[-1]]
        if value.count(value[-1]) <= value.count(opening):
            break
        value = value[:-1].rstrip(".,;!¡¿")
    return value


def extract_explicit_https_urls(text: str, *, limit: int = 6) -> tuple[str, ...]:
    """Extract exact HTTPS destinations without manufacturing or rewriting them."""

    output: list[str] = []
    seen: set[str] = set()
    for match in _HTTPS_URL.finditer(str(text or "")):
        target = _trim_url_punctuation(match.group(0))
        key = target.casefold()
        if target and key not in seen:
            output.append(target)
            seen.add(key)
        if len(output) >= max(1, min(int(limit), 6)):
            break
    return tuple(output)


def https_url_key(value: str) -> str | None:
    """Canonical comparison key that ignores only a URL fragment."""

    try:
        parsed = urlsplit(str(value or "").strip())
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    authority = hostname if port in {None, 443} else f"{hostname}:{port}"
    return f"https://{authority}{parsed.path or ''}?{parsed.query}".rstrip("?")


def filter_untrusted_https_urls(
    text: str,
    trusted_urls: Iterable[str],
    *,
    replacement: str = "enlace no verificado omitido",
) -> str:
    """Filter clickable prose links without corrupting literal source code."""

    text, code = protect_code(str(text or ""))

    allowed = {
        key
        for url in trusted_urls
        if (key := https_url_key(str(url or ""))) is not None
    }

    def normalized_target(value: str) -> str:
        decoded = html.unescape(str(value or "").strip())
        return _MARKDOWN_ESCAPABLE.sub(r"\1", decoded).strip()

    def trusted_target(value: str) -> str | None:
        normalized = normalized_target(value)
        key = https_url_key(normalized)
        return normalized if key is not None and key in allowed else None

    def reference_key(value: str) -> str:
        return " ".join(normalized_target(value).casefold().split())

    blocked_references: set[str] = set()

    def reference_definition(match: re.Match[str]) -> str:
        destination, _ = _markdown_destination(match.group("destination"))
        verified = trusted_target(destination)
        if verified is None:
            blocked_references.add(reference_key(match.group("id")))
            return ""
        return f'{match.group("indent")}[{match.group("id")}]: <{verified}>'

    filtered = _MARKDOWN_REFERENCE_DEFINITION.sub(
        reference_definition,
        str(text or ""),
    )

    def reference_link(match: re.Match[str]) -> str:
        label = match.group("label")
        identifier = match.group("id") or label
        if reference_key(identifier) not in blocked_references:
            return match.group(0)
        return f"{label} ({replacement})"

    filtered = _MARKDOWN_REFERENCE_LINK.sub(reference_link, filtered)
    for identifier in sorted(blocked_references, key=len, reverse=True):
        if not identifier:
            continue
        filtered = re.sub(
            rf"(?<![!\[])\[{re.escape(identifier)}\]",
            replacement,
            filtered,
            flags=re.IGNORECASE,
        )

    filtered = _sanitize_inline_markdown_links(
        filtered,
        trusted_target=trusted_target,
        replacement=replacement,
    )

    def autolink(match: re.Match[str]) -> str:
        target = normalized_target(match.group(1))
        if https_url_key(target) is None:
            return match.group(0)
        verified = trusted_target(target)
        return f"<{verified}>" if verified is not None else replacement

    filtered = _MARKDOWN_AUTOLINK.sub(autolink, filtered)

    def html_attribute(match: re.Match[str]) -> str:
        verified = trusted_target(match.group("quoted") or match.group("bare"))
        value = html.escape(verified, quote=True) if verified is not None else ""
        return f'{match.group("prefix")}"{value}"'

    filtered = _HTML_URL_ATTRIBUTE.sub(html_attribute, filtered)

    def raw(match: re.Match[str]) -> str:
        value = match.group(0)
        if trusted_target(value) is not None:
            return value
        target = _trim_url_punctuation(value)
        suffix = value[len(target) :]
        return value if trusted_target(target) is not None else f"{replacement}{suffix}"

    return restore_code(_HTTPS_URL.sub(raw, filtered), code)


def _markdown_destination(value: str) -> tuple[str, str]:
    """Split a CommonMark destination from its optional title."""

    raw = str(value or "").strip()
    if raw.startswith("<"):
        escaped = False
        for index, character in enumerate(raw[1:], start=1):
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == ">":
                return raw[1:index], raw[index + 1 :].strip()
        return raw, ""

    escaped = False
    depth = 0
    for index, character in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "(":
            depth += 1
            continue
        if character == ")" and depth:
            depth -= 1
            continue
        if character.isspace() and depth == 0:
            return raw[:index], raw[index:].strip()
    return raw, ""


def _sanitize_inline_markdown_links(
    text: str,
    *,
    trusted_target: Callable[[str], str | None],
    replacement: str,
) -> str:
    """Rewrite inline CommonMark links, including escaped destinations."""

    output: list[str] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        label_start = text.find("[", cursor)
        if label_start < 0:
            output.append(text[cursor:])
            break
        output.append(text[cursor:label_start])
        label_end = _matching_markdown_delimiter(text, label_start, "[", "]")
        if label_end is None or label_end + 1 >= length or text[label_end + 1] != "(":
            output.append(text[label_start])
            cursor = label_start + 1
            continue
        destination_end = _matching_markdown_delimiter(
            text,
            label_end + 1,
            "(",
            ")",
        )
        if destination_end is None:
            output.append(text[label_start])
            cursor = label_start + 1
            continue
        raw_destination = text[label_end + 2 : destination_end]
        destination, _ = _markdown_destination(raw_destination)
        verified = trusted_target(destination)
        label = text[label_start + 1 : label_end]
        image_prefix = label_start > 0 and text[label_start - 1] == "!"
        if image_prefix and output and output[-1].endswith("!"):
            output[-1] = output[-1][:-1]
        if verified is None:
            output.append(f"{label} ({replacement})")
        else:
            marker = "!" if image_prefix else ""
            output.append(f"{marker}[{label}](<{verified}>)")
        cursor = destination_end + 1
    return "".join(output)


def _matching_markdown_delimiter(
    text: str,
    start: int,
    opening: str,
    closing: str,
) -> int | None:
    depth = 0
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def is_youtube_video_url(value: str) -> bool:
    """Return whether a URL points at a video route, not a YouTube page/search."""

    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return False
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme.casefold() != "https" or hostname not in _YOUTUBE_VIDEO_HOSTS:
        return False
    segments = [segment for segment in parsed.path.split("/") if segment]
    if hostname in {"youtu.be", "www.youtu.be"}:
        return bool(segments)
    return bool(segments) and segments[0].casefold() in {
        "watch",
        "shorts",
        "live",
        "v",
        "embed",
    }


def youtube_search_url(query: str) -> str:
    return (
        "https://www.youtube.com/results?search_query="
        f"{quote_plus(_normalized(query))}"
    )


def requested_open_count(text: str) -> int:
    folded = _fold(_normalized(text))
    numbered = re.search(
        r"\b([1-5]|un|uno|una|one|dos|two|tres|three|cuatro|four|cinco|five)"
        r"\s+(?:videos?|pestanas?|enlaces?|tabs?)\b",
        folded,
    )
    if numbered:
        token = numbered.group(1)
        return int(token) if token.isdigit() else _NUMBER_WORDS[token]
    if re.search(r"\b(?:todos|todas|all)\b", folded):
        return 5
    if _PLURAL_OPEN.search(folded) or re.search(
        r"\b(?:videos|pestanas|enlaces|tabs)\b", folded
    ):
        return 3
    return 1


def _strip_youtube_command(text: str) -> str:
    value = _normalized(text)
    value = re.sub(
        r"^\s*(?:arfoxia[\s,:-]*)?(?:por\s+favor[\s,:-]*)?"
        r"(?:pon(?:me)?|reproduce(?:me)?|abre(?:me)?|busca(?:me)?|"
        r"encuentra(?:me)?|open|play|find)\s+",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^(?:en\s+)?youtube\s+",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^(?:(?:un|una|el|la|los|las)\s+)?"
        r"(?:vídeo|vídeos|video|videos)"
        r"(?:\s+(?:de|sobre|acerca\s+de))?\s+",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\s+(?:en|de)\s+youtube\b.*$",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\s+(?:y|e)\s+"
        r"(?:abre(?:me|lo|los|la|las)?|pon(?:me|lo|los|la|las)?|"
        r"reproduce(?:me|lo|los|la|las)?)\b.*$",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:por\s+favor|please)\b[\s.!?]*$",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    return _normalized(value.strip(" ,:;-"))


def _search_topic(text: str) -> str:
    value = _normalized(text)
    video_clause = re.search(
        r"[,;]?\s+(?:y\s+)?si\s+hay\s+(?:alg[uú]n|algunos?)\s+"
        r"(?:vídeo|vídeos|video|videos)\b",
        value,
        flags=re.IGNORECASE,
    )
    if video_clause:
        value = value[: video_clause.start()]
    value = re.sub(
        r"^\s*arfoxia[\s,:-]*",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^\s*(?:dime|explica(?:me)?|tell\s+me)\s+(?:por\s+favor\s+)?",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^\s*(?:si|whether)\s+",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^\s*(?:busca(?:me)?\s+)?(?:en\s+la\s+web\s+)?"
        r"(?:[1-5]|un|uno|una|dos|tres|cuatro|cinco)?\s*"
        r"(?:vídeo|vídeos|video|videos)?"
        r"(?:\s+(?:de|sobre|acerca\s+de))?\s*",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\s+(?:y|e)\s+"
        r"(?:abre(?:me|lo|los|la|las)?|pon(?:me|lo|los|la|las)?|"
        r"reproduce(?:me|lo|los|la|las)?)\b.*$",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:en\s+)?(?:pestañas?|tabs?)\s+(?:de\s+)?youtube\b.*$",
        "",
        value,
        count=1,
        flags=re.IGNORECASE,
    )
    return _normalized(value.strip(" ,:;-"))[:190].rstrip()


def plan_browser_request(
    text: str,
    *,
    previous_user_messages: tuple[str, ...] = (),
) -> BrowserPlan | None:
    """Recognize high-confidence browser orders without trusting assistant history."""

    normalized = _normalized(text)
    if not has_open_intent(normalized):
        return None

    explicit_urls = extract_explicit_https_urls(normalized)
    if explicit_urls:
        return BrowserPlan(kind="targets", targets=explicit_urls, count=len(explicit_urls))

    folded = _fold(normalized)
    youtube_mentioned = _YOUTUBE_WORD.search(folded) is not None
    videos_mentioned = _VIDEO_WORD.search(folded) is not None
    plural_context = _PLURAL_OPEN.search(folded) is not None
    if not youtube_mentioned and plural_context:
        for previous in reversed(previous_user_messages):
            previous_folded = _fold(previous)
            if (
                _YOUTUBE_WORD.search(previous_folded)
                or _VIDEO_WORD.search(previous_folded)
            ):
                topic = _search_topic(previous)
                if topic:
                    return BrowserPlan(
                        kind="verified_youtube_search",
                        query=topic,
                        count=requested_open_count(normalized),
                    )
        return None

    if not youtube_mentioned and not videos_mentioned:
        return None

    compact_words = re.findall(r"[a-z0-9]+", folded)
    youtube_only = all(
        word
        in {
            "abre",
            "abreme",
            "abrir",
            "arfoxia",
            "el",
            "la",
            "me",
            "por",
            "favor",
            "please",
            "youtube",
        }
        for word in compact_words
    )
    if youtube_mentioned and youtube_only:
        return BrowserPlan(
            kind="targets",
            targets=("https://www.youtube.com/",),
        )

    count = requested_open_count(normalized)
    explicit_web_search = bool(
        _SEARCH_WORD.search(folded)
        and re.search(r"\b(?:web|internet)\b", folded)
    )
    compound = _COMPOUND_QUESTION.search(folded) is not None
    if explicit_web_search or plural_context or compound:
        query = _search_topic(normalized) or _strip_youtube_command(normalized)
        if not query:
            return None
        return BrowserPlan(
            kind="verified_youtube_search",
            query=query,
            count=count,
            needs_model_followup=compound,
        )

    query = _strip_youtube_command(normalized)
    if not query:
        return BrowserPlan(
            kind="targets",
            targets=("https://www.youtube.com/",),
        )
    return BrowserPlan(
        kind="targets",
        targets=(youtube_search_url(query),),
    )
