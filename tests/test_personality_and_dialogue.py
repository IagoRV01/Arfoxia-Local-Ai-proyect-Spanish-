import unicodedata

from glaceon_companion.config import CompanionConfig
from glaceon_companion.ollama_client import build_system_prompt
from glaceon_companion.ui import CRY_PROFILES, is_short_dialogue


def _fold(text: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(character)
    )


def test_system_prompt_defines_arfoxias_male_trilingual_personality():
    prompt = build_system_prompt(
        CompanionConfig.defaults(),
        "ánimo=feliz, hambre=18/100",
    )
    folded = _fold(prompt)

    assert "arfoxia" in folded
    assert "glaceon" in folded
    assert "macho" in folded or "masculin" in folded
    assert "espanol" in folded
    assert "ingles" in folded
    assert "gallego" in folded or "galego" in folded
    assert "animo=feliz" in folded
    assert "breve" in folded
    assert "chatbot" in folded
    assert "glace" in folded


def test_system_prompt_recognizes_the_user_as_gori():
    prompt = build_system_prompt(CompanionConfig.defaults(), "ánimo=sereno")
    folded = _fold(prompt)

    assert "companero pokemon de gori" in folded
    assert "gori es tu humano y entrenador" in folded
    assert "iago" not in folded


def test_system_prompt_uses_the_configured_owner_name():
    config = CompanionConfig.defaults()
    config.owner_name = "Brais"

    folded = _fold(build_system_prompt(config, "ánimo=sereno"))

    assert "companero pokemon de brais" in folded
    assert "brais es tu humano" in folded


def test_each_interaction_has_a_distinct_nonempty_cry_profile():
    expected = {"feed", "pet", "play", "sleep", "wake", "chat"}

    assert expected <= CRY_PROFILES.keys()
    profiles = [CRY_PROFILES[kind] for kind in sorted(expected)]
    assert all(profile for profile in profiles)
    assert len({repr(profile) for profile in profiles}) >= 3


def test_short_dialogue_accepts_a_brief_single_line_reply():
    assert is_short_dialogue("¡Glace! Aquí estoy.", max_chars=24)


def test_short_dialogue_rejects_multiline_or_over_limit_text():
    assert not is_short_dialogue("Primera línea\nSegunda línea", max_chars=180)
    assert not is_short_dialogue("x" * 181, max_chars=180)
    assert is_short_dialogue("x" * 180, max_chars=180)
    assert not is_short_dialogue("   ", max_chars=180)
