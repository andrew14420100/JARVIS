from __future__ import annotations

import math
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator
from jarvis.config.settings import Settings
from jarvis.core.state import JarvisState
from jarvis.voice.cosyvoice_proxy import CosyVoiceProxyTTS as BaseCosyVoiceProxyTTS
from jarvis.voice.cosyvoice_stable import CosyVoiceProxyTTS
from jarvis.voice.echo import EchoReference
from jarvis.voice.stt import LocalSTT as BaseLocalSTT, STTResult
from jarvis.voice.stt_stable import LocalSTT


class EmptyRegistry:
    def schemas(self):
        return []

    def execute(self, *_args, **_kwargs):
        raise AssertionError("No tool should execute in this test")


class FastStreamClient:
    def __init__(self):
        self.calls = 0
        self.last_provider = ""
        self.last_model = ""

    def resolve_model(self, configured_model=""):
        return configured_model or "qwen-local"

    def resolve_best_model(self, _priority=""):
        return "qwen-local"

    def can_stream_chat(self, **_kwargs):
        return True

    def chat_completion_stream(self, **_kwargs):
        self.calls += 1
        yield "Ricevuto"
        yield ", signore."

    def chat_completion(self, **_kwargs):
        return {"role": "assistant", "content": "Ricevuto, signore.", "tool_calls": []}

    def close(self):
        pass


class AlternatingFailureClient(FastStreamClient):
    def chat_completion_stream(self, **_kwargs):
        self.calls += 1
        mode = self.calls % 4
        if mode == 1:
            raise RuntimeError("provider unavailable before first token")
        if mode == 2:
            yield "Parziale"
            raise RuntimeError("provider dropped mid-stream")
        if mode == 3:
            yield "OK"
            return
        yield "Tutto"
        yield " bene"


def make_agent(client=None, **overrides):
    values = dict(
        model="qwen-local",
        memory_enabled=False,
        openjarvis_enabled=False,
        conversation_max_messages=20,
        conversation_local_first=False,
    )
    values.update(overrides)
    return StableJarvisOrchestrator(Settings(**values), client or FastStreamClient(), EmptyRegistry())


def test_ai_300_consecutive_streaming_turns_stay_bounded_and_fast():
    agent = make_agent()
    started = time.perf_counter()
    for index in range(300):
        answer = "".join(agent.process_message_stream(f"Turno conversazione numero {index}"))
        assert answer == "Ricevuto, signore."
        assert agent.state is JarvisState.SPEAKING
        assert len(agent.messages) <= 21
    elapsed = time.perf_counter() - started
    assert elapsed < 8.0, f"300 synthetic AI turns took {elapsed:.2f}s"
    assert agent.client.calls == 300


def test_ai_repeated_provider_failures_do_not_crash_or_leak_history():
    agent = make_agent(AlternatingFailureClient())
    started = time.perf_counter()
    answers = []
    for index in range(160):
        answers.append("".join(agent.process_message_stream(f"Richiesta {index}")))
        assert agent.state in {JarvisState.IDLE, JarvisState.SPEAKING}
        assert len(agent.messages) <= 21
    elapsed = time.perf_counter() - started
    assert elapsed < 8.0
    assert any(answer == "Parziale" for answer in answers)
    assert any(answer == "OK" for answer in answers)
    assert all(answer for answer in answers)


def test_ai_stream_can_be_interrupted_200_times_without_state_corruption():
    agent = make_agent()
    started = time.perf_counter()
    for index in range(200):
        stream = agent.process_message_stream(f"Interrompi questo turno {index}")
        assert next(stream) == "Ricevuto"
        stream.close()
        assert agent.state is JarvisState.IDLE
        assert len(agent.messages) <= 21
        assert agent.messages[-1]["role"] == "assistant"
        assert agent.messages[-1]["content"] == "Ricevuto"
    assert time.perf_counter() - started < 6.0


def test_ai_parallel_instances_do_not_share_conversation_state():
    def run_session(session: int):
        agent = make_agent()
        output = []
        for turn in range(60):
            output.append("".join(agent.process_message_stream(f"sessione {session} turno {turn}")))
        return len(agent.messages), output[-1], agent.client.calls

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run_session, range(8)))
    assert time.perf_counter() - started < 10.0
    assert all(size <= 21 for size, _answer, _calls in results)
    assert all(answer == "Ricevuto, signore." for _size, answer, _calls in results)
    assert all(calls == 60 for _size, _answer, calls in results)


def test_think_filter_survives_every_single_character_chunk_boundary():
    visible = "Certamente, signore. Procedo subito."
    payload = "<think>ragionamento privato molto lungo che non va pronunciato</think>" + visible
    chunks = list(payload)
    result = "".join(CosyVoiceProxyTTS._strip_think_chunks(iter(chunks)))
    assert result == visible
    assert "ragionamento" not in result
    assert "think" not in result.casefold()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("<think>segreto", ""),
        ("testo visibile</think>Risposta", "testo visibileRisposta"),
        ("<THINK attr='x'>nascosto</THINK>Ciao", "Ciao"),
        ("Ciao <think>nascosto</think> mondo", "Ciao  mondo"),
    ],
)
def test_think_filter_never_speaks_hidden_reasoning(payload, expected):
    pieces = [payload[index:index + 2] for index in range(0, len(payload), 2)]
    result = "".join(CosyVoiceProxyTTS._strip_think_chunks(iter(pieces)))
    assert result == expected


def test_tts_segmenter_handles_very_long_live_reply_without_pathological_slowdown():
    text = " ".join(
        f"Frase numero {index}, risposta naturale e continua per verificare lo streaming."
        for index in range(2500)
    )
    chunks = (text[index:index + 7] for index in range(0, len(text), 7))
    started = time.perf_counter()
    packets = list(CosyVoiceProxyTTS._segments_from_live_text(chunks))
    elapsed = time.perf_counter() - started
    joined = " ".join(packets)
    assert packets
    assert all(packet for packet in packets)
    assert "Frase numero 0" in joined
    assert "Frase numero 2499" in joined
    assert elapsed < 3.0, f"TTS segmentation took {elapsed:.2f}s"


def test_tts_bistream_failure_fallback_preserves_complete_text(monkeypatch):
    tts = CosyVoiceProxyTTS()
    captured = []

    def broken_bistream(_self, chunks):
        iterator = iter(chunks)
        assert next(iterator) == "Prima parte. "
        raise RuntimeError("bistream connection dropped")

    def capture_speak(text, streamed=True):
        captured.append((text, streamed))

    monkeypatch.setattr(BaseCosyVoiceProxyTTS, "speak_text_stream", broken_bistream)
    monkeypatch.setattr(tts, "speak", capture_speak)
    tts.speak_text_stream(iter(["Prima parte. ", "Seconda parte. ", "Terza parte."]))
    assert captured == [("Prima parte. Seconda parte. Terza parte.", True)]


def test_tts_playback_interrupt_stops_promptly_and_closes_stream(monkeypatch):
    writes = []
    state = {"closed": False}
    tts = CosyVoiceProxyTTS()

    class FakeOutput:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

        def write(self, data):
            writes.append(bytes(data))
            if len(writes) == 4:
                tts._interrupt.set()

        def stop(self):
            pass

        def close(self):
            state["closed"] = True

    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(RawOutputStream=FakeOutput))
    chunks = iter([b"\x01\x00" * 200] * 1000)
    started = time.perf_counter()
    tts._play_pcm_iterator(chunks, label="test")
    assert time.perf_counter() - started < 1.0
    assert 1 <= len(writes) <= 4
    assert state["closed"] is True


def test_echo_guard_detects_self_audio_repeatedly_with_low_cpu_cost():
    sample_rate = 16000
    duration = 0.75
    count = int(sample_rate * duration)
    x = np.arange(count, dtype=np.float32) / sample_rate
    signal = (0.25 * np.sin(2.0 * math.pi * 330.0 * x)).astype(np.float32)
    pcm = np.clip(signal * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    reference = EchoReference(max_seconds=3.0)
    reference.push_pcm16(pcm, sample_rate)

    started = time.perf_counter()
    scores = [reference.correlation(signal, sample_rate) for _ in range(120)]
    elapsed = time.perf_counter() - started
    assert min(scores) > 0.90
    assert elapsed < 4.0, f"120 echo correlations took {elapsed:.2f}s"


def test_stt_normalization_is_bounded_and_does_not_clip():
    stt = BaseLocalSTT()
    quiet = np.full(16000, 0.001, dtype=np.float32)
    normalized = stt._normalize_audio(quiet)
    assert 1.0 < stt.last_recording_gain <= 24.0
    assert float(np.max(np.abs(normalized))) <= 1.0

    loud = np.linspace(-0.8, 0.8, 16000, dtype=np.float32)
    normalized_loud = stt._normalize_audio(loud)
    assert stt.last_recording_gain == 1.0
    assert np.allclose(loud, normalized_loud)


def _install_fake_sounddevice(monkeypatch, frames, read_counter):
    class FakeRawInputStream:
        def __init__(self, **kwargs):
            self.blocksize = int(kwargs["blocksize"])
            self._frames = iter(frames)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, chunk):
            read_counter[0] += 1
            try:
                frame = next(self._frames)
            except StopIteration:
                frame = np.zeros(chunk, dtype=np.int16)
            if frame.size != chunk:
                frame = np.resize(frame, chunk).astype(np.int16)
            return frame.astype(np.int16).tobytes(), False

    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(RawInputStream=FakeRawInputStream))


def test_stt_endpointing_stops_after_natural_pause_without_seconds_of_extra_audio(monkeypatch):
    sample_rate = 16000
    chunk = int(sample_rate * 0.08)
    quiet = np.zeros(chunk, dtype=np.int16)
    speech = np.full(chunk, 1800, dtype=np.int16)
    frames = [quiet] * 4 + [speech] * 8 + [quiet] * 20
    reads = [0]
    _install_fake_sounddevice(monkeypatch, frames, reads)

    stt = LocalSTT(endpoint_silence_seconds=0.42)
    started = time.perf_counter()
    audio = stt.record_until_silence(sample_rate=sample_rate, max_seconds=10.0, initial_silence_seconds=2.0)
    elapsed = time.perf_counter() - started

    assert stt.last_recording_heard_speech is True
    assert stt.last_recording_end_reason == "silence"
    assert audio.size > 0
    assert reads[0] <= 18
    assert elapsed < 0.5


def test_stt_initial_silence_timeout_returns_empty_without_hanging(monkeypatch):
    sample_rate = 16000
    chunk = int(sample_rate * 0.08)
    reads = [0]
    _install_fake_sounddevice(monkeypatch, [np.zeros(chunk, dtype=np.int16)] * 50, reads)

    stt = LocalSTT()
    started = time.perf_counter()
    audio = stt.record_until_silence(
        sample_rate=sample_rate,
        max_seconds=10.0,
        initial_silence_seconds=0.32,
    )
    assert audio.size == 0
    assert stt.last_recording_end_reason == "initial-timeout"
    assert reads[0] <= 5
    assert time.perf_counter() - started < 0.5


def test_stt_gpu_failure_falls_back_to_cpu_once_and_returns_transcript():
    class BrokenGpu:
        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("CUDA device lost")

    class WorkingCpu:
        def transcribe(self, *_args, **_kwargs):
            segment = types.SimpleNamespace(text=" ciao signore ")
            info = types.SimpleNamespace(language="it")
            return iter([segment]), info

    class TestSTT(BaseLocalSTT):
        def __init__(self):
            super().__init__(device="cuda")
            self.loads = []
            self._model_device = "cuda"
            self._model = BrokenGpu()

        def _load_model(self, force_cpu=False):
            self.loads.append(force_cpu)
            if force_cpu:
                self._model_device = "cpu"
                self._model = WorkingCpu()
            return self._model

    stt = TestSTT()
    result = stt.transcribe(np.ones(8000, dtype=np.float32) * 0.01)
    assert result == STTResult(text="ciao signore", language="it")
    assert stt._model_device == "cpu"
    assert stt.loads == [False, True]


def test_voice_ai_synthetic_hot_paths_are_stable_across_many_repetitions():
    text = "Certamente, signore. Controllo subito e le rispondo senza ritardi."
    started = time.perf_counter()
    for _ in range(2000):
        packets = list(CosyVoiceProxyTTS._segments_from_live_text(iter([text])))
        assert packets
        assert "".join(packets).replace(" ", "") == text.replace(" ", "")
        cleaned = CosyVoiceProxyTTS._clean_for_speech("<think>x</think>" + text)
        assert cleaned == text
    elapsed = time.perf_counter() - started
    assert elapsed < 6.0, f"voice hot paths took {elapsed:.2f}s"
