from __future__ import annotations

import sys
import types

from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator
from jarvis.brain.lmstudio import LMStudioClient
from jarvis.config.settings import Settings
from jarvis.voice.cosyvoice_proxy import CosyVoiceProxyTTS as BaseCosyVoiceProxyTTS
from jarvis.voice.cosyvoice_stable import CosyVoiceProxyTTS


class EmptyRegistry:
    def schemas(self):
        return []


class CountingLocal:
    def __init__(self):
        self.calls = 0

    def resolve_best_model(self, _priority=""):
        return "qwen-local"

    def resolve_model(self, _model=""):
        return "qwen-local"

    def chat_completion(self, **_kwargs):
        self.calls += 1
        return {"role": "assistant", "content": "NO"}


class WrapperClient:
    def __init__(self):
        self._local_fallback = CountingLocal()

    def resolve_model(self, _configured=""):
        return "qwen-local"

    def close(self):
        pass


def test_simple_qwen_voice_turn_disables_thinking_without_mutating_history():
    messages = [
        {"role": "system", "content": "Sei JARVIS."},
        {"role": "user", "content": "Come stai?"},
    ]
    prepared, fast = LMStudioClient._prepare_messages_for_latency(
        "lmstudio-community/Qwen3.8-27B-GGUF",
        messages,
    )
    assert fast is True
    assert messages[-1]["content"] == "Come stai?"
    assert prepared[-1]["content"].endswith("/no_think")


def test_complex_qwen_turn_keeps_reasoning_available():
    messages = [
        {"role": "system", "content": "Sei JARVIS."},
        {"role": "user", "content": "Analizza e correggi il backend, poi fai debug completo del database."},
    ]
    prepared, fast = LMStudioClient._prepare_messages_for_latency(
        "lmstudio-community/Qwen3.8-27B-GGUF",
        messages,
    )
    assert fast is False
    assert prepared[-1]["content"] == messages[-1]["content"]
    assert "/no_think" not in prepared[-1]["content"]


def test_clear_question_after_long_pause_skips_address_classifier_llm():
    client = WrapperClient()
    agent = StableJarvisOrchestrator(
        Settings(memory_enabled=False, openjarvis_enabled=False),
        client,
        EmptyRegistry(),
    )
    assert agent.is_addressed_to_jarvis("come stai", seconds_since_reply=600.0) is True
    assert client._local_fallback.calls == 0


def test_ambiguous_long_idle_phrase_may_use_address_classifier():
    client = WrapperClient()
    agent = StableJarvisOrchestrator(
        Settings(memory_enabled=False, openjarvis_enabled=False),
        client,
        EmptyRegistry(),
    )
    assert agent.is_addressed_to_jarvis("che bella giornata", seconds_since_reply=600.0) is False
    assert client._local_fallback.calls == 1


def test_tts_first_stream_packet_is_buffered_enough_for_smooth_playback():
    text = (
        "Bene, signore. Tutto procede regolarmente e possiamo continuare da dove avevamo lasciato. "
        "Non rilevo problemi in questo momento."
    )
    packets = list(CosyVoiceProxyTTS._segments_from_live_text(iter([text])))
    assert packets
    if len(packets) > 1:
        assert len(packets[0]) >= 30
    assert "".join(packets).replace(" ", "") == text.replace(" ", "")


def test_tts_stop_never_cross_closes_active_http_response(monkeypatch):
    tts = BaseCosyVoiceProxyTTS()
    state = {"closed": False, "sd_stop": False}

    class FakeResponse:
        def close(self):
            state["closed"] = True

    def sd_stop():
        state["sd_stop"] = True

    tts._active_response = FakeResponse()
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(stop=sd_stop))
    tts.stop()
    assert tts._interrupt.is_set()
    assert state["sd_stop"] is True
    assert state["closed"] is False


def test_bistream_failure_does_not_replay_text_after_audio_already_started(monkeypatch):
    tts = CosyVoiceProxyTTS()
    spoken = []

    def partially_spoken_then_fail(_self, chunks):
        iterator = iter(chunks)
        next(iterator)
        tts._voice_audio_started = True
        raise RuntimeError("synthetic audio drop")

    monkeypatch.setattr(BaseCosyVoiceProxyTTS, "speak_text_stream", partially_spoken_then_fail)
    monkeypatch.setattr(tts, "speak", lambda text, streamed=True: spoken.append((text, streamed)))
    tts.speak_text_stream(iter(["Prima parte della risposta. ", "Seconda parte. "]))
    assert spoken == []
