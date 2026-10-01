from __future__ import annotations

import threading
import time
import webbrowser
from dataclasses import dataclass
from typing import Any

import uvicorn

from jarvis.app import app, get_orchestrator
from jarvis.config.settings import get_settings
from jarvis.core.state import JarvisState
from jarvis.monitoring import ProactiveMonitor
from jarvis.presence import PresenceContext
from jarvis.vision import ScreenMonitor
from jarvis.voice import CosyVoiceProxyTTS, LocalSTT, LocalTTS, WakeWordListener
from jarvis.voice.conversation import is_stop_phrase
from jarvis.voice.identity import SpeakerAuthenticator, SpeakerMatch
from jarvis.voice.prosody import analyze_prosody


ACOUSTIC_GUARD_SECONDS = 0.10
POST_WAKE_CAPTURE_DELAY_SECONDS = 0.12


@dataclass(slots=True)
class CapturedTurn:
    text: str
    audio: Any
    speaker_name: str
    speaker_role: str
    speaker_score: float
    authorized: bool
    prosody_context: str


def _post_wake_speech_profile(audio, *, sample_rate: int = 16000) -> tuple[bool, float, float, float]:
    import numpy as np

    array = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not array.size:
        return False, 0.0, 0.0, 0.0012
    frame = max(320, int(sample_rate * 0.06))
    frame_rms: list[float] = []
    for start in range(0, array.size, frame):
        chunk = array[start:start + frame]
        if chunk.size < frame // 2:
            continue
        frame_rms.append(float(np.sqrt(np.mean(np.square(chunk)))))
    if not frame_rms:
        return False, 0.0, 0.0, 0.0012
    peak = max(frame_rms)
    noise = float(np.percentile(np.asarray(frame_rms, dtype=np.float32), 30))
    threshold = max(0.0012, noise * 2.5)
    voiced_frames = sum(1 for value in frame_rms if value >= threshold)
    return voiced_frames >= 2 and peak >= threshold, peak, noise, threshold


def _looks_incomplete(text: str) -> bool:
    value = " ".join(str(text or "").casefold().strip().split())
    if not value:
        return False
    endings = (
        " e", " ma", " però", " pero", " perché", " perche", " che", " di",
        " con", " senza", " quindi", " cioè", " cioe", " oppure", " quando",
        " mentre", " se", " nel", " nella", " per",
    )
    return value.endswith(endings) or value.endswith(("...", "—", "-"))


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
        tts = LocalTTS(voice=settings.tts_voice, speed=settings.tts_speed, lang_code=settings.tts_lang_code)
        voice_name = f"Kokoro · {settings.tts_voice}"

    wake = WakeWordListener(
        model_name=settings.wake_model,
        threshold=settings.wake_threshold,
        chunk_size=settings.wake_chunk_size,
        context_seconds=settings.presence_context_seconds,
        input_device=input_device,
        min_rms=settings.wake_min_rms,
    )
    presence = PresenceContext(max_items=settings.presence_max_items, max_chars=settings.presence_max_chars)
    speakers = SpeakerAuthenticator(settings.speaker_profiles_dir, settings.speaker_match_threshold)
    screen = ScreenMonitor(
        interval_seconds=settings.screen_capture_interval_seconds,
        max_width=settings.screen_max_width,
        jpeg_quality=settings.screen_jpeg_quality,
    )
    proactive = ProactiveMonitor(
        poll_seconds=settings.proactive_poll_seconds,
        cooldown_seconds=settings.proactive_cooldown_seconds,
        cpu_percent=settings.proactive_cpu_percent,
        memory_percent=settings.proactive_memory_percent,
        disk_percent=settings.proactive_disk_percent,
        gpu_temp_c=settings.proactive_gpu_temp_c,
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
        print("[JARVIS] Voce non pronta: continuo senza TTS finché CosyVoice non torna disponibile.")
    elif hasattr(tts, "prepare_output"):
        try:
            tts.prepare_output()
        except Exception as exc:
            print(f"[JARVIS] Uscita voce non pronta: {exc}")
            tts_ready = False

    try:
        print("[STT] Precarico Whisper...")
        stt_device, stt_warm_seconds = stt.warmup()
        print(f"[STT] Whisper pronto su {stt_device} · warm-up {stt_warm_seconds:.2f}s")
    except Exception as exc:
        print(f"[STT] Warm-up non riuscito: {exc}. Ritento al primo turno.")

    busy = threading.Event()
    session_active = threading.Event()
    barge_in_requested = threading.Event()
    owner_enrollment_allowed = threading.Event()
    agent = get_orchestrator()
    if hasattr(agent, "attach_screen_monitor"):
        agent.attach_screen_monitor(screen)

    if settings.screen_monitor_enabled:
        if screen.start():
            print("[JARVIS] Visione schermo: ON · frame volatile in RAM")
        else:
            print(f"[JARVIS] Visione schermo non disponibile: {screen.last_error}")
    if settings.proactive_enabled:
        proactive.start()

    last_reply_at = [0.0]

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
        if (
            settings.listener_barge_in_enabled
            and session_active.is_set()
            and agent.state == JarvisState.SPEAKING
        ):
            stop_current_turn(barge_in=True)

    def verify_barge_speaker(candidate_audio) -> bool:
        if not settings.speaker_auth_enabled:
            return True
        # On the very first session there is no trustworthy voiceprint yet.
        # Do not allow ambient sound or JARVIS' own cloned voice to interrupt
        # playback until the owner has been enrolled from a complete turn.
        if not speakers.has_profiles():
            return False
        match = speakers.identify(candidate_audio, 16000)
        if match.authorized:
            print(f"[VOICE-ID] barge-in={match.name} role={match.role} score={match.score:.2f}")
            return True
        return False

    def _speaker_for_audio(audio) -> SpeakerMatch:
        if not settings.speaker_auth_enabled:
            return SpeakerMatch(settings.speaker_owner_name, settings.speaker_owner_role, 1.0, True)
        if not speakers.has_profiles():
            if settings.speaker_auto_enroll_owner and owner_enrollment_allowed.is_set():
                ok = speakers.enroll(
                    settings.speaker_owner_name,
                    settings.speaker_owner_role,
                    audio,
                    16000,
                )
                if ok:
                    owner_enrollment_allowed.clear()
                    print(f"[VOICE-ID] Profilo proprietario creato: {settings.speaker_owner_name}")
                    return SpeakerMatch(settings.speaker_owner_name, settings.speaker_owner_role, 1.0, True)
            return SpeakerMatch("", "unknown", 0.0, False)
        return speakers.identify(audio, 16000)

    def capture_turn(
        *,
        initial_silence_seconds: float,
        max_seconds: float,
        activation_audio=None,
        activation_has_speech: bool = False,
    ) -> CapturedTurn | None:
        import numpy as np

        agent.set_state(JarvisState.LISTENING)
        capture_started = time.monotonic()
        audio = stt.record_until_silence(
            initial_silence_seconds=initial_silence_seconds,
            max_seconds=max_seconds,
        )
        capture_seconds = time.monotonic() - capture_started
        diagnostic = (
            f"max_rms={stt.last_recording_max_rms:.4f} noise={stt.last_recording_noise_floor:.4f} "
            f"soglia={stt.last_recording_speech_threshold:.4f} fine={stt.last_recording_end_reason or 'unknown'}"
        )
        if not stt.last_recording_heard_speech and not activation_has_speech:
            print(f"[STT] {diagnostic} speech=no · capture={capture_seconds:.2f}s")
            return None

        pieces = []
        if activation_audio is not None and getattr(activation_audio, "size", 0):
            pieces.append(np.asarray(activation_audio, dtype=np.float32).reshape(-1))
        if getattr(audio, "size", 0):
            pieces.append(np.asarray(audio, dtype=np.float32).reshape(-1))
        if not pieces:
            return None
        combined = pieces[0] if len(pieces) == 1 else np.concatenate(pieces)

        match = _speaker_for_audio(combined)
        if settings.speaker_auth_enabled and not match.authorized:
            print(f"[VOICE-ID] voce non autorizzata · score={match.score:.2f}")
            return CapturedTurn("", combined, match.name, match.role, match.score, False, "")

        prosody_context = ""
        if settings.prosody_enabled:
            try:
                prosody_context = analyze_prosody(combined).as_context()
            except Exception:
                prosody_context = ""

        agent.set_state(JarvisState.THINKING)
        stt_started = time.monotonic()
        result = stt.transcribe(combined)
        stt_seconds = time.monotonic() - stt_started
        text = result.text.strip()
        print(
            f"[STT] {diagnostic} speech=si capture={capture_seconds:.2f}s decode={stt_seconds:.2f}s "
            f"speaker={match.name or 'unknown'} score={match.score:.2f}"
        )
        return CapturedTurn(
            text,
            combined,
            match.name or "utente",
            match.role or "unknown",
            match.score,
            True,
            prosody_context,
        )

    def capture_with_wake_paused(**kwargs) -> CapturedTurn | None:
        wake.pause()
        try:
            if wake.selected_device is not None:
                stt.input_device = wake.selected_device
            return capture_turn(**kwargs)
        finally:
            wake.resume()

    def capture_natural_turn(**kwargs) -> CapturedTurn | None:
        turn = capture_with_wake_paused(**kwargs)
        if turn is None or not turn.authorized or not turn.text:
            return turn
        if _looks_incomplete(turn.text):
            continuation = capture_with_wake_paused(
                initial_silence_seconds=settings.stt_incomplete_phrase_silence_seconds,
                max_seconds=min(settings.listener_max_utterance_seconds, 18.0),
            )
            if (
                continuation is not None
                and continuation.authorized
                and continuation.text
                and continuation.speaker_name == turn.speaker_name
            ):
                turn.text = f"{turn.text} {continuation.text}".strip()
        return turn

    def speak_text(text: str) -> None:
        if not text or not settings.tts_enabled or not tts_ready:
            return
        try:
            agent.set_state(JarvisState.SPEAKING)
            tts.speak(text, streamed=True)
            acoustic_guard()
        except Exception as exc:
            if not barge_in_requested.is_set():
                print(f"[JARVIS] TTS non disponibile: {exc}")

    def speak_error(reason: object) -> str:
        phrase = str(settings.listener_error_phrase or "").strip() or "Mi dispiace signore, non ho capito l'ultima parte."
        print(f"[JARVIS] Errore elaborazione: {reason}")
        if not barge_in_requested.is_set():
            speak_text(phrase)
        agent.set_state(JarvisState.IDLE)
        return phrase

    def answer_turn(turn: CapturedTurn, ambient_context: str = "") -> str:
        text = turn.text
        if hasattr(agent, "set_interaction_context"):
            agent.set_interaction_context(
                speaker_name=turn.speaker_name,
                speaker_role=turn.speaker_role,
                prosody=turn.prosody_context,
            )
        print(f"{turn.speaker_name.upper()}: {text}")
        brain_started = time.monotonic()
        first_token_at = None
        brain_done_at = None
        collected: list[str] = []

        def brain_chunks():
            nonlocal first_token_at, brain_done_at
            stream_method = getattr(agent, "process_message_stream", None)
            iterator = (
                stream_method(text, ambient_context=ambient_context)
                if callable(stream_method)
                else iter([agent.process_message(text, ambient_context=ambient_context)])
            )
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
            if not barge_in_requested.is_set():
                print(f"[JARVIS] Stream risposta non disponibile: {exc}")

        reply = "".join(collected).strip()
        if brain_done_at is None:
            brain_done_at = time.monotonic()
        if barge_in_requested.is_set():
            print("[JARVIS] Risposta interrotta dall'utente.")
            return reply
        if not reply:
            return speak_error("il cervello non ha restituito testo")

        presence.add(text, speaker=turn.speaker_name)
        presence.add(reply, speaker="Jarvis")
        last_reply_at[0] = time.monotonic()
        print(f"JARVIS: {reply}")
        if first_token_at is not None:
            print(f"[LATENCY] cervello_primo_token={first_token_at - brain_started:.2f}s")
        print(f"[LATENCY] cervello_completo={brain_done_at - brain_started:.2f}s")

        if settings.tts_enabled and tts_ready and not tts_spoken:
            try:
                agent.set_state(JarvisState.SPEAKING)
                tts.speak(reply, streamed=True)
                tts_spoken = True
            except Exception as exc:
                print(f"[JARVIS] TTS fallback non disponibile: {exc}")
        if tts_spoken:
            acoustic_guard()
        return reply

    def capture_after_activation(*, acknowledge_if_empty: bool = True) -> CapturedTurn | None:
        time.sleep(POST_WAKE_CAPTURE_DELAY_SECONDS)
        try:
            post_audio = wake.post_wake_audio(seconds=0.82, exclude_head_seconds=0.12)
        except Exception:
            post_audio = None
        continued, peak, noise, threshold = _post_wake_speech_profile(post_audio)
        if continued:
            print(f"[JARVIS] Frase dopo attivazione · peak={peak:.4f} noise={noise:.4f} soglia={threshold:.4f}")
            turn = capture_natural_turn(
                initial_silence_seconds=0.75,
                max_seconds=min(settings.listener_max_utterance_seconds, 18.0),
                activation_audio=post_audio,
                activation_has_speech=True,
            )
            if turn is not None and (turn.text or not turn.authorized):
                return turn
        if acknowledge_if_empty:
            speak_text(settings.listener_activation_phrase)
        return capture_natural_turn(
            initial_silence_seconds=settings.persistent_session_poll_seconds,
            max_seconds=min(settings.listener_max_utterance_seconds, 28.0),
        )

    def capture_after_barge_in() -> CapturedTurn | None:
        time.sleep(0.08)
        try:
            buffered = wake.post_wake_audio(seconds=1.05, exclude_head_seconds=0.0)
        except Exception:
            buffered = None
        continued, _peak, _noise, _threshold = _post_wake_speech_profile(buffered)
        return capture_natural_turn(
            initial_silence_seconds=1.1,
            max_seconds=min(settings.listener_max_utterance_seconds, 20.0),
            activation_audio=buffered,
            activation_has_speech=continued,
        )

    def speak_unauthorized() -> None:
        phrase = settings.listener_unauthorized_phrase.strip() or "Mi dispiace, non posso eseguire questa richiesta."
        speak_text(phrase)

    def maybe_proactive_alert() -> None:
        if not session_active.is_set() or not settings.proactive_enabled:
            return
        alert = proactive.pop()
        if alert is not None and not barge_in_requested.is_set():
            print(f"[PROACTIVE] {alert.key}: {alert.message}")
            speak_text(alert.message)

    def handle_wake() -> None:
        if busy.is_set():
            request_barge_in()
            return

        busy.set()
        session_active.set()
        barge_in_requested.clear()
        if settings.speaker_auth_enabled and not speakers.has_profiles():
            owner_enrollment_allowed.set()
        try:
            print("[JARVIS] Sessione vocale attiva.")
            turn = capture_after_activation(acknowledge_if_empty=True)

            while session_active.is_set():
                if turn is None:
                    maybe_proactive_alert()
                    turn = capture_natural_turn(
                        initial_silence_seconds=settings.persistent_session_poll_seconds,
                        max_seconds=min(settings.listener_max_utterance_seconds, 28.0),
                    )
                    continue

                if not turn.authorized:
                    speak_unauthorized()
                    turn = None
                    continue
                if not turn.text:
                    turn = None
                    continue
                if is_stop_phrase(turn.text, settings.listener_stop_phrases):
                    print("[JARVIS] Sessione chiusa su richiesta.")
                    session_active.clear()
                    break

                context = presence.as_context() if settings.presence_enabled else ""
                seconds_since_reply = (
                    time.monotonic() - last_reply_at[0] if last_reply_at[0] > 0 else 9999.0
                )
                addressed = True
                classifier = getattr(agent, "is_addressed_to_jarvis", None)
                if callable(classifier):
                    addressed = bool(
                        classifier(
                            turn.text,
                            ambient_context=context,
                            seconds_since_reply=seconds_since_reply,
                        )
                    )
                if not addressed:
                    presence.add(turn.text, speaker=turn.speaker_name)
                    if agent.memory:
                        try:
                            agent.memory.record_message(
                                turn.speaker_name,
                                turn.text,
                                {"speaker_role": turn.speaker_role, "addressed_to_jarvis": False},
                            )
                        except Exception:
                            pass
                    print(f"[JARVIS] Frase ambientale, nessuna risposta: {turn.text}")
                    turn = None
                    continue

                answer_turn(turn, ambient_context=context)

                if barge_in_requested.is_set():
                    barge_in_requested.clear()
                    print("[JARVIS] Interruzione acquisita · ascolto la correzione...")
                    turn = capture_after_barge_in()
                    continue

                maybe_proactive_alert()
                turn = capture_natural_turn(
                    initial_silence_seconds=settings.persistent_session_poll_seconds,
                    max_seconds=min(settings.listener_max_utterance_seconds, 28.0),
                )
        except Exception as exc:
            speak_error(exc)
        finally:
            session_active.clear()
            wake.resume()
            barge_in_requested.clear()
            owner_enrollment_allowed.clear()
            agent.set_state(JarvisState.IDLE)
            busy.clear()
            print("[JARVIS] Standby · di' Jarvis per aprire una nuova sessione.")

    def serve_ui() -> None:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

    threading.Thread(target=serve_ui, daemon=True, name="jarvis-web").start()
    time.sleep(0.8)
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass

    print("[JARVIS] Desktop runtime online.")
    print(f"[JARVIS] Attivazione iniziale: {settings.wake_model}; dopo l'attivazione la wake word non serve più.")
    print(f"[JARVIS] Voice: {voice_name} · {'READY' if tts_ready else 'PENDING'}")
    print(f"[JARVIS] Speaker profiles: {len(speakers.profile_names())} · auth={'ON' if settings.speaker_auth_enabled else 'OFF'}")
    print(f"[JARVIS] Persistent conversation: {'ON' if settings.persistent_session_enabled else 'OFF'}")
    print(f"[JARVIS] Screen context: {'ON' if settings.screen_monitor_enabled else 'OFF'}")
    print("[JARVIS] UI: http://127.0.0.1:8000")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        wake.run(
            handle_wake,
            busy=lambda: busy.is_set() and agent.state == JarvisState.SPEAKING,
            interrupt=request_barge_in if settings.listener_barge_in_enabled else None,
            conversation_active=session_active.is_set,
            speech_interrupt=verify_barge_speaker if settings.listener_barge_in_enabled else None,
            barge_in_min_rms=settings.barge_in_min_rms,
            barge_in_min_seconds=settings.barge_in_min_seconds,
            echo_guard_enabled=settings.echo_guard_enabled,
            echo_guard_max_correlation=settings.echo_guard_max_correlation,
        )
    except KeyboardInterrupt:
        pass
    finally:
        session_active.clear()
        stop_current_turn()
        busy.clear()
        wake.stop()
        proactive.stop()
        screen.stop()
        presence.clear()
        agent.close()


if __name__ == "__main__":
    main()
