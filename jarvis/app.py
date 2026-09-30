from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.brain.lmstudio import LMStudioClient, LMStudioError
from jarvis.config.settings import get_settings
from jarvis.memory import LocalMemory
from jarvis.tools.defaults import build_default_registry
from jarvis.voice import LocalSTT, LocalTTS, WakeWordListener

settings = get_settings()
client = LMStudioClient(settings.lm_studio_base_url, settings.request_timeout_seconds)
registry = build_default_registry()
orchestrator: JarvisOrchestrator | None = None
WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="JARVIS", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    reply: str
    state: str
    model: str


def get_orchestrator() -> JarvisOrchestrator:
    global orchestrator
    if orchestrator is None:
        orchestrator = JarvisOrchestrator(settings, client, registry)
    return orchestrator


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    try:
        models = client.list_models()
        return {"ok": True, "lm_studio": True, "models": models, "tools": registry.names()}
    except LMStudioError as exc:
        return {"ok": False, "lm_studio": False, "error": str(exc), "tools": registry.names()}


@app.get("/api/capabilities")
def capabilities() -> dict[str, object]:
    stt = LocalSTT(
        model_name=settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        language=settings.stt_language,
    )
    tts = LocalTTS(
        voice=settings.tts_voice,
        speed=settings.tts_speed,
        lang_code=settings.tts_lang_code,
    )
    wake = WakeWordListener(
        model_name=settings.wake_model,
        threshold=settings.wake_threshold,
        chunk_size=settings.wake_chunk_size,
    )
    return {
        "voice_enabled": settings.voice_enabled,
        "memory_enabled": settings.memory_enabled,
        "wake_word": settings.wake_model,
        "stt": {"available": stt.available(), "dependencies": stt.dependency_status(), "model": settings.stt_model},
        "tts": {"available": tts.available(), "dependencies": tts.dependency_status(), "voice": settings.tts_voice},
        "wake": {"available": wake.available(), "dependencies": wake.dependency_status()},
        "tools": registry.names(),
    }


@app.get("/api/models")
def models() -> dict[str, list[str]]:
    try:
        return {"models": client.list_models()}
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/memory")
def memory_list(limit: int = 20) -> dict[str, object]:
    if not settings.memory_enabled:
        return {"enabled": False, "items": []}
    memory = LocalMemory(settings.memory_db_path, settings.memory_top_k)
    items = memory.recent(max(1, min(limit, 100)))
    return {
        "enabled": True,
        "items": [
            {"id": item.id, "content": item.content, "created_at": item.created_at}
            for item in items
        ],
    }


@app.delete("/api/memory/{memory_id}")
def memory_delete(memory_id: int) -> dict[str, bool]:
    if not settings.memory_enabled:
        return {"ok": False}
    memory = LocalMemory(settings.memory_db_path, settings.memory_top_k)
    return {"ok": memory.forget(memory_id)}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        agent = get_orchestrator()
        reply = agent.process_message(request.message)
        return ChatResponse(reply=reply, state=agent.state.value, model=agent.model)
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/reset")
def reset() -> dict[str, bool]:
    if orchestrator is not None:
        orchestrator.reset_conversation()
    return {"ok": True}
