from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from jarvis.app import app, get_orchestrator
from jarvis.config.settings import get_settings
from jarvis.voice import LocalSTT, LocalTTS, WakeWordListener


def main() -> None:
    settings = get_settings()
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

    missing: list[str] = []
    for name, service in (("STT", stt), ("TTS", tts), ("Wake word", wake)):
        if not service.available():
            missing.append(f"{name}: {service.dependency_status()}")
    if missing:
        details = "\n".join(f"  - {item}" for item in missing)
        raise SystemExit(
            "Mancano dipendenze del runtime locale. Installa requirements-local.txt.\n" + details
        )

    busy = threading.Event()

    def interrupt() -> None:
        stt.abort()
        tts.stop()
        busy.clear()

    def handle_wake() -> None:
        if busy.is_set():
            interrupt()
            return
        busy.set()
        try:
            wake.pause()
            if settings.tts_enabled:
                try:
                    tts.speak("Sì?", streamed=False)
                except Exception as exc:
                    print(f"[JARVIS] TTS prompt non disponibile: {exc}")

            print("[JARVIS] Ti ascolto...")
            audio = stt.record_until_silence()
            result = stt.transcribe(audio)
            text = result.text.strip()
            if not text:
                print("[JARVIS] Nessun comando rilevato.")
                return

            print(f"TU: {text}")
            agent = get_orchestrator()
            reply = agent.process_message(text)
            print(f"JARVIS: {reply}")
            if settings.tts_enabled and reply:
                try:
                    tts.speak(reply, streamed=True)
                except Exception as exc:
                    print(f"[JARVIS] TTS non disponibile: {exc}")
        except Exception as exc:
            print(f"[JARVIS] Errore voce: {exc}")
        finally:
            wake.resume()
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
    print("[JARVIS] UI: http://127.0.0.1:8000")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        wake.run(handle_wake, busy=busy.is_set, interrupt=interrupt)
    except KeyboardInterrupt:
        pass
    finally:
        interrupt()
        wake.stop()


if __name__ == "__main__":
    main()
