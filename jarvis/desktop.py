from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from jarvis.app import app, get_orchestrator
from jarvis.config.settings import get_settings
from jarvis.core.events import EventBus
from jarvis.core.router import JarvisRouter
from jarvis.core.state import JarvisState
from jarvis.presence import PresenceContext
from jarvis.voice import CosyVoiceProxyTTS, LocalSTT, LocalTTS, WakeWordListener
from jarvis.voice.conversation import VoiceConversationEngine


def main() -> None:
    settings = get_settings()
    settings.voice_enabled = True
    input_device = settings.audio_input_device.strip() or None

    stt = LocalSTT(
        model_name=settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        language=settings.stt_language,
        input_device=input_device,
    )

    if settings.tts_mode.strip().lower() == "cosyvoice-local" and settings.cosyvoice_enabled:
        tts = CosyVoiceProxyTTS(
            base_url=settings.cosyvoice_service_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
        voice_name = "CosyVoice 3 · cloned local voice"
    else:
        tts = LocalTTS(
            voice=settings.tts_voice,
            speed=settings.tts_speed,
            lang_code=settings.tts_lang_code,
        )
        voice_name = f"Kokoro · {settings.tts_voice}"

    wake = WakeWordListener(
        model_name=settings.wake_model,
        threshold=settings.wake_threshold,
        chunk_size=settings.wake_chunk_size,
        context_seconds=settings.presence_context_seconds,
        input_device=input_device,
    )
    presence = PresenceContext(
        max_items=settings.presence_max_items,
        max_chars=settings.presence_max_chars,
    )

    missing: list[str] = []
    for name, service in (("STT", stt), ("Wake word", wake)):
        if not service.available():
            missing.append(f"{name}: {service.dependency_status()}")
    if missing:
        details = "\n".join(f"  - {item}" for item in missing)
        raise SystemExit("Mancano componenti del runtime locale:\n" + details)

    tts_ready = bool(tts.available())
    if not tts_ready:
        print(
            "[JARVIS] Voce non ancora pronta. Il runtime continua senza TTS; "
            "avvia CosyVoice e verifica la voce di riferimento."
        )

    try:
        print("[STT] Precarico Whisper...")
        stt_device, stt_warm_seconds = stt.warmup()
        print(f"[STT] Whisper pronto su {stt_device} · warm-up {stt_warm_seconds:.2f}s")
    except Exception as exc:
        print(f"[STT] Warm-up non riuscito: {exc}. Verra' ritentato al primo comando.")

    # Everything below the warm-up remains inside main(). The previous core
    # upgrade accidentally dedented this section, causing Python to exit with
    # code 0 immediately after Whisper loaded.
    print("[JARVIS] Inizializzo cervello e motore conversazionale...", flush=True)
    try:
        agent = get_orchestrator()
    except SystemExit as exc:
        raise RuntimeError(
            f"Il cervello ha terminato l'avvio inaspettatamente (SystemExit={exc.code!r})."
        ) from exc
    event_bus = EventBus()
    router = JarvisRouter()
    print("[JARVIS] Cervello pronto · voice engine in inizializzazione...", flush=True)

    engine = VoiceConversationEngine(
        settings=settings,
        stt=stt,
        tts=tts,
        tts_ready=tts_ready,
        wake=wake,
        agent=agent,
        presence=presence,
        router=router,
        event_bus=event_bus,
    )

    def serve_ui() -> None:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

    threading.Thread(target=serve_ui, daemon=True, name="jarvis-web").start()
    time.sleep(0.8)

    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass

    print("[JARVIS] Desktop runtime online.")
    print(f"[JARVIS] Wake word: {settings.wake_model}")
    print(f"[JARVIS] Voice: {voice_name} · {'READY' if tts_ready else 'PENDING'}")
    if settings.presence_enabled:
        print("[JARVIS] Conversation context: ON · ambient mic transcription: OFF")
    else:
        print("[JARVIS] Conversation context: OFF · ambient mic transcription: OFF")

    cognitive_label = (
        "OpenJarvis + guarded local agent"
        if settings.openjarvis_enabled
        else "guarded local agent"
    )
    print(f"[JARVIS] Hybrid cognitive engine: {cognitive_label}")
    print("[JARVIS] Voice engine: streaming turns · sentence TTS · continuous conversation")
    print("[JARVIS] UI: http://127.0.0.1:8000")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        while True:
            engine.run()
            # A normal desktop session should remain inside the wake loop. If
            # the audio loop returns unexpectedly, restart it instead of
            # silently returning to PowerShell with exit code 0.
            print("[JARVIS] Voice engine terminato; riavvio automatico...", flush=True)
            if engine.busy.is_set():
                engine.interrupt()
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        engine.interrupt()
        wake.stop()
        presence.clear()
        agent.close()
        print("[JARVIS] Desktop runtime stopped.")


if __name__ == "__main__":
    main()
