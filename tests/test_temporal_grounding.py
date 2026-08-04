from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from glaceon_companion.config import CompanionConfig
from glaceon_companion.ollama_client import build_system_prompt
from glaceon_companion.services import required_web_action
from glaceon_companion.temporal import (
    TemporalContext,
    enrich_query_with_time,
    madrid_date_from_iso,
    resolve_temporal_grounding,
)


MADRID = ZoneInfo("Europe/Madrid")
FIXED = TemporalContext.current(datetime(2026, 8, 4, 14, 30, tzinfo=MADRID))


def test_temporal_context_uses_madrid_date_dst_and_calendar_week():
    assert FIXED.now.isoformat() == "2026-08-04T14:30:00+02:00"
    assert FIXED.today.isoformat() == "2026-08-04"
    assert FIXED.yesterday.isoformat() == "2026-08-03"
    assert FIXED.tomorrow.isoformat() == "2026-08-05"
    assert FIXED.week_start.isoformat() == "2026-08-03"
    assert FIXED.week_end.isoformat() == "2026-08-09"

    winter = TemporalContext.current(
        datetime(2026, 1, 4, 12, tzinfo=MADRID)
    )
    assert winter.now.utcoffset().total_seconds() == 3600
    assert FIXED.now.utcoffset().total_seconds() == 7200


def test_utc_rollover_resolves_the_next_madrid_day():
    context = TemporalContext.current(
        datetime(2026, 8, 4, 22, 30, tzinfo=UTC)
    )

    assert context.now.isoformat() == "2026-08-05T00:30:00+02:00"
    assert context.today.isoformat() == "2026-08-05"


def test_prompt_receives_the_pc_date_as_the_source_of_truth():
    prompt = build_system_prompt(
        CompanionConfig.defaults(),
        "ánimo=sereno",
        FIXED,
    )

    assert "RELOJ LOCAL DE CONFIANZA" in prompt
    assert "Europe/Madrid" in prompt
    assert "hoy=2026-08-04" in prompt
    assert "martes, 4 de agosto de 2026" in prompt
    assert "entrenamiento" in prompt


def test_news_today_is_grounded_to_an_exact_date_and_daily_news_window():
    action = required_web_action(
        "Busca noticias de hoy sobre inteligencia artificial",
        temporal_context=FIXED,
    )

    assert action is not None
    name, arguments = action
    assert name == "web_search"
    assert arguments["search_type"] == "news"
    assert arguments["timelimit"] == "d"
    assert arguments["as_of_date"] == "2026-08-04"
    assert arguments["date_from"] == "2026-08-04"
    assert arguments["date_to"] == "2026-08-04"
    assert arguments["query"] == "inteligencia artificial 2026-08-04"
    assert arguments["timezone"] == "Europe/Madrid"


def test_yesterday_and_this_week_resolve_to_bounded_calendar_dates():
    yesterday = required_web_action(
        "Noticias de ayer sobre ciencia",
        temporal_context=FIXED,
    )
    week = required_web_action(
        "Noticias de esta semana sobre videojuegos",
        temporal_context=FIXED,
    )

    assert yesterday is not None
    assert yesterday[1]["date_from"] == "2026-08-03"
    assert yesterday[1]["date_to"] == "2026-08-03"
    assert yesterday[1]["timelimit"] == "w"
    assert week is not None
    assert week[1]["date_from"] == "2026-08-03"
    assert week[1]["date_to"] == "2026-08-09"
    assert week[1]["timelimit"] == "w"


def test_intensive_current_news_reuses_the_same_exact_date_for_every_query():
    action = required_web_action(
        "Haz una investigación intensiva sobre noticias de hoy de robótica",
        temporal_context=FIXED,
    )

    assert action is not None
    name, arguments = action
    assert name == "web_research"
    assert arguments["search_type"] == "news"
    assert arguments["timelimit"] == "d"
    assert len(arguments["queries"]) == 2
    assert all("2026-08-04" in query for query in arguments["queries"])


def test_relative_query_annotation_is_bounded_and_changes_each_day():
    grounding = resolve_temporal_grounding("noticias de hoy", FIXED)
    next_day = TemporalContext.current(
        datetime(2026, 8, 5, 9, tzinfo=MADRID)
    )
    next_grounding = resolve_temporal_grounding("noticias de hoy", next_day)

    first = enrich_query_with_time("x" * 300, grounding)
    second = enrich_query_with_time("x" * 300, next_grounding)

    assert len(first) <= 240
    assert "2026-08-04" in first
    assert "2026-08-05" in second
    assert first != second


def test_explicit_news_date_is_respected_instead_of_being_replaced_by_today():
    exact = required_web_action(
        "Busca noticias del 3 de agosto de 2026",
        temporal_context=FIXED,
    )
    historical = required_web_action(
        "Busca noticias de 2024",
        temporal_context=FIXED,
    )

    assert exact is not None
    assert exact[1]["date_from"] == exact[1]["date_to"] == "2026-08-03"
    assert exact[1]["timelimit"] == "w"
    assert "2026-08-04" not in exact[1]["query"]
    assert historical is not None
    assert historical[1]["date_from"] == "2024-01-01"
    assert historical[1]["date_to"] == "2024-12-31"
    assert "timelimit" not in historical[1]


def test_year_inside_a_product_name_does_not_become_a_historical_news_filter():
    action = required_web_action(
        "Busca noticias de hoy sobre Windows Server 2022",
        temporal_context=FIXED,
    )

    assert action is not None
    assert action[1]["date_from"] == action[1]["date_to"] == "2026-08-04"


def test_explicit_english_numeric_and_galician_dates_resolve_to_one_day():
    messages = (
        "Find news from August 3, 2026",
        "Busca noticias del 03/08/2026",
        "Busca novas do 3 de agosto do 2026",
    )

    for message in messages:
        action = required_web_action(message, temporal_context=FIXED)
        assert action is not None
        assert action[1]["date_from"] == action[1]["date_to"] == "2026-08-03"


def test_long_research_request_keeps_two_distinct_dated_queries():
    action = required_web_action(
        "Haz una investigación intensiva sobre noticias de hoy sobre "
        + "inteligencia artificial " * 20,
        temporal_context=FIXED,
    )

    assert action is not None
    queries = action[1]["queries"]
    assert len(queries) == len(set(queries)) == 2
    assert queries[1].startswith("fuentes oficiales ")
    assert all(len(query) <= 240 for query in queries)


def test_persisted_utc_timestamp_is_labelled_with_the_madrid_calendar_day():
    converted = madrid_date_from_iso("2026-08-03T22:30:00+00:00")

    assert converted is not None
    assert converted.isoformat() == "2026-08-04"


def test_explicit_negation_still_prevents_current_news_search():
    assert (
        required_web_action(
            "No busques noticias de hoy",
            temporal_context=FIXED,
        )
        is None
    )
