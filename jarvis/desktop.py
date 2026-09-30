from __future__ import annotations

import re
import threading
import time
import webbrowser

import uvicorn

from jarvis.app import app, get_orchestrator
from jarvis.config.settings import get_settings
from jarvis.core.state import JarvisState
from jarvis.presence import PresenceContext
from jarvis.voice import CosyVoiceProxyTTS, LocalSTT, LocalTTS, WakeWordListener


def _clean_ambient_transcript(text: str) -> str:
    value = " ".join(text.strip().split())
    # The tail around activation often contains the wake phrase itself; remove
    # it from contextual prose so the primary command is not duplicated.
    value = re.sub(r"\b(?:hey\s+)?jarvis\b[,.!?;:]*", "", value, flags=re.I)
    return " ".join(value.split()).strip()


def main() -> None:
    settings = get_settings()
    # Running this entrypoint explicitly means the local voice/presence runtime
    # is active, even if cloud/web-only previews keep those features disabled.
    settings.voice_enabled = True
    settings.presence_enabled = True
    settings.openjarvis_enabled = True

    stt = LocalSTT(
        model_name=settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        language=settings.stt_language,
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
    )
    presence = PresenceContext(
        max_items=settings.presence_max_items,
        max_chars=settings.presence_max_chars,
    )

    missing: list[str] = []
    for name, service in (("STT", stt), ("TTS", tts), ("Wake word", wake)):
        if not service.available():
            missing.append(f"{name}: {service.dependency_status()}")
    if missing:
        details = "\n".join(f"  - {item}" for item in missing)
        raise SystemExit(
            "Mancano componenti del runtime locale. Se TTS indica cosyvoice_service=false, "
            "avvia prima start-cosyvoice.ps1 dopo aver configurato la voce.\n" + details
        )

    busy = threading.Event()
    agent = get_orchestrator()

    def interrupt() -> None:
        stt.abort()
        tts.stop()
        agent.set_state(JarvisState.IDLE)
        busy.clear()

    def handle_wake() -> None:
        if busy.is_set():
            interrupt()
            return
        busy.set()

        # Snapshot the conversation *before* pausing the wake microphone. The
        # snapshot is float audio held only in process memory.
        ambient_audio = None
        if settings.presence_enabled:
            try:
                ambient_audio = wake.recent_audio(settings.presence_context_seconds)
            except Exception:
                ambient_audio = None

        wake.pause()
        try:
            agent.set_state(JarvisState.LISTENING)
            if settings.tts_enabled:
                try:
                    tts.speak("Sì?", streamed=True)
                except Exception as exc:
                    print(f"[JARVIS] TTS prompt non disponibile: {exc}")

            print("[JARVIS] Ti ascolto...")
            audio = stt.record_until_silence()
            result = stt.transcribe(audio)
            text = result.text.strip()
            if not text:
                print("[JARVIS] Nessun comando rilevato.")
                agent.set_state(JarvisState.IDLE)
                return

            # Transcribe recent room context only when Jarvis was actually
            # invoked. This avoids running Whisper continuously in background.
            if settings.presence_enabled and ambient_audio is not None:
                try:
                    if getattr(ambient_audio, "size", 0) >= int(16000 * 2.0):
                        ambient_result = stt.transcribe(ambient_audio)
                        ambient_text = _clean_ambient_transcript(ambient_result.text)
                        if ambient_text:
                            presence.add(ambient_text, speaker="contesto recente")
                            print(f"[PRESENCE] {ambient_text}")
                except Exception as exc:
                    print(f"[PRESENCE] contesto non disponibile: {exc}")
                finally:
                    wake.clear_recent_audio()

            ambient_context = presence.as_context() if settings.presence_enabled else ""
            print(f"TU: {text}")
            reply = agent.process_message(text, ambient_context=ambient_context)
            presence.add(text, speaker="utente")
            if reply:
                presence.add(reply, speaker="Jarvis")

            print(f"JARVIS: {reply}")
            reasoning = agent.reasoning_status()
            if reasoning.get("used_openjarvis"):
                print(
                    "[COGNITIVE] OpenJarvis "
                    f"agent={reasoning.get('agent')} model={reasoning.get('model')} "
                    f"score={reasoning.get('score')}"
                )

            if settings.tts_enabled and reply:
                try:
                    agent.set_state(JarvisState.SPEAKING)
                    # CosyVoice streams PCM chunks as soon as they are generated,
                    # so playback begins before the full waveform exists.
                    tts.speak(reply, streamed=True)
                except Exception as exc:
                    print(f"[JARVIS] TTS non disponibile: {exc}")
        except Exception as exc:
            agent.set_state(JarvisState.ERROR)
            print(f"[JARVIS] Errore voce: {exc}")
        finally:
            wake.resume()
            if agent.state is not JarvisState.ERROR:
                agent.set_state(JarvisState.IDLE)
            busy.clear()

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
    print(f"[JARVIS] Voice: {voice_name}")
    print(f"[JARVIS] Presence context: {settings.presence_context_seconds:.0f}s (RAM only)")
    print("[JARVIS] Hybrid cognitive engine: OpenJarvis + guarded local agent")
    print("[JARVIS] UI: http://127.0.0.1:8000")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        wake.run(handle_wake, busy=busy.is_set, interrupt=interrupt)
    except KeyboardInterrupt:
        pass
    finally:
        interrupt()
        wake.stop()
        presence.clear()
        agent.close()


if __name__ == "__main__":
    main()
