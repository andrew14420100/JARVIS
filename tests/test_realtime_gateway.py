from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis.realtime_gateway import build_realtime_gateway


class FakeAgent:
    model = "fast-local"

    def __init__(self) -> None:
        self.states = []

    def process_message_stream(self, text: str):
        assert text == "come stai"
        yield "Molto "
        yield "bene, "
        yield "signore."

    def set_state(self, state) -> None:
        self.states.append(state)


def test_realtime_chat_streams_deltas_before_done():
    core = FastAPI()

    @core.get("/healthz")
    def healthz():
        return {"ok": True}

    agent = FakeAgent()
    gateway = build_realtime_gateway(
        core,
        get_agent=lambda: agent,
        get_tts=lambda: None,
        brain_status=lambda: {"active_model": "fast-local", "active_provider": "local"},
    )
    client = TestClient(gateway)

    response = client.post("/api/realtime/chat", json={"message": "come stai"})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]

    assert [event["type"] for event in events] == ["delta", "delta", "delta", "done"]
    assert "".join(event.get("text", "") for event in events) == "Molto bene, signore."
    assert events[-1]["model"] == "fast-local"
    assert events[-1]["provider"] == "local"


def test_gateway_keeps_core_app_available_behind_hot_path():
    core = FastAPI()

    @core.get("/healthz")
    def healthz():
        return {"ok": True}

    gateway = build_realtime_gateway(
        core,
        get_agent=lambda: FakeAgent(),
        get_tts=lambda: None,
        brain_status=lambda: {},
    )
    client = TestClient(gateway)

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
