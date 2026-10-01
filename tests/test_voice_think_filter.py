from __future__ import annotations

from jarvis.voice.cosyvoice_stable import CosyVoiceProxyTTS


def collect(*chunks: str) -> str:
    return " ".join(CosyVoiceProxyTTS._segments_from_live_text(iter(chunks))).strip()


def test_complete_think_block_is_not_spoken() -> None:
    result = collect("<think>ragionamento segreto</think>Risposta visibile.")
    assert result == "Risposta visibile."


def test_split_think_tags_are_not_spoken() -> None:
    result = collect(
        "<thi",
        "nk>questo non deve essere pronunciato",
        "</thi",
        "nk>Buongiorno, signore.",
    )
    assert result == "Buongiorno, signore."


def test_orphan_closing_tag_discards_hidden_prefix() -> None:
    result = collect(
        "ragionamento iniziato prima dello stream",
        "</think>Risposta finale.",
    )
    assert result == "Risposta finale."


def test_unfinished_think_tail_is_discarded() -> None:
    result = collect("Risposta visibile. <think>ragionamento che non finisce")
    assert result == "Risposta visibile."


def test_non_stream_cleanup_removes_reasoning_body() -> None:
    result = CosyVoiceProxyTTS._clean_for_speech(
        "<think>think think think</think>Testo da leggere."
    )
    assert result == "Testo da leggere."
