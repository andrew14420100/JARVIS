from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.brain.lmstudio import LMStudioClient, LMStudioError
from jarvis.config.settings import get_settings
from jarvis.tools.defaults import build_default_registry

settings = get_settings()
client = LMStudioClient(settings.lm_studio_base_url, settings.request_timeout_seconds)
registry = build_default_registry()
orchestrator: JarvisOrchestrator | None = None
WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="JARVIS", version="0.1.0")


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


@app.get("/api/models")
def models() -> dict[str, list[str]]:
    try:
        return {"models": client.list_models()}
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
