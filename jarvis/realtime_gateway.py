from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


class RealtimeChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class BistreamPushRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1600)


def _ndjson(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def build_realtime_gateway(
    core_app,
    *,
    get_agent: Callable[[], Any] | None = None,
    get_tts: Callable[[], Any] | None = None,
    brain_status: Callable[[], dict[str, object]] | None = None,
) -> FastAPI:
    """Latency-critical gateway in front of the legacy FastAPI application."""

    if get_agent is None or get_tts is None or brain_status is None:
        import jarvis.app as jarvis_app

        get_agent = get_agent or jarvis_app.get_orchestrator
        get_tts = get_tts or (lambda: jarvis_app.cosyvoice_tts)
        brain_status = brain_status or jarvis_app._brain_status

    gateway = FastAPI(title="JARVIS Realtime Gateway", version="2.0")

    @gateway.post("/api/realtime/chat")
    def realtime_chat(request: RealtimeChatRequest) -> StreamingResponse:
        agent = get_agent()

        def generate() -> Iterator[bytes]:
            started = time.monotonic()
            first_token_at: float | None = None
            emitted = False
            try:
                stream_method = getattr(agent, "process_message_stream", None)
                iterator = (
                    stream_method(request.message)
                    if callable(stream_method)
                    else iter([agent.process_message(request.message)])
                )
                for chunk in iterator:
                    text = str(chunk or "")
                    if not text:
                        continue
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                        print(f"[LATENCY] realtime_primo_token={first_token_at - started:.2f}s")
                    emitted = True
                    yield _ndjson({"type": "delta", "text": text})

                status = brain_status()
                yield _ndjson(
                    {
                        "type": "done",
                        "model": str(status.get("active_model") or getattr(agent, "model", "")),
                        "provider": str(status.get("active_provider") or ""),
                        "elapsed": round(time.monotonic() - started, 3),
                    }
                )
            except GeneratorExit:
                raise
            except Exception as exc:
                if not emitted:
                    yield _ndjson({"type": "error", "detail": str(exc)})
                else:
                    yield _ndjson({"type": "done", "partial": True, "detail": str(exc)})
            finally:
                try:
                    from jarvis.core.state import JarvisState

                    agent.set_state(JarvisState.IDLE)
                except Exception:
                    pass

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    def require_tts():
        # Never call /health in the realtime packet path. The actual bistream
        # operation is the health check; extra HTTP round-trips add audible delay.
        tts = get_tts()
        if tts is None:
            raise HTTPException(status_code=503, detail="CosyVoice locale non selezionato.")
        return tts

    @gateway.post("/api/realtime/tts/bistream/start")
    def bistream_start() -> dict[str, object]:
        tts = require_tts()
        try:
            response = httpx.post(f"{tts.base_url}/tts/bistream/start", timeout=3.0)
            response.raise_for_status()
            data = response.json()
            return {
                "session_id": str(data["session_id"]),
                "sample_rate": int(data.get("sample_rate") or tts.sample_rate),
            }
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Avvio CosyVoice bistream fallito: {exc}") from exc

    @gateway.post("/api/realtime/tts/bistream/{session_id}/push")
    def bistream_push(session_id: str, request: BistreamPushRequest) -> dict[str, bool]:
        tts = require_tts()
        clean = tts._clean_for_speech(request.text)
        if not clean:
            return {"ok": True}
        try:
            response = httpx.post(
                f"{tts.base_url}/tts/bistream/{session_id}/push",
                json={"text": clean},
                timeout=3.0,
            )
            response.raise_for_status()
            return {"ok": True}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Push CosyVoice bistream fallito: {exc}") from exc

    @gateway.post("/api/realtime/tts/bistream/{session_id}/finish")
    def bistream_finish(session_id: str) -> dict[str, bool]:
        tts = require_tts()
        try:
            response = httpx.post(
                f"{tts.base_url}/tts/bistream/{session_id}/finish",
                timeout=3.0,
            )
            response.raise_for_status()
            return {"ok": True}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Chiusura CosyVoice bistream fallita: {exc}") from exc

    @gateway.get("/api/realtime/tts/bistream/{session_id}/audio")
    def bistream_audio(session_id: str) -> StreamingResponse:
        tts = require_tts()

        def audio_bytes() -> Iterator[bytes]:
            try:
                with httpx.stream(
                    "GET",
                    f"{tts.base_url}/tts/bistream/{session_id}/audio",
                    timeout=tts.timeout_seconds,
                ) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        if chunk:
                            yield chunk
            except GeneratorExit:
                raise
            except Exception as exc:
                print(f"[JARVIS] Browser bistream audio terminato: {exc}")

        return StreamingResponse(
            audio_bytes(),
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-Audio-Format": "pcm_s16le_mono",
                "X-Sample-Rate": str(tts.sample_rate),
            },
        )

    gateway.mount("/", core_app)
    return gateway
