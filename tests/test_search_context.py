import pytest

from glaceon_companion.search_context import compact_search_query, resolve_web_followup
from glaceon_companion.services import required_web_action


TOPIC = "Hola Arfoxia, busca el tiempo para mañana en Ourense por favor"


def resolve(text, history):
    return resolve_web_followup(text, history, lambda message: required_web_action(message) is not None)


@pytest.mark.parametrize("text", [
    "Vuelve a intetar buscar", "Vuelve a intentarlo", "Busca otra vez",
    "Los enlaces no funcionan", "Dame los enlaces", "Try again",
])
def test_retry_keeps_actual_topic(text):
    assert resolve(text, [TOPIC]) == TOPIC


def test_retry_keeps_weather_refinement_through_multiple_retries():
    detail = "¿Cuánto van a ser las máximas y mínimas?"
    assert resolve("Vuelve a intentarlo", [TOPIC, detail, "Vuelve a intetar buscar"]) == f"{TOPIC}. {detail}"
    assert resolve(detail, [TOPIC]) == f"{TOPIC}. {detail}"


def test_retry_never_jumps_over_unrelated_topic_or_invents_a_topic():
    assert resolve("Vuelve a intentarlo", []) == ""
    assert resolve("Vuelve a intentarlo", [TOPIC, "Escribe un poema"]) == ""


@pytest.mark.parametrize("text", ["No vuelvas a buscar", "No busques las máximas", "Explícame la RAM"])
def test_no_forced_search_for_negation_or_unrelated_question(text):
    assert resolve(text, [TOPIC]) == text


def test_query_removes_conversational_wrapper_not_search_subject():
    assert compact_search_query(TOPIC) == "el tiempo para mañana en Ourense"
