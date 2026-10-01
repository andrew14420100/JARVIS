from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import jarvis.app as app_module
from jarvis.core.state import JarvisState


class FakeBrain:
    last_provider = "fake-core"
    last_model = "fake-model"

    def list_models(self):
        return ["fake-model"]

    def status(self):
        return {
            "mode": "test",
            "configured": ["fake-core"],
            "models": ["fake-model"],
            "active_provider": self.last_provider,
            "active_model": self.last_model,
            "paid_fallback": False,
        }


class FakeAgent:
    def __init__(self):
        self.state = JarvisState.IDLE
        self.pending_confirmation = None
        self.model = "fake-model"
        self.reset_called = False

    def start_session(self, *, local_time: str = "", locale: str = "it-IT") -> str:
        self.state = JarvisState.SPEAKING
        return f"Sì, signore. {locale} {bool(local_time)}"

    def process_message(self, text: str, *, ambient_context: str = "") -> str:
        self.state = JarvisState.SPEAKING
        return f"Risposta: {text}"

    def reasoning_status(self):
        return {"used_openjarvis": False, "score": 0, "reasons": [], "agent": "", "model": "fake-model"}

    def set_state(self, state):
        self.state = state

    def reset_conversation(self):
        self.reset_called = True
        self.state = JarvisState.IDLE


class FakeCosyVoice:
    sample_rate = 24000

    def status(self):
        return {
            "enabled": True,
            "ready": True,
            "provider": "cosyvoice3-local",
            "sample_rate": self.sample_rate,
            "reference_voice_configured": True,
        }

    def stream_pcm(self, text: str):
        assert text.strip()
        yield b"\x00\x00\x01\x00"

    def synthesize(self, text: str):
        assert text.strip()
        return SimpleNamespace(
            data=b"RIFFfake-wave",
            media_type="audio/wav",
            provider="cosyvoice3-local",
        )


def install_fakes(monkeypatch, tmp_path):
    agent = FakeAgent()
    monkeypatch.setattr(app_module, "client", FakeBrain())
    monkeypatch.setattr(app_module, "orchestrator", agent)
    monkeypatch.setattr(app_module, "cosyvoice_tts", FakeCosyVoice())
    monkeypatch.setattr(app_module.settings, "memory_db_path", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setattr(app_module.settings, "memory_enabled", True)
    return agent


def test_health_state_capabilities_and_models(monkeypatch, tmp_path):
    install_fakes(monkeypatch, tmp_path)
    client = TestClient(app_module.app)

    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["active_model"] == "fake-model"
    assert payload["voice"]["provider"] == "cosyvoice3-local"
    assert payload["paid_fallback"] is False
    assert payload["tools"]

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["state"] == "IDLE"

    models = client.get("/api/models")
    assert models.status_code == 200
    assert models.json()["models"] == ["fake-model"]

    capabilities = client.get("/api/capabilities")
    assert capabilities.status_code == 200
    cap = capabilities.json()
    assert cap["voice"]["provider"] == "cosyvoice3-local"
    assert "stt" in cap and "wake" in cap and "tools" in cap


def test_chat_session_reset_and_memory_routes(monkeypatch, tmp_path):
    agent = install_fakes(monkeypatch, tmp_path)
    client = TestClient(app_module.app)

    session = client.post("/api/session/start", json={"local_time": "2026-10-01 14:00", "locale": "it-IT"})
    assert session.status_code == 200
    assert session.json()["reply"].startswith("Sì, signore.")

    chat = client.post("/api/chat", json={"message": "spiegami un integrale"})
    assert chat.status_code == 200
    assert chat.json()["reply"] == "Risposta: spiegami un integrale"
    assert chat.json()["state"] == "SPEAKING"
    assert agent.state == JarvisState.IDLE

    memory = client.get("/api/memory")
    assert memory.status_code == 200
    assert memory.json()["enabled"] is True

    reset = client.post("/api/reset")
    assert reset.status_code == 200
    assert reset.json() == {"ok": True}
    assert agent.reset_called is True


def test_cloned_voice_buffered_and_streaming_routes(monkeypatch, tmp_path):
    install_fakes(monkeypatch, tmp_path)
    client = TestClient(app_module.app)

    buffered = client.post("/api/tts", json={"text": "Sì, signore."})
    assert buffered.status_code == 200
    assert buffered.content == b"RIFFfake-wave"
    assert buffered.headers["X-JARVIS-TTS-Provider"] == "cosyvoice3-local"

    streamed = client.post("/api/tts/stream", json={"text": "Prova streaming."})
    assert streamed.status_code == 200
    assert streamed.content == b"\x00\x00\x01\x00"
    assert streamed.headers["X-Audio-Format"] == "pcm_s16le_mono"
    assert streamed.headers["X-Sample-Rate"] == "24000"


def test_api_validation_and_unknown_routes(monkeypatch, tmp_path):
    install_fakes(monkeypatch, tmp_path)
    client = TestClient(app_module.app)

    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/tts", json={"text": ""}).status_code == 422
    assert client.get("/api/does-not-exist").status_code == 404
