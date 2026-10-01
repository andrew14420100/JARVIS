from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from jarvis.app import app, get_orchestrator
from jarvis.config.settings import get_settings
from jarvis.core.events import EventBus, JarvisEvent
from jarvis.core.router import JarvisRouter
from jarvis.core.state import JarvisState
from jarvis.presence import PresenceContext
from jarvis.voice import CosyVoiceProxyTTS, LocalSTT, LocalTTS, WakeWordListener
from jarvis.voice.realtime_stt import NvidiaRealtimeSTT


ACOUSTIC_GUARD_SECONDS = 0.28
POST_WAKE_CAPTURE_DELAY_SECONDS = 0.12


def _post_wake_speech_profile(
    audio,
    *,
    sample_rate: int = 16000,
) -> tuple[bool, float, float, float]:
    """Detect speech immediately following the wake word without decoding it."""
    import numpy as np

    array = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not array.size:
        return False, 0.0, 0.0, 0.0010

    frame = max(320, int(sample_rate * 0.05))
    frame_rms: list[float] = []
    for start in range(0, array.size, frame):
        chunk = array[start : start + frame]
        if chunk.size < frame // 2:
            continue
        frame_rms.append(float(np.sqrt(np.mean(np.square(chunk)))))

    if not frame_rms:
        return False, 0.0, 0.0, 0.0010

    values = np.asarray(frame_rms, dtype=np.float32)
    peak = float(values.max())
    noise = float(np.percentile(values, 30))
    threshold = max(0.0010, noise * 2.5)
    voiced_frames = sum(value >= threshold for value in frame_rms)
    return voiced_frames >= 2 and peak >= threshold, peak, noise, threshold


def main() -> None:
    settings = get_settings()
    settings.voice_enabled = True
    input_device = settings.audio_input_device.strip() or None

    requested_backend = settings.stt_backend.strip().lower()
    if requested_backend in {"nvidia", "nvidia-realtime", "nemotron", "nemotron-realtime"}:
        stt = NvidiaRealtimeSTT(
            http_url=settings.nvidia_asr_http_url,
            websocket_url=settings.nvidia_asr_websocket_url,
            language=settings.nvidia_asr_language,
            input_device=input_device,
            endpointing_ms=settings.nvidia_asr_endpointing_ms,
        )
        if not stt.available():
            print(
                "[STT] NVIDIA Nemotron realtime non disponibile. "
                "Uso temporaneamente faster-whisper CUDA."
            )
            print(f"[STT] {stt.dependency_error()}")
            stt = LocalSTT(
                model_name=settings.stt_model,
                device=settings.stt_device,
                compute_type=settings.stt_compute_type,
                language=settings.stt_language,
                input_device=input_device,
            )
            stt_backend_name = "faster-whisper CUDA fallback"
        else:
            stt_backend_name = "NVIDIA Nemotron 3.5 realtime · local CUDA"
    else:
        stt = LocalSTT(
            model_name=settings.stt_model,
            device=settings.stt_device,
            compute_type=settings.stt_compute_type,
            language=settings.stt_language,
            input_device=input_device,
        )
        stt_backend_name = "faster-whisper"

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
            "[JARVIS] Voce non pronta. Il runtime continua senza TTS; "
            "verifica CosyVoice 3."
        )

    try:
        print(f"[STT] Backend: {stt_backend_name}")
        print("[STT] Precarico ASR...")
        stt_device, stt_warm_seconds = stt.warmup()
        print(
            f"[STT] ASR pronto su {stt_device} · "
            f"warm-up {stt_warm_seconds:.2f}s"
        )
    except Exception as exc:
        if isinstance(stt, NvidiaRealtimeSTT):
            print(f"[STT] NVIDIA realtime non pronto ({exc}); uso faster-whisper CUDA.")
            stt = LocalSTT(
                model_name=settings.stt_model,
                device=settings.stt_device,
                compute_type=settings.stt_compute_type,
                language=settings.stt_language,
                input_device=input_device,
            )
            stt_backend_name = "faster-whisper CUDA fallback"
            stt_device, stt_warm_seconds = stt.warmup()
            print(
                f"[STT] Whisper pronto su {stt_device} · "
                f"warm-up {stt_warm_seconds:.2f}s"
            )
        else:
            print(f"[STT] Warm-up non riuscito: {exc}. Verra' ritentato al primo comando.")

    busy = threading.Event()
    agent = get_orchestrator()
    event_bus = EventBus()
    router = JarvisRouter()

    def acoustic_guard() -> None:
        time.sleep(ACOUSTIC_GUARD_SECONDS)

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
    ) -> str:
        agent.set_state(JarvisState.LISTENING)
        capture_started = time.monotonic()

        if isinstance(stt, NvidiaRealtimeSTT):
            audio = stt.record_until_silence(
                initial_silence_seconds=initial_silence_seconds,
                max_seconds=max_seconds,
                activation_audio=activation_audio,
            )
        else:
            audio = stt.record_until_silence(
                initial_silence_seconds=initial_silence_seconds,
                max_seconds=max_seconds,
            )

        capture_seconds = time.monotonic() - capture_started
        diagnostic = (
            f"max_rms={stt.last_recording_max_rms:.4f} "
            f"noise={stt.last_recording_noise_floor:.4f} "
            f"soglia_voce={stt.last_recording_speech_threshold:.4f} "
            f"release={stt.last_recording_release_threshold:.4f} "
            f"fine={stt.last_recording_end_reason or 'unknown'}"
        )

        if not stt.last_recording_heard_speech:
            print(
                f"[STT] {diagnostic} speech=no · "
                f"capture={capture_seconds:.2f}s · decode=saltata"
            )
            return ""

        agent.set_state(JarvisState.THINKING)

        if isinstance(stt, NvidiaRealtimeSTT):
            result = stt.transcribe(audio)
            stt_seconds = 0.0
            text = result.text.strip()
        else:
            stt_started = time.monotonic()
            result = stt.transcribe(audio)
            stt_seconds = time.monotonic() - stt_started
            text = result.text.strip()

        print(
            f"[STT] {diagnostic} speech=si · "
            f"capture={capture_seconds:.2f}s · decode={stt_seconds:.2f}s"
        )
        if text:
            print(f"[STT] testo finale: {text}")
        return text

    def answer_turn(text: str, ambient_context: str = "") -> str:
        print(f"TU: {text}")

        intent = router.classify(text)
        event_bus.emit(
            JarvisEvent(
                "USER_COMMAND",
                {"text": text, "intent": intent},
            )
        )
        print(f"[CORE] Intent rilevato: {intent}")

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
                print(
                    f"[LATENCY] voce_totale="
                    f"{time.monotonic() - tts_started:.2f}s"
                )
                acoustic_guard()
            except Exception as exc:
                print(f"[JARVIS] TTS non disponibile: {exc}")

        return reply

    def handle_wake() -> None:
        if busy.is_set():
            interrupt()
            return

        busy.set()
        if wake.selected_device is not None:
            stt.input_device = wake.selected_device

        # Keep the wake listener alive for a very short tail so a fast
        # "Hey Jarvis, ..." command is captured before the microphone changes
        # ownership to the command STT.
        time.sleep(POST_WAKE_CAPTURE_DELAY_SECONDS)
        post_wake_audio = None
            try:
                post_wake_audio = wake.post_wake_audio(
                    seconds=0.72,
                    exclude_head_seconds=0.08,
                )
        except Exception:
            post_wake_audio = None

        continued, post_peak, post_noise, post_threshold = _post_wake_speech_profile(
            post_wake_audio
        )

        wake.pause()
        try:
            print("[JARVIS] Ti ascolto...")

            if continued:
                print(
                    "[JARVIS] Comando immediato rilevato · "
                    f"peak={post_peak:.4f} noise={post_noise:.4f} "
                    f"soglia={post_threshold:.4f}"
                )
                text = capture_turn(
                    initial_silence_seconds=0.55,
                    max_seconds=min(settings.listener_max_utterance_seconds, 12.0),
                    activation_audio=post_wake_audio,
                )
            else:
                print(
                    "[JARVIS] Wake isolata · "
                    f"peak={post_peak:.4f} noise={post_noise:.4f} "
                    f"soglia={post_threshold:.4f}"
                )
                text = ""

            if not text:
                print("[JARVIS] In ascolto del comando...")
                text = capture_turn(
                    initial_silence_seconds=1.35,
                    max_seconds=min(settings.listener_max_utterance_seconds, 12.0),
                )

            if not text:
                if settings.listener_wake_ack_enabled and settings.tts_enabled and tts_ready:
                    try:
                        tts.speak("Sì?", streamed=True)
                        acoustic_guard()
                    except Exception as exc:
                        print(f"[JARVIS] TTS prompt non disponibile: {exc}")

                print("[JARVIS] In ascolto del comando...")
                text = capture_turn(
                    initial_silence_seconds=2.8,
                    max_seconds=min(settings.listener_max_utterance_seconds, 12.0),
                )

            if not text:
                print("[JARVIS] Nessun comando rilevato.")
                return

            context = presence.as_context() if settings.presence_enabled else ""
            answer_turn(text, ambient_context=context)

            while not stt.abort_event.is_set():
                print("[JARVIS] Conversazione attiva · ascolto...")
                followup = capture_turn(
                    initial_silence_seconds=min(
                        settings.listener_followup_silence_seconds,
                        3.5,
                    ),
                    max_seconds=min(settings.listener_max_utterance_seconds, 16.0),
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

    threading.Thread(
        target=serve_ui,
        daemon=True,
        name="jarvis-web",
    ).start()

    time.sleep(0.8)
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass

    print("[JARVIS] Desktop runtime online.")
    print(f"[JARVIS] Wake word: {settings.wake_model}")
    print(f"[JARVIS] Voice: {voice_name} · {'READY' if tts_ready else 'PENDING SAMPLE'}")
    print(f"[JARVIS] STT: {stt_backend_name}")

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
    print("[JARVIS] UI: http://127.0.0.1:8000")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        wake.run(
            handle_wake,
            busy=busy.is_set,
            interrupt=interrupt,
        )
    except KeyboardInterrupt:
        pass
    finally:
        interrupt()
        wake.stop()
        presence.clear()
        agent.close()


if __name__ == "__main__":
    main()
