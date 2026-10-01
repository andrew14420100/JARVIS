from jarvis.brain.lmstudio import LMStudioClient


def _messages(user_text: str):
    return [
        {
            "role": "system",
            "content": "SYSTEM PROMPT MOLTO LUNGO " * 300,
        },
        {"role": "user", "content": "Ciao Jarvis"},
        {"role": "assistant", "content": "Buonasera, signore."},
        {"role": "user", "content": user_text},
    ]


def test_simple_voice_turn_uses_compact_prompt_and_qwen_no_think():
    original = _messages("Come stai?")
    prepared, fast = LMStudioClient._prepare_messages_for_latency(
        "Qwen3.8-27B", original
    )

    assert fast is True
    assert len(prepared) <= 4
    assert "SYSTEM PROMPT MOLTO LUNGO" not in prepared[0]["content"]
    assert prepared[-1]["role"] == "user"
    assert prepared[-1]["content"].endswith("/no_think")
    # Permanent transcript must not be modified.
    assert "/no_think" not in original[-1]["content"]


def test_memory_sensitive_turn_keeps_full_context():
    original = _messages("Ricordi cosa ti ho detto ieri?")
    prepared, fast = LMStudioClient._prepare_messages_for_latency(
        "Qwen3.8-27B", original
    )

    assert fast is False
    assert prepared is original
    assert "SYSTEM PROMPT MOLTO LUNGO" in prepared[0]["content"]


def test_technical_turn_keeps_full_context():
    original = _messages("Analizza il backend e correggi il codice")
    prepared, fast = LMStudioClient._prepare_messages_for_latency(
        "Qwen3.8-27B", original
    )

    assert fast is False
    assert prepared is original


def test_non_qwen_fast_turn_still_compacts_without_control_token():
    original = _messages("Che fai?")
    prepared, fast = LMStudioClient._prepare_messages_for_latency(
        "glm-4.7-flash", original
    )

    assert fast is True
    assert "SYSTEM PROMPT MOLTO LUNGO" not in prepared[0]["content"]
    assert "/no_think" not in prepared[-1]["content"]
