from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from local_voice.cosyvoice_server import _pcm_bytes, build_app


class FakeTensor:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class FakeCosyVoice:
    sample_rate = 24000

    def __init__(self):
        self.calls = []

    def inference_zero_shot(self, text, *args, **kwargs):
        if isinstance(text, str):
            rendered = text
        else:
            rendered = " ".join(str(item) for item in text)
        self.calls.append((rendered, kwargs))
        if rendered.strip():
            yield {"tts_speech": FakeTensor([-1.0, -0.25, 0.0, 0.25, 1.0])}


def make_client():
    engine = FakeCosyVoice()
    app = build_app(engine, "speaker-test", "CosyVoice-test", "cpu", "fp32")
    return engine, TestClient(app)


def test_pcm_bytes_is_int16_and_rejects_nonfinite_values():
    pcm = _pcm_bytes(FakeTensor([-1.0, 0.0, 1.0]))
    assert len(pcm) == 6
    values = np.frombuffer(pcm, dtype=np.int16)
    assert values.tolist() == [-32767, 0, 32767]

    try:
        _pcm_bytes(FakeTensor([0.0, np.nan]))
    except RuntimeError as exc:
        assert "non finiti" in str(exc)
    else:
        raise AssertionError("NaN audio must be rejected")


def test_health_and_standard_tts_stream_contract():
    engine, client = make_client()

    health = client.get("/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["provider"] == "cosyvoice3-local"
    assert payload["sample_rate"] == 24000
    assert payload["bistream"] is True

    response = client.post("/tts", json={"text": "  Buongiorno   signore.  ", "speed": 1.05})
    assert response.status_code == 200
    assert response.headers["X-Audio-Format"] == "pcm_s16le_mono"
    assert response.headers["X-Sample-Rate"] == "24000"
    assert response.headers["X-JARVIS-TTS-Provider"] == "cosyvoice3-local"
    assert len(response.content) == 10
    assert engine.calls[-1][0] == "Buongiorno signore."
    assert engine.calls[-1][1]["stream"] is True


def test_bistream_start_push_finish_audio_and_cleanup():
    engine, client = make_client()

    started = client.post("/tts/bistream/start")
    assert started.status_code == 200
    session_id = started.json()["session_id"]
    assert client.get("/health").json()["active_bistream_sessions"] == 1

    first = client.post(f"/tts/bistream/{session_id}/push", json={"text": "Prima frase."})
    second = client.post(f"/tts/bistream/{session_id}/push", json={"text": "Seconda frase."})
    assert first.status_code == 200 and second.status_code == 200

    finished = client.post(f"/tts/bistream/{session_id}/finish")
    assert finished.status_code == 200

    audio = client.get(f"/tts/bistream/{session_id}/audio")
    assert audio.status_code == 200
    assert audio.headers["X-JARVIS-TTS-Provider"] == "cosyvoice3-local-bistream"
    assert len(audio.content) == 10
    assert engine.calls[-1][0] == "Prima frase. Seconda frase."

    assert client.get("/health").json()["active_bistream_sessions"] == 0
    assert client.get(f"/tts/bistream/{session_id}/audio").status_code == 404


def test_bistream_unknown_session_and_request_validation():
    _, client = make_client()

    assert client.post("/tts", json={"text": ""}).status_code == 422
    assert client.post("/tts", json={"text": "ok", "speed": 3.0}).status_code == 422
    assert client.post("/tts/bistream/missing/push", json={"text": "ciao"}).status_code == 404
    assert client.post("/tts/bistream/missing/finish").status_code == 404
    assert client.get("/tts/bistream/missing/audio").status_code == 404
