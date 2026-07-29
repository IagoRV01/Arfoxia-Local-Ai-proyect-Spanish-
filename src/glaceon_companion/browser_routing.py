from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote_plus, urlsplit


_HTTPS_URL = re.compile(r"https://[^\s<>{}\[\]\"']+", re.IGNORECASE)
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


def extract_explicit_https_urls(text: str, *, limit: int = 6) -> tuple[str, ...]:
    """Extract exact HTTPS destinations without manufacturing or rewriting them."""

    output: list[str] = []
    seen: set[str] = set()
    for match in _HTTPS_URL.finditer(str(text or "")):
        target = match.group(0).rstrip(".,;!¡¿)]}")
        key = target.casefold()
        if target and key not in seen:
            output.append(target)
            seen.add(key)
        if len(output) >= max(1, min(int(limit), 6)):
            break
    return tuple(output)


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
