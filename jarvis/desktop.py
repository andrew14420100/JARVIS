from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from jarvis.app import app, get_orchestrator
from jarvis.config.settings import get_settings
from jarvis.core.state import JarvisState
from jarvis.presence import PresenceContext
from jarvis.voice import CosyVoiceProxyTTS, LocalSTT, LocalTTS, WakeWordListener


def _post_wake_speech_profile(audio, *, sample_rate: int = 16000) -> tuple[bool, float, float, float]:
    """Decide whether real speech continued after the wake word.

    The decision is based only on audio captured *after* openWakeWord fired.
    A dynamic floor derived from the local noise level replaces the old fixed
    threshold that could mistake a 0.0007 room-noise tail for speech.
    """
    import numpy as np

    array = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not array.size:
        return False, 0.0, 0.0, 0.0012

    frame = max(320, int(sample_rate * 0.06))
    frame_rms: list[float] = []
    for start in range(0, array.size, frame):
        chunk = array[start : start + frame]
        if chunk.size < frame // 2:
            continue
        frame_rms.append(float(np.sqrt(np.mean(np.square(chunk)))))

    if not frame_rms:
        return False, 0.0, 0.0, 0.0012

    peak = max(frame_rms)
    noise = float(np.percentile(np.asarray(frame_rms, dtype=np.float32), 30))
    threshold = max(0.0012, noise * 2.5)
    voiced_frames = sum(1 for value in frame_rms if value >= threshold)
    heard_speech = voiced_frames >= 2 and peak >= threshold
    return heard_speech, peak, noise, threshold


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
            "aggiungi il campione e avvia start-cosyvoice.ps1 quando disponibile."
        )

    try:
        print("[STT] Precarico Whisper...")
        stt_device, stt_warm_seconds = stt.warmup()
        print(f"[STT] Whisper pronto su {stt_device} · warm-up {stt_warm_seconds:.2f}s")
    except Exception as exc:
        print(f"[STT] Warm-up non riuscito: {exc}. Verra' ritentato al primo comando.")

    busy = threading.Event()
    agent = get_orchestrator()

    def interrupt() -> None:
        stt.abort()
        if tts_ready:
            tts.stop()
        agent.set_state(JarvisState.IDLE)
        busy.clear()

    def capture_turn(
        *,
        initial_silence_seconds: float,
        max_seconds: float,
        activation_audio=None,
        activation_has_speech: bool = False,
    ) -> str:
        import numpy as np

        agent.set_state(JarvisState.LISTENING)
        capture_started = time.monotonic()
        audio = stt.record_until_silence(
            initial_silence_seconds=initial_silence_seconds,
            max_seconds=max_seconds,
        )
        capture_seconds = time.monotonic() - capture_started

        # If neither the live STT stream nor the post-wake buffer contains real
        # speech, do not invoke Whisper at all. Decoding silence is what allowed
        # hallucinated phrases to reach the brain in earlier builds.
        if not stt.last_recording_heard_speech and not activation_has_speech:
            print(
                f"[STT] max_rms={stt.last_recording_max_rms:.4f} "
                f"soglia_voce={stt.last_recording_speech_threshold:.4f} "
                f"speech=no gain=1.0x · capture={capture_seconds:.2f}s · "
                "decode=saltata (nessuna voce)"
            )
            return ""

        pieces = []
        if activation_audio is not None and getattr(activation_audio, "size", 0):
            pieces.append(activation_audio.astype(np.float32, copy=False))
        if getattr(audio, "size", 0):
            pieces.append(audio.astype(np.float32, copy=False))
        if not pieces:
            print(
                f"[STT] max_rms={stt.last_recording_max_rms:.4f} "
                f"soglia_voce={stt.last_recording_speech_threshold:.4f} "
                f"speech=no gain=1.0x · capture={capture_seconds:.2f}s · "
                "decode=saltata (audio vuoto)"
            )
            return ""

        combined = pieces[0] if len(pieces) == 1 else np.concatenate(pieces)
        stt_started = time.monotonic()
        result = stt.transcribe(combined)
        stt_seconds = time.monotonic() - stt_started
        text = result.text.strip()
        speech_label = "si" if stt.last_recording_heard_speech else "post-wake"

        print(
            f"[STT] max_rms={stt.last_recording_max_rms:.4f} "
            f"soglia_voce={stt.last_recording_speech_threshold:.4f} "
            f"speech={speech_label} gain={stt.last_recording_gain:.1f}x · "
            f"capture={capture_seconds:.2f}s · decode={stt_seconds:.2f}s"
        )
        return text

    def answer_turn(text: str, ambient_context: str = "") -> str:
        print(f"TU: {text}")
        brain_started = time.monotonic()
        reply = agent.process_message(text, ambient_context=ambient_context)
        brain_seconds = time.monotonic() - brain_started
        presence.add(text, speaker="utente")
        if reply:
            presence.add(reply, speaker="Jarvis")
        print(f"JARVIS: {reply}")
        print(f"[LATENCY] cervello={brain_seconds:.2f}s")

        reasoning = agent.reasoning_status()
        if reasoning.get("used_openjarvis"):
            print(
                "[COGNITIVE] OpenJarvis "
                f"agent={reasoning.get('agent')} model={reasoning.get('model')} "
                f"score={reasoning.get('score')}"
            )

        if settings.tts_enabled and tts_ready and reply:
            try:
                agent.set_state(JarvisState.SPEAKING)
                tts_started = time.monotonic()
                tts.speak(reply, streamed=True)
                print(f"[LATENCY] voce_totale={time.monotonic() - tts_started:.2f}s")
            except Exception as exc:
                print(f"[JARVIS] TTS non disponibile: {exc}")
        return reply

    def handle_wake() -> None:
        if busy.is_set():
            interrupt()
            return
        busy.set()

        # openWakeWord owns the microphone a little longer after the trigger.
        # It records only the chunks AFTER the activating chunk into a dedicated
        # post-wake buffer. Whisper will never receive the wake phrase itself.
        time.sleep(0.62)

        post_wake_audio = None
        try:
            post_wake_audio = wake.post_wake_audio(seconds=0.75, exclude_head_seconds=0.18)
        except Exception:
            post_wake_audio = None

        continued, post_peak, post_noise, post_threshold = _post_wake_speech_profile(post_wake_audio)

        if wake.selected_device is not None:
            stt.input_device = wake.selected_device

        wake.pause()
        try:
            print("[JARVIS] Ti ascolto...")
            if continued:
                print(
                    "[JARVIS] Comando dopo wake rilevato · "
                    f"peak={post_peak:.4f} noise={post_noise:.4f} soglia={post_threshold:.4f}"
                )
                text = capture_turn(
                    initial_silence_seconds=0.9,
                    max_seconds=min(settings.listener_max_utterance_seconds, 15.0),
                    activation_audio=post_wake_audio,
                    activation_has_speech=True,
                )
            else:
                print(
                    "[JARVIS] Wake isolata · "
                    f"peak={post_peak:.4f} noise={post_noise:.4f} soglia={post_threshold:.4f} · "
                    "wake non inviata a Whisper"
                )
                text = ""

            if not text:
                if settings.listener_wake_ack_enabled and settings.tts_enabled and tts_ready:
                    try:
                        tts.speak("Sì?", streamed=True)
                    except Exception as exc:
                        print(f"[JARVIS] TTS prompt non disponibile: {exc}")
                print("[JARVIS] In ascolto del comando...")
                text = capture_turn(
                    initial_silence_seconds=5.0,
                    max_seconds=min(settings.listener_max_utterance_seconds, 20.0),
                )

            if not text:
                print("[JARVIS] Nessun comando rilevato.")
                agent.set_state(JarvisState.IDLE)
                return

            context = presence.as_context() if settings.presence_enabled else ""
            answer_turn(text, ambient_context=context)

            while not stt.abort_event.is_set():
                print("[JARVIS] Conversazione attiva · ascolto...")
                followup = capture_turn(
                    initial_silence_seconds=settings.listener_followup_silence_seconds,
                    max_seconds=min(settings.listener_max_utterance_seconds, 30.0),
                )
                if not stt.last_recording_heard_speech and not followup:
                    print("[JARVIS] Standby.")
                    break
                if not followup:
                    continue

                normalized = followup.casefold().strip(" .,!?:;")
                stop_phrases = {
                    item.casefold().strip(" .,!?:;")
                    for item in settings.listener_stop_phrases.split("|")
                    if item.strip()
                }
                if normalized in stop_phrases:
                    print("[JARVIS] Standby richiesto.")
                    break

                context = presence.as_context() if settings.presence_enabled else ""
                answer_turn(followup, ambient_context=context)
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
    print(f"[JARVIS] Voice: {voice_name} · {'READY' if tts_ready else 'PENDING SAMPLE'}")
    if settings.presence_enabled:
        print("[JARVIS] Conversation context: ON · ambient mic transcription: OFF")
    else:
        print("[JARVIS] Conversation context: OFF · ambient mic transcription: OFF")
    cognitive_label = "OpenJarvis + guarded local agent" if settings.openjarvis_enabled else "guarded local agent"
    print(f"[JARVIS] Hybrid cognitive engine: {cognitive_label}")
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
