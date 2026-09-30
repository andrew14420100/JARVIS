from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.brain.lmstudio import LMStudioClient, LMStudioError
from jarvis.brain.openjarvis_adapter import OpenJarvisAdapter
from jarvis.config.settings import get_settings
from jarvis.core.state import JarvisState
from jarvis.memory import LocalMemory
from jarvis.tools.defaults import build_default_registry
from jarvis.voice import LocalSTT, LocalTTS, WakeWordListener

settings = get_settings()
client = LMStudioClient(settings.lm_studio_base_url, settings.request_timeout_seconds)
registry = build_default_registry()
orchestrator: JarvisOrchestrator | None = None
REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_WEB_DIR = Path(__file__).parent / "web"
FRONTEND_BUILD_DIR = REPO_ROOT / "frontend" / "build"
FRONTEND_STATIC_DIR = FRONTEND_BUILD_DIR / "static"

app = FastAPI(title="JARVIS", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND_STATIC_DIR), name="frontend-static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    reply: str
    state: str
    model: str
    reasoning: dict[str, Any] | None = None


def get_orchestrator() -> JarvisOrchestrator:
    global orchestrator
    if orchestrator is None:
        orchestrator = JarvisOrchestrator(settings, client, registry)
    return orchestrator


def _frontend_index() -> Path:
    built = FRONTEND_BUILD_DIR / "index.html"
    if built.is_file():
        return built
    return LEGACY_WEB_DIR / "index.html"


@app.get("/")
def home() -> FileResponse:
    return FileResponse(_frontend_index())


@app.get("/api/health")
def health() -> dict[str, object]:
    try:
        models = client.list_models()
        return {"ok": True, "lm_studio": True, "models": models, "tools": registry.names()}
    except LMStudioError as exc:
        return {"ok": False, "lm_studio": False, "error": str(exc), "tools": registry.names()}


@app.get("/api/state")
def runtime_state() -> dict[str, object]:
    agent = orchestrator
    pending = agent.pending_confirmation.name if agent and agent.pending_confirmation else None
    return {
        "state": agent.state.value if agent else "IDLE",
        "pending_confirmation": pending,
        "voice_enabled": settings.voice_enabled,
        "presence_enabled": settings.presence_enabled,
        "reasoning": agent.reasoning_status() if agent else None,
    }


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
        context_seconds=settings.presence_context_seconds,
    )
    openjarvis = OpenJarvisAdapter(
        enabled=settings.openjarvis_enabled,
        agent=settings.openjarvis_agent,
        model=settings.openjarvis_model or settings.model,
    )
    return {
        "voice_enabled": settings.voice_enabled,
        "presence_enabled": settings.presence_enabled,
        "presence_context_seconds": settings.presence_context_seconds,
        "memory_enabled": settings.memory_enabled,
        "wake_word": settings.wake_model,
        "stt": {"available": stt.available(), "dependencies": stt.dependency_status(), "model": settings.stt_model},
        "tts": {"available": tts.available(), "dependencies": tts.dependency_status(), "voice": settings.tts_voice},
        "wake": {"available": wake.available(), "dependencies": wake.dependency_status()},
        "openjarvis": {
            "enabled": settings.openjarvis_enabled,
            "available": openjarvis.available(),
            "agent": settings.openjarvis_agent,
            "error": openjarvis.error,
        },
        "tools": registry.names(),
    }


@app.get("/api/reasoning")
def reasoning_status() -> dict[str, Any]:
    if orchestrator is None:
        return {
            "used_openjarvis": False,
            "score": 0,
            "reasons": [],
            "openjarvis": {
                "enabled": settings.openjarvis_enabled,
                "available": False,
                "agent": settings.openjarvis_agent,
            },
        }
    return orchestrator.reasoning_status()


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
        response_state = agent.state.value
        response = ChatResponse(
            reply=reply,
            state=response_state,
            model=agent.model,
            reasoning=agent.reasoning_status(),
        )
        # Typed chat has no backend TTS lifecycle, so return the visual state to
        # the browser and then leave the shared runtime ready for voice wake-up.
        agent.set_state(JarvisState.IDLE)
        return response
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/reset")
def reset() -> dict[str, bool]:
    if orchestrator is not None:
        orchestrator.reset_conversation()
    return {"ok": True}


@app.get("/{path:path}", include_in_schema=False)
def react_spa(path: str) -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    if FRONTEND_BUILD_DIR.is_dir():
        candidate = (FRONTEND_BUILD_DIR / path).resolve()
        try:
            candidate.relative_to(FRONTEND_BUILD_DIR.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        if candidate.is_file():
            return FileResponse(candidate)
        index = FRONTEND_BUILD_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)

    legacy = LEGACY_WEB_DIR / "index.html"
    if legacy.is_file():
        return FileResponse(legacy)
    raise HTTPException(status_code=404, detail="Frontend not built")
