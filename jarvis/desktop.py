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
from jarvis.voice.conversation import followup_wait_seconds, is_stop_phrase


ACOUSTIC_GUARD_SECONDS = 0.24
POST_WAKE_CAPTURE_DELAY_SECONDS = 0.38


def _post_wake_speech_profile(audio, *, sample_rate: int = 16000) -> tuple[bool, float, float, float]:
    """Decide whether real speech continued after the wake word."""
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
        endpoint_silence_seconds=settings.stt_silence_seconds,
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
        min_rms=settings.wake_min_rms,
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
    barge_in_requested = threading.Event()
    agent = get_orchestrator()

    def acoustic_guard() -> None:
        time.sleep(ACOUSTIC_GUARD_SECONDS)

    def stop_current_turn(*, barge_in: bool = False) -> None:
        if barge_in:
            barge_in_requested.set()
        stt.abort()
        if tts_ready:
            tts.stop()
        agent.set_state(JarvisState.IDLE)

    def request_barge_in() -> None:
        """Interrupt speech after a verified wake word while a turn is active."""
        if not settings.listener_barge_in_enabled:
            return
        stop_current_turn(barge_in=True)

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

        diagnostic = (
            f"max_rms={stt.last_recording_max_rms:.4f} "
            f"noise={stt.last_recording_noise_floor:.4f} "
            f"soglia_voce={stt.last_recording_speech_threshold:.4f} "
            f"release={stt.last_recording_release_threshold:.4f} "
            f"fine={stt.last_recording_end_reason or 'unknown'}"
        )

        if not stt.last_recording_heard_speech and not activation_has_speech:
            print(
                f"[STT] {diagnostic} speech=no gain=1.0x · "
                f"capture={capture_seconds:.2f}s · decode=saltata (nessuna voce)"
            )
            return ""

        pieces = []
        if activation_audio is not None and getattr(activation_audio, "size", 0):
            pieces.append(activation_audio.astype(np.float32, copy=False))
        if getattr(audio, "size", 0):
            pieces.append(audio.astype(np.float32, copy=False))
        if not pieces:
            print(
                f"[STT] {diagnostic} speech=no gain=1.0x · "
                f"capture={capture_seconds:.2f}s · decode=saltata (audio vuoto)"
            )
            return ""

        agent.set_state(JarvisState.THINKING)
        print(f"[JARVIS] Voce rilevata · elaboro... · {diagnostic}")

        combined = pieces[0] if len(pieces) == 1 else np.concatenate(pieces)
        stt_started = time.monotonic()
        result = stt.transcribe(combined)
        stt_seconds = time.monotonic() - stt_started
        text = result.text.strip()
        speech_label = "si" if stt.last_recording_heard_speech else "post-wake"

        print(
            f"[STT] {diagnostic} speech={speech_label} gain={stt.last_recording_gain:.1f}x · "
            f"capture={capture_seconds:.2f}s · decode={stt_seconds:.2f}s"
        )
        return text

    def capture_with_wake_paused(**kwargs) -> str:
        """Give STT exclusive ownership of the Windows microphone."""
        wake.pause()
        try:
            if wake.selected_device is not None:
                stt.input_device = wake.selected_device
            return capture_turn(**kwargs)
        finally:
            wake.resume()

    def speak_error(reason: object) -> str:
        phrase = str(settings.listener_error_phrase or "").strip()
        if not phrase:
            phrase = "Mi dispiace signore, ho avuto un problema nell'elaborare la richiesta."
        print(f"[JARVIS] Errore elaborazione: {reason}")
        if settings.tts_enabled and tts_ready and not barge_in_requested.is_set():
            try:
                agent.set_state(JarvisState.SPEAKING)
                tts.speak(phrase, streamed=True)
                acoustic_guard()
            except Exception as voice_exc:
                print(f"[JARVIS] Impossibile pronunciare l'errore: {voice_exc}")
        agent.set_state(JarvisState.IDLE)
        return phrase

    def answer_turn(text: str, ambient_context: str = "") -> str:
        print(f"TU: {text}")
        brain_started = time.monotonic()
        first_token_at = None
        brain_done_at = None
        collected: list[str] = []

        def brain_chunks():
            nonlocal first_token_at, brain_done_at
            stream_method = getattr(agent, "process_message_stream", None)
            if callable(stream_method):
                iterator = stream_method(text, ambient_context=ambient_context)
            else:
                iterator = iter([agent.process_message(text, ambient_context=ambient_context)])
            try:
                for chunk in iterator:
                    if not chunk:
                        continue
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                    collected.append(chunk)
                    yield chunk
            finally:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()
                brain_done_at = time.monotonic()

        tts_spoken = False
        try:
            if settings.tts_enabled and tts_ready and hasattr(tts, "speak_text_stream"):
                tts_started = time.monotonic()
                tts.speak_text_stream(brain_chunks())
                tts_spoken = not barge_in_requested.is_set()
                print(f"[LATENCY] turno_voce_totale={time.monotonic() - tts_started:.2f}s")
            else:
                for _ in brain_chunks():
                    pass
        except Exception as exc:
            print(f"[JARVIS] Stream risposta non disponibile: {exc}")

        reply = "".join(collected).strip()
        if brain_done_at is None:
            brain_done_at = time.monotonic()

        if barge_in_requested.is_set():
            print("[JARVIS] Risposta interrotta dall'utente.")
            return reply

        if not reply:
            return speak_error("il cervello non ha restituito una risposta utilizzabile")

        presence.add(text, speaker="utente")
        presence.add(reply, speaker="Jarvis")
        print(f"JARVIS: {reply}")
        if first_token_at is not None:
            print(f"[LATENCY] cervello_primo_token={first_token_at - brain_started:.2f}s")
        print(f"[LATENCY] cervello_completo={brain_done_at - brain_started:.2f}s")

        reasoning = agent.reasoning_status()
        if reasoning.get("used_openjarvis"):
            print(
                "[COGNITIVE] OpenJarvis "
                f"agent={reasoning.get('agent')} model={reasoning.get('model')} "
                f"score={reasoning.get('score')}"
            )

        # If live TTS failed but the brain produced text, retry once through the
        # simpler streaming endpoint instead of silently dropping the answer.
        if settings.tts_enabled and tts_ready and not tts_spoken:
            try:
                agent.set_state(JarvisState.SPEAKING)
                tts_started = time.monotonic()
                tts.speak(reply, streamed=True)
                print(f"[LATENCY] voce_fallback={time.monotonic() - tts_started:.2f}s")
                tts_spoken = True
            except Exception as exc:
                print(f"[JARVIS] TTS fallback non disponibile: {exc}")

        if tts_spoken:
            acoustic_guard()
        return reply

    def capture_command_after_verified_wake() -> str:
        """Reuse post-wake PCM and then hand the microphone to Whisper."""
        time.sleep(POST_WAKE_CAPTURE_DELAY_SECONDS)

        try:
            post_wake_audio = wake.post_wake_audio(seconds=0.72, exclude_head_seconds=0.14)
        except Exception:
            post_wake_audio = None

        continued, post_peak, post_noise, post_threshold = _post_wake_speech_profile(post_wake_audio)

        if continued:
            print(
                "[JARVIS] Comando dopo wake rilevato · "
                f"peak={post_peak:.4f} noise={post_noise:.4f} soglia={post_threshold:.4f}"
            )
            text = capture_with_wake_paused(
                initial_silence_seconds=0.75,
                max_seconds=min(settings.listener_max_utterance_seconds, 12.0),
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

        if text:
            return text

        if settings.listener_wake_ack_enabled and settings.tts_enabled and tts_ready:
            try:
                tts.speak("Sì?", streamed=True)
                acoustic_guard()
            except Exception as exc:
                print(f"[JARVIS] TTS prompt non disponibile: {exc}")

        print("[JARVIS] In ascolto del comando...")
        return capture_with_wake_paused(
            initial_silence_seconds=2.8,
            max_seconds=min(settings.listener_max_utterance_seconds, 12.0),
        )

    def handle_wake() -> None:
        # A verified wake while busy is normally handled inside wake_stable via
        # request_barge_in(). This guard prevents accidental parallel sessions.
        if busy.is_set():
            request_barge_in()
            return

        busy.set()
        barge_in_requested.clear()
        try:
            print("[JARVIS] Ti ascolto...")
            text = capture_command_after_verified_wake()
            if not text:
                print("[JARVIS] Nessun comando rilevato.")
                return

            while text:
                if is_stop_phrase(text, settings.listener_stop_phrases):
                    print("[JARVIS] Standby richiesto.")
                    break

                context = presence.as_context() if settings.presence_enabled else ""
                answer_turn(text, ambient_context=context)

                if barge_in_requested.is_set():
                    # wake_stable has already stopped playback and started a new
                    # post-wake PCM buffer. Continue this same session rather than
                    # requiring another wake callback/thread.
                    barge_in_requested.clear()
                    print("[JARVIS] Barge-in acquisito · ascolto il nuovo comando...")
                    text = capture_command_after_verified_wake()
                    if not text:
                        print("[JARVIS] Barge-in senza comando · standby.")
                        break
                    continue

                print("[JARVIS] Conversazione attiva · ascolto...")
                followup = capture_with_wake_paused(
                    initial_silence_seconds=followup_wait_seconds(
                        settings.listener_followup_silence_seconds
                    ),
                    max_seconds=min(settings.listener_max_utterance_seconds, 20.0),
                )
                if not stt.last_recording_heard_speech and not followup:
                    print("[JARVIS] Standby.")
                    break
                if not followup:
                    continue
                text = followup
        except Exception as exc:
            speak_error(exc)
        finally:
            wake.resume()
            barge_in_requested.clear()
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
    print(
        f"[JARVIS] Follow-up: {followup_wait_seconds(settings.listener_followup_silence_seconds):.1f}s · "
        f"barge-in wake: {'ON' if settings.listener_barge_in_enabled else 'OFF'}"
    )
    print("[JARVIS] UI: http://127.0.0.1:8000")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        wake.run(
            handle_wake,
            busy=busy.is_set,
            interrupt=request_barge_in if settings.listener_barge_in_enabled else None,
        )
    except KeyboardInterrupt:
        pass
    finally:
        stop_current_turn()
        busy.clear()
        wake.stop()
        presence.clear()
        agent.close()


if __name__ == "__main__":
    main()
