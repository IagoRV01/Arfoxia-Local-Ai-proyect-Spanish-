"""Resolve short web follow-ups from this conversation's user messages only."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence


def _fold(value: str) -> str:
    return " ".join("".join(character for character in unicodedata.normalize("NFD", value.casefold())
                            if unicodedata.category(character) != "Mn").split()).strip(" .!?¿¡,")


def _retry(value: str) -> bool:
    text = _fold(value)
    if len(text) > 140 or re.search(r"\b(?:no|non|nunca|never|dont)\s+(?:vuelvas|busques|busca|search|retry)", text):
        return False
    return bool(re.fullmatch(
        r"(?:arfoxia[, ]+)?(?:por favor[, ]+)?(?:"
        r"(?:vuelve|volvelo|volve) a (?:intentarlo|intentala|intentar|intetar|buscar)(?: buscar|lo| de nuevo| otra vez)?|"
        r"(?:busca|buscalo|intentalo|reintenta)(?: otra vez| de nuevo| nuevamente| mejor)|"
        r"(?:try|search|look) again|retry|"
        r"(?:los |esos |estos )?(?:enlaces|links)(?: no (?:funcionan|sirven|abren)| son (?:invalidos|incorrectos))"
        r")(?:[, ]+por favor)?", text))


def _weather_details(text: str) -> bool:
    folded = _fold(text)
    return len(folded) <= 140 and not re.search(r"\b(?:no|non|never|dont)\b", folded) and bool(re.search(
        r"\b(?:maximas?|minimas?|por horas|hora a hora|y manana|and tomorrow)\b", folded))


def _links_only(text: str) -> bool:
    return bool(re.fullmatch(r"(?:dame|pasame|muestrame|enviame) (?:los |las )?(?:enlaces|links|fuentes)", _fold(text)))


def resolve_web_followup(text: str, previous: Sequence[str], is_web_request: Callable[[str], bool]) -> str:
    retry = _retry(text)
    details = _weather_details(text)
    links = _links_only(text)
    if not (retry or details or links):
        return text
    refinements = [text] if details else []
    for earlier in reversed(previous[-6:]):
        if _retry(earlier) or _links_only(earlier):
            continue
        if _weather_details(earlier) and not is_web_request(earlier):
            refinements.insert(0, earlier)
            continue
        # Never jump over a different topic to an unrelated or cross-chat memory.
        if not is_web_request(earlier):
            break
        if refinements and not re.search(r"\b(?:tiempo|tempo|weather|temperatura)\b", _fold(earlier)):
            break
        return ". ".join([earlier, *refinements])
    # Searching the literal phrase 'try again' produces unrelated dictionary
    # pages. Leave it to the conversation to clarify when no topic is known.
    return "" if retry else text


def compact_search_query(text: str) -> str:
    value = re.sub(r"^\s*(?:hola|buenas|hello|hey)[, ]+(?:arfoxia[, ]*)?", "", text, flags=re.I)
    value = re.sub(r"^\s*arfoxia[, ]+", "", value, flags=re.I)
    value = re.sub(r"^\s*(?:por favor[, ]+)?(?:busca(?:me)?|buscar|buscame|búscame|consulta|search(?: for)?|find)\s+(?:(?:en (?:internet|la web)|online|on the web)\s+)?", "", value, flags=re.I)
    value = re.sub(r"[, ]+(?:por favor|please)[.! ]*$", "", value, flags=re.I)
    value = re.sub(r"\bpor favor\b[, ]*[.?!]?", "", value, flags=re.I)
    # Keep short weather refinements, not the question's conversational filler.
    value = re.sub(r"[¿?]*\bcu[aá]nt[oa]s?\s+(?:van a ser|ser[aá]n|son)\s+(?:las?\s+)?(?=m[aá]xim|m[ií]nim)", "", value, flags=re.I)
    return " ".join(value.split()).strip() or text
