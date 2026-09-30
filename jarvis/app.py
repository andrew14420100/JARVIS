from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.brain.cloud import CloudAIClient, CloudAIError
from jarvis.brain.lmstudio import LMStudioClient, LMStudioError
from jarvis.brain.openjarvis_adapter import OpenJarvisAdapter
from jarvis.config.settings import get_settings
from jarvis.core.state import JarvisState
from jarvis.memory import LocalMemory
from jarvis.tools.defaults import build_default_registry
from jarvis.voice import CosyVoiceProxyTTS, LocalSTT, LocalTTS, WakeWordListener
from jarvis.voice.cosyvoice_proxy import CosyVoiceProxyError
from jarvis.voice.edge_cloud import EdgeCloudTTS, EdgeTTSError
from jarvis.voice.fish_s2 import FishS2CloudTTS, FishS2Error

settings = get_settings()


def _build_brain_client():
    if settings.brain_mode.strip().lower() == "cloud":
        return CloudAIClient(
            nvidia_api_key=settings.nvidia_api_key,
            nvidia_model=settings.nvidia_model,
            zai_api_key=settings.zai_api_key,
            zai_model=settings.zai_model,
            groq_api_key=settings.groq_api_key,
            openrouter_api_key=settings.openrouter_api_key,
            groq_model=settings.groq_model,
            openrouter_model=settings.openrouter_model,
            timeout_seconds=settings.request_timeout_seconds,
            app_name=settings.cloud_app_name,
            app_url=settings.cloud_app_url,
            local_fallback_enabled=settings.lm_studio_fallback_enabled,
            local_fallback_base_url=settings.lm_studio_base_url,
        )
    return LMStudioClient(settings.lm_studio_base_url, settings.request_timeout_seconds)


client = _build_brain_client()
registry = build_default_registry()
orchestrator: JarvisOrchestrator | None = None

# The default voice path is entirely local. Cloud TTS is kept only as an
# explicitly selectable legacy mode and is never used while tts_mode is local.
voice_mode = settings.tts_mode.strip().lower()
cosyvoice_tts: CosyVoiceProxyTTS | None = None
cloud_tts: FishS2CloudTTS | None = None
edge_tts_fallback: EdgeCloudTTS | None = None

if voice_mode == "cosyvoice-local" and settings.cosyvoice_enabled:
    cosyvoice_tts = CosyVoiceProxyTTS(
        base_url=settings.cosyvoice_service_url,
        timeout_seconds=settings.request_timeout_seconds,
    )
elif voice_mode == "cloud" and settings.cloud_tts_enabled:
    if settings.cloud_tts_provider.strip().lower() == "fish-s2-pro":
        cloud_tts = FishS2CloudTTS(
            space_id=settings.fish_s2_space,
            hf_token=settings.fish_s2_hf_token,
            style_prompt=settings.fish_s2_style_prompt,
        )
    if settings.cloud_tts_fallback_enabled:
        edge_tts_fallback = EdgeCloudTTS(
            voice=settings.edge_tts_voice,
            rate=settings.edge_tts_rate,
            pitch=settings.edge_tts_pitch,
            volume=settings.edge_tts_volume,
        )

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_WEB_DIR = Path(__file__).parent / "web"
FRONTEND_BUILD_DIR = REPO_ROOT / "frontend" / "build"
FRONTEND_STATIC_DIR = FRONTEND_BUILD_DIR / "static"

app = FastAPI(title="JARVIS", version="0.10.0")
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


class SessionStartRequest(BaseModel):
    local_time: str = Field(default="", max_length=128)
    locale: str = Field(default="it-IT", max_length=32)


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


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


def _brain_status() -> dict[str, object]:
    status_method = getattr(client, "status", None)
    if callable(status_method):
        return dict(status_method())
    return {
        "mode": "local-lmstudio",
        "configured": ["lmstudio"],
        "models": [],
        "active_provider": "lmstudio",
        "active_model": "",
        "paid_fallback": False,
    }


def _voice_status() -> dict[str, object]:
    if cosyvoice_tts is not None:
        return cosyvoice_tts.status()

    primary: dict[str, object] = {"enabled": False, "provider": ""}
    if cloud_tts is not None:
        primary = {"enabled": True, **cloud_tts.status()}
    fallback = edge_tts_fallback.status() if edge_tts_fallback is not None else None
    return {**primary, "fallback": fallback}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(_frontend_index())


@app.get("/api/health")
def health() -> dict[str, object]:
    status = _brain_status()
    voice = _voice_status()
    try:
        models = client.list_models()
        status = _brain_status()
        return {
            "ok": True,
            "brain_mode": settings.brain_mode,
            "provider": status.get("active_provider") or ((status.get("configured") or [""])[0]),
            "active_model": status.get("active_model") or (models[0] if models else ""),
            "models": models,
            "paid_fallback": bool(status.get("paid_fallback", False)),
            "voice": voice,
            # Backwards-compatible key consumed by older frontend builds.
            "cloud_tts": voice,
            "tools": registry.names(),
        }
    except (CloudAIError, LMStudioError) as exc:
        return {
            "ok": False,
            "brain_mode": settings.brain_mode,
            "provider": status.get("active_provider") or "",
            "models": status.get("models") or [],
            "paid_fallback": False,
            "voice": voice,
            "cloud_tts": voice,
            "error": str(exc),
            "tools": registry.names(),
        }


@app.get("/api/state")
def runtime_state() -> dict[str, object]:
    agent = orchestrator
    pending = agent.pending_confirmation.name if agent and agent.pending_confirmation else None
    voice = _voice_status()
    return {
        "state": agent.state.value if agent else "IDLE",
        "pending_confirmation": pending,
        "voice_enabled": settings.voice_enabled,
        "presence_enabled": settings.presence_enabled,
        "voice": voice,
        "cloud_tts": voice,
        "brain": _brain_status(),
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
    legacy_tts = LocalTTS(
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
    selected_voice = _voice_status()
    return {
        "brain": _brain_status(),
        "voice_enabled": settings.voice_enabled,
        "presence_enabled": settings.presence_enabled,
        "presence_context_seconds": settings.presence_context_seconds,
        "memory_enabled": settings.memory_enabled,
        "wake_word": settings.wake_model,
        "voice": selected_voice,
        "cloud_tts": selected_voice,
        "stt": {"available": stt.available(), "dependencies": stt.dependency_status(), "model": settings.stt_model},
        "tts": selected_voice if cosyvoice_tts is not None else {
            "available": legacy_tts.available(),
            "dependencies": legacy_tts.dependency_status(),
            "voice": settings.tts_voice,
        },
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
def models() -> dict[str, object]:
    try:
        return {"models": client.list_models(), "brain": _brain_status()}
    except (CloudAIError, LMStudioError) as exc:
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


@app.post("/api/session/start", response_model=ChatResponse)
def start_session(request: SessionStartRequest) -> ChatResponse:
    try:
        agent = get_orchestrator()
        reply = agent.start_session(local_time=request.local_time, locale=request.locale)
        active_status = _brain_status()
        response = ChatResponse(
            reply=reply,
            state=agent.state.value,
            model=str(active_status.get("active_model") or agent.model),
            reasoning=agent.reasoning_status(),
        )
        agent.set_state(JarvisState.IDLE)
        return response
    except (CloudAIError, LMStudioError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        agent = get_orchestrator()
        reply = agent.process_message(request.message)
        response_state = agent.state.value
        active_status = _brain_status()
        response = ChatResponse(
            reply=reply,
            state=response_state,
            model=str(active_status.get("active_model") or agent.model),
            reasoning=agent.reasoning_status(),
        )
        agent.set_state(JarvisState.IDLE)
        return response
    except (CloudAIError, LMStudioError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/tts/stream")
def stream_tts(request: TTSRequest) -> StreamingResponse:
    if cosyvoice_tts is None:
        raise HTTPException(status_code=503, detail="CosyVoice locale non è selezionato.")

    voice = cosyvoice_tts.status()
    if not voice.get("ready"):
        raise HTTPException(
            status_code=503,
            detail="CosyVoice locale non è ancora pronto oppure manca la voce di riferimento.",
        )

    sample_rate = int(voice.get("sample_rate") or cosyvoice_tts.sample_rate)
    return StreamingResponse(
        cosyvoice_tts.stream_pcm(request.text),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-JARVIS-TTS-Provider": "cosyvoice3-local",
            "X-Sample-Rate": str(sample_rate),
            "X-Audio-Format": "pcm_s16le_mono",
        },
    )


@app.post("/api/tts")
def synthesize_tts(request: TTSRequest) -> Response:
    if cosyvoice_tts is not None:
        try:
            audio = cosyvoice_tts.synthesize(request.text)
            return Response(
                content=audio.data,
                media_type=audio.media_type,
                headers={
                    "Cache-Control": "no-store",
                    "X-JARVIS-TTS-Provider": audio.provider,
                },
            )
        except CosyVoiceProxyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Legacy cloud path is used only when JARVIS_TTS_MODE=cloud is explicitly set.
    primary_error = ""
    if cloud_tts is not None:
        try:
            audio = cloud_tts.synthesize(request.text)
            return Response(
                content=audio.data,
                media_type=audio.media_type,
                headers={
                    "Cache-Control": "no-store",
                    "X-JARVIS-TTS-Provider": audio.provider,
                },
            )
        except FishS2Error as exc:
            primary_error = str(exc)

    if edge_tts_fallback is not None:
        try:
            audio = edge_tts_fallback.synthesize(request.text)
            return Response(
                content=audio.data,
                media_type=audio.media_type,
                headers={
                    "Cache-Control": "no-store",
                    "X-JARVIS-TTS-Provider": audio.provider,
                    "X-JARVIS-TTS-Fallback": "1",
                },
            )
        except EdgeTTSError as exc:
            detail = f"TTS cloud primario: {primary_error or 'non disponibile'} | fallback: {exc}"
            raise HTTPException(status_code=503, detail=detail) from exc

    raise HTTPException(
        status_code=503,
        detail="Il motore vocale locale non è pronto. Avvia CosyVoice 3 e configura la voce di riferimento.",
    )


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
