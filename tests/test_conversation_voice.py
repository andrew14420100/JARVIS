from __future__ import annotations

from jarvis.voice.conversation import (
    followup_wait_seconds,
    is_stop_phrase,
    normalize_spoken_text,
)


def test_normalize_spoken_text_handles_punctuation_and_case() -> None:
    assert normalize_spoken_text("  Grazie, JARVIS!  ") == "grazie jarvis"


def test_configured_stop_phrase_inside_polite_wrapper() -> None:
    assert is_stop_phrase(
        "Ok, Jarvis stop per favore.",
        "jarvis stop|vai in standby",
    )


def test_natural_stop_variants() -> None:
    samples = (
        "Basta così",
        "Puoi fermarti?",
        "Fermati un attimo",
        "Vai in standby",
        "Grazie Jarvis, basta",
    )
    for sample in samples:
        assert is_stop_phrase(sample)


def test_negated_stop_is_not_misclassified() -> None:
    samples = (
        "Non fermarti",
        "Non Jarvis stop",
        "Non andare in standby",
    )
    for sample in samples:
        assert not is_stop_phrase(sample)


def test_normal_conversation_is_not_stop() -> None:
    assert not is_stop_phrase("Mi spieghi come funziona lo standby del computer?")
    assert not is_stop_phrase("Questo non basta per risolvere il problema")


def test_followup_timeout_defaults_to_natural_window() -> None:
    assert followup_wait_seconds(10) == 10.0


def test_followup_timeout_is_clamped() -> None:
    assert followup_wait_seconds(1) == 6.0
    assert followup_wait_seconds(99) == 20.0
    assert followup_wait_seconds("non-valido") == 10.0
