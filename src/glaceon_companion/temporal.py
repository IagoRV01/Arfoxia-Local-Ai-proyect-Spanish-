from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MADRID_TIMEZONE = "Europe/Madrid"
_WEEKDAYS_ES = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_MONTH_NUMBERS = {
    **{name: index for index, name in enumerate(_MONTHS_ES, start=1)},
    "xaneiro": 1,
    "febreiro": 2,
    "maio": 5,
    "xuno": 6,
    "xullo": 7,
    "setembro": 9,
    "outubro": 10,
    "decembro": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_TODAY_WORDS = {"hoy", "hoxe", "today"}
_YESTERDAY_WORDS = {"ayer", "onte", "yesterday"}
_TOMORROW_WORDS = {"manana", "mana", "tomorrow"}
_THIS_WEEK_PHRASES = ("esta semana", "this week")
_LAST_24_HOURS_PHRASES = (
    "ultimas 24 horas",
    "ultimos 24 horas",
    "last 24 hours",
)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def _madrid_tz() -> tzinfo:
    try:
        return ZoneInfo(MADRID_TIMEZONE)
    except ZoneInfoNotFoundError:
        # Windows does not ship the IANA database. The project depends on
        # ``tzdata``, but retaining the configured system zone keeps Arfoxia
        # usable during an incomplete upgrade instead of breaking startup.
        return datetime.now().astimezone().tzinfo or UTC


def _spanish_date(value: date) -> str:
    return (
        f"{_WEEKDAYS_ES[value.weekday()]}, {value.day} de "
        f"{_MONTHS_ES[value.month - 1]} de {value.year}"
    )


def madrid_date_from_iso(value: str) -> date | None:
    """Convert a persisted ISO timestamp into its Europe/Madrid calendar day."""

    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(_madrid_tz()).date()


@dataclass(frozen=True, slots=True)
class TemporalContext:
    """One immutable Europe/Madrid clock snapshot shared by a whole turn."""

    now: datetime
    timezone_name: str = MADRID_TIMEZONE

    @classmethod
    def current(cls, now: datetime | None = None) -> "TemporalContext":
        zone = _madrid_tz()
        if now is None:
            localized = datetime.now(zone)
        elif now.tzinfo is None:
            localized = now.replace(tzinfo=zone)
        else:
            localized = now.astimezone(zone)
        return cls(localized, MADRID_TIMEZONE)

    @property
    def today(self) -> date:
        return self.now.date()

    @property
    def yesterday(self) -> date:
        return self.today - timedelta(days=1)

    @property
    def tomorrow(self) -> date:
        return self.today + timedelta(days=1)

    @property
    def week_start(self) -> date:
        return self.today - timedelta(days=self.today.weekday())

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)

    def prompt_text(self) -> str:
        offset = self.now.strftime("%z")
        formatted_offset = (
            f"UTC{offset[:3]}:{offset[3:]}" if len(offset) == 5 else "UTC"
        )
        return (
            f"RELOJ LOCAL DE CONFIANZA ({self.timezone_name}, {formatted_offset}): "
            f"ahora={self.now.isoformat(timespec='seconds')}; "
            f"hoy={self.today.isoformat()} ({_spanish_date(self.today)}); "
            f"ayer={self.yesterday.isoformat()}; mañana={self.tomorrow.isoformat()}; "
            f"esta semana={self.week_start.isoformat()}..{self.week_end.isoformat()}. "
            "Esta fecha del PC es la fuente de verdad para expresiones relativas. "
            "Nunca deduzcas el día actual del entrenamiento, del historial ni de la memoria."
        )


@dataclass(frozen=True, slots=True)
class TemporalGrounding:
    period: str
    date_from: date
    date_to: date
    timelimit: str | None

    @property
    def as_of_date(self) -> date:
        return self.date_to

    def annotation(self) -> str:
        if self.date_from == self.date_to:
            return f"{self.period}={self.date_from.isoformat()} {MADRID_TIMEZONE}"
        return (
            f"{self.period}={self.date_from.isoformat()}.."
            f"{self.date_to.isoformat()} {MADRID_TIMEZONE}"
        )


def _timelimit_for_date(value: date, context: TemporalContext) -> str | None:
    distance = (context.today - value).days
    if distance == 0:
        return "d"
    if 0 < distance <= 7:
        return "w"
    if 0 < distance <= 31:
        return "m"
    if 0 < distance <= 366:
        return "y"
    return None


def _explicit_temporal_grounding(
    folded: str,
    context: TemporalContext,
) -> TemporalGrounding | None:
    iso_match = re.search(
        r"(?<!\d)(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)",
        folded,
    )
    if iso_match is not None:
        try:
            requested = date(*(int(part) for part in iso_match.groups()))
        except ValueError:
            requested = None
        if requested is not None:
            return TemporalGrounding(
                "fecha solicitada",
                requested,
                requested,
                _timelimit_for_date(requested, context),
            )

    numeric_match = re.search(
        r"(?<!\d)(0?[1-9]|[12]\d|3[01])[/.-]"
        r"(0?[1-9]|1[0-2])[/.-](20\d{2})(?!\d)",
        folded,
    )
    if numeric_match is not None:
        day, month, year = numeric_match.groups()
        try:
            requested = date(int(year), int(month), int(day))
        except ValueError:
            requested = None
        if requested is not None:
            return TemporalGrounding(
                "fecha solicitada",
                requested,
                requested,
                _timelimit_for_date(requested, context),
            )

    month_names = "|".join(_MONTH_NUMBERS)
    named_match = re.search(
        rf"(?<!\d)(\d{{1,2}})\s+(?:(?:de|do)\s+)?({month_names})"
        rf"\s+(?:(?:de|do)\s+)?(20\d{{2}})(?!\d)",
        folded,
    )
    if named_match is not None:
        day, month_name, year = named_match.groups()
        try:
            requested = date(int(year), _MONTH_NUMBERS[month_name], int(day))
        except ValueError:
            requested = None
        if requested is not None:
            return TemporalGrounding(
                "fecha solicitada",
                requested,
                requested,
                _timelimit_for_date(requested, context),
            )

    english_match = re.search(
        rf"\b({month_names})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b",
        folded,
    )
    if english_match is not None:
        month_name, day, year = english_match.groups()
        try:
            requested = date(int(year), _MONTH_NUMBERS[month_name], int(day))
        except ValueError:
            requested = None
        if requested is not None:
            return TemporalGrounding(
                "fecha solicitada",
                requested,
                requested,
                _timelimit_for_date(requested, context),
            )

    month_match = re.search(
        rf"\b({month_names})\s+(?:(?:de|do)\s+)?(20\d{{2}})\b",
        folded,
    )
    if month_match is not None:
        month_name, year = month_match.groups()
        start = date(int(year), _MONTH_NUMBERS[month_name], 1)
        next_month = (
            date(start.year + 1, 1, 1)
            if start.month == 12
            else date(start.year, start.month + 1, 1)
        )
        return TemporalGrounding(
            "mes solicitado",
            start,
            next_month - timedelta(days=1),
            None,
        )

    year_match = re.search(
        r"\b(?:de|del|do|en|in|from|año|ano|year)\s+(20\d{2})\b",
        folded,
    )
    if year_match is not None:
        year = int(year_match.group(1))
        return TemporalGrounding(
            "año solicitado",
            date(year, 1, 1),
            date(year, 12, 31),
            None,
        )
    return None


def resolve_temporal_grounding(
    text: str,
    context: TemporalContext,
    *,
    default_latest: bool = False,
) -> TemporalGrounding | None:
    folded = " ".join(_fold(text).split())
    words = set(re.findall(r"[a-z0-9]+", folded))
    if words & _YESTERDAY_WORDS:
        return TemporalGrounding(
            "ayer",
            context.yesterday,
            context.yesterday,
            "w",
        )
    if any(phrase in folded for phrase in _THIS_WEEK_PHRASES):
        return TemporalGrounding(
            "esta semana",
            context.week_start,
            context.week_end,
            "w",
        )
    if any(phrase in folded for phrase in _LAST_24_HOURS_PHRASES):
        return TemporalGrounding(
            "últimas 24 horas",
            context.yesterday,
            context.today,
            "d",
        )
    if words & _TODAY_WORDS:
        return TemporalGrounding("hoy", context.today, context.today, "d")
    if words & _TOMORROW_WORDS:
        return TemporalGrounding(
            "mañana",
            context.tomorrow,
            context.tomorrow,
            None,
        )
    explicit = _explicit_temporal_grounding(folded, context)
    if explicit is not None:
        return explicit
    if default_latest:
        return TemporalGrounding(
            "fecha de referencia",
            context.today,
            context.today,
            "d",
        )
    return None


def enrich_query_with_time(
    query: str,
    grounding: TemporalGrounding | None,
    *,
    max_chars: int = 240,
) -> str:
    normalized = " ".join(str(query or "").split()).strip()
    if grounding is None or not normalized:
        return normalized[:max_chars].rstrip()
    if grounding.date_from == grounding.date_to:
        suffix = f" {grounding.date_from.isoformat()}"
    else:
        suffix = (
            f" {grounding.date_from.isoformat()} a "
            f"{grounding.date_to.isoformat()}"
        )
    available = max(1, int(max_chars) - len(suffix))
    return f"{normalized[:available].rstrip()}{suffix}"[:max_chars].rstrip()
