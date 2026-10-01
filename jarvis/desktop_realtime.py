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
from jarvis.voice import CosyVoiceProxyTTS, LocalSTT, LocalTTS
from jarvis.voice.conversation import is_stop_phrase
from jarvis.voice.full_duplex import FullDuplexMicrophone
from jarvis.voice.identity import SpeakerAuthenticator, SpeakerMatch
from jarvis.voice.prosody import analyze_prosody


@dataclass(slots=True)
class RealtimeTurn:
    text: str
    audio: Any
    speaker_name: str
    speaker_role: str
    speaker_score: float
    authorized: bool
    prosody_context: str


def main() -> None:
    settings = get_settings()
    settings.voice_enabled = True

    stt = LocalSTT(
        model_name=settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        language=settings.stt_language,
        input_device=None,
        endpoint_silence_seconds=settings.stt_silence_seconds,
    )

    if settings.tts_mode.strip().lower() == "cosyvoice-local" and settings.cosyvoice_enabled:
        tts = CosyVoiceProxyTTS(
            base_url=settings.cosyvoice_service_url,
            timeout_seconds=settings.request_timeout_seconds,
            output_device=settings.audio_output_device.strip() or None,
        )
        voice_name = "CosyVoice 3 · cloned local voice"
    else:
        tts = LocalTTS(voice=settings.tts_voice, speed=settings.tts_speed, lang_code=settings.tts_lang_code)
        voice_name = f"Kokoro · {settings.tts_voice}"

    speakers = SpeakerAuthenticator(settings.speaker_profiles_dir, settings.speaker_match_threshold)
    presence = PresenceContext(max_items=settings.presence_max_items, max_chars=settings.presence_max_chars)
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

    agent = get_orchestrator()
    if hasattr(agent, "attach_screen_monitor"):
        agent.attach_screen_monitor(screen)

    if not stt.available():
        raise SystemExit(f"STT non disponibile: {stt.dependency_status()}")

    tts_ready = bool(settings.tts_enabled and tts.available())
    if tts_ready and hasattr(tts, "prepare_output"):
        try:
            tts.prepare_output()
        except Exception as exc:
            tts_ready = False
            print(f"[JARVIS] Uscita voce non pronta: {exc}")
    elif not tts_ready:
        print("[JARVIS] CosyVoice non pronta: la conversazione resta attiva ma senza audio in uscita.")

    print("[STT] Precarico Whisper...")
    try:
        stt_device, warm = stt.warmup()
        print(f"[STT] Whisper pronto su {stt_device} · warm-up {warm:.2f}s")
    except Exception as exc:
        print(f"[STT] Warm-up non riuscito: {exc}. Ritento al primo turno.")

    if settings.screen_monitor_enabled:
        if screen.start():
            print("[JARVIS] Visione schermo: ON · frame volatile in RAM")
        else:
            print(f"[JARVIS] Visione schermo non disponibile: {screen.last_error}")
    if settings.proactive_enabled:
        proactive.start()

    response_active = threading.Event()
    barge_in_requested = threading.Event()
    owner_enrollment_allowed = threading.Event()
    if settings.speaker_auth_enabled and not speakers.has_profiles():
        owner_enrollment_allowed.set()

    last_reply_at = [0.0]

    def verify_barge_speaker(audio) -> bool:
        if not settings.speaker_auth_enabled:
            return True
        if not speakers.has_profiles():
            return False
        match = speakers.identify(audio, 16000)
        if match.authorized:
            print(f"[VOICE-ID] interrupt={match.name} role={match.role} score={match.score:.2f}")
            return True
        return False

    def interrupt_response() -> None:
        if not response_active.is_set():
            return
        barge_in_requested.set()
        if tts_ready:
            try:
                tts.stop()
            except Exception:
                pass
        agent.set_state(JarvisState.IDLE)

    mic = FullDuplexMicrophone(
        input_device=settings.audio_input_device.strip() or None,
        sample_rate=16000,
        frame_ms=40,
        endpoint_silence_seconds=settings.stt_silence_seconds,
        min_speech_rms=0.00090,
        max_utterance_seconds=settings.listener_max_utterance_seconds,
        assistant_active=response_active.is_set,
        assistant_speaking=(tts.is_speaking if hasattr(tts, "is_speaking") else (lambda: False)),
        verify_barge_speaker=verify_barge_speaker,
        on_barge_in=interrupt_response,
        echo_guard_enabled=settings.echo_guard_enabled,
        echo_guard_max_correlation=settings.echo_guard_max_correlation,
        barge_in_min_seconds=settings.barge_in_min_seconds,
    )

    def speaker_for_audio(audio) -> SpeakerMatch:
        if not settings.speaker_auth_enabled:
            return SpeakerMatch(settings.speaker_owner_name, settings.speaker_owner_role, 1.0, True)
        if not speakers.has_profiles():
            if settings.speaker_auto_enroll_owner and owner_enrollment_allowed.is_set():
                if speakers.enroll(settings.speaker_owner_name, settings.speaker_owner_role, audio, 16000):
                    owner_enrollment_allowed.clear()
                    print(f"[VOICE-ID] Profilo proprietario creato: {settings.speaker_owner_name}")
                    return SpeakerMatch(settings.speaker_owner_name, settings.speaker_owner_role, 1.0, True)
            return SpeakerMatch("", "unknown", 0.0, False)
        return speakers.identify(audio, 16000)

    def decode_audio(audio) -> RealtimeTurn | None:
        if audio is None or not getattr(audio, "size", 0):
            return None
        match = speaker_for_audio(audio)
        if settings.speaker_auth_enabled and not match.authorized:
            print(f"[VOICE-ID] voce non autorizzata · score={match.score:.2f}")
            return RealtimeTurn("", audio, match.name, match.role, match.score, False, "")

        prosody = ""
        if settings.prosody_enabled:
            try:
                prosody = analyze_prosody(audio).as_context()
            except Exception:
                pass

        agent.set_state(JarvisState.THINKING)
        started = time.monotonic()
        result = stt.transcribe(audio)
        elapsed = time.monotonic() - started
        text = result.text.strip()
        print(
            f"[STT] realtime decode={elapsed:.2f}s · audio={len(audio) / 16000.0:.2f}s · "
            f"speaker={match.name or 'unknown'} score={match.score:.2f}"
        )
        if not text:
            return None
        return RealtimeTurn(
            text=text,
            audio=audio,
            speaker_name=match.name or "utente",
            speaker_role=match.role or "unknown",
            speaker_score=match.score,
            authorized=True,
            prosody_context=prosody,
        )

    def speak_text(text: str) -> None:
        if not text or not tts_ready:
            return
        response_active.set()
        barge_in_requested.clear()
        try:
            agent.set_state(JarvisState.SPEAKING)
            tts.speak(text, streamed=True)
        except Exception as exc:
            if not barge_in_requested.is_set():
                print(f"[JARVIS] TTS non disponibile: {exc}")
        finally:
            response_active.clear()
            agent.set_state(JarvisState.IDLE)

    def speak_unauthorized() -> None:
        phrase = settings.listener_unauthorized_phrase.strip() or "Mi dispiace, non posso eseguire questa richiesta."
        speak_text(phrase)

    def answer_turn(turn: RealtimeTurn, ambient_context: str) -> str:
        if hasattr(agent, "set_interaction_context"):
            agent.set_interaction_context(
                speaker_name=turn.speaker_name,
                speaker_role=turn.speaker_role,
                prosody=turn.prosody_context,
            )
        print(f"{turn.speaker_name.upper()}: {turn.text}")

        response_active.set()
        barge_in_requested.clear()
        brain_started = time.monotonic()
        first_token = None
        brain_done = None
        collected: list[str] = []

        def brain_chunks():
            nonlocal first_token, brain_done
            stream_method = getattr(agent, "process_message_stream", None)
            iterator = (
                stream_method(turn.text, ambient_context=ambient_context)
                if callable(stream_method)
                else iter([agent.process_message(turn.text, ambient_context=ambient_context)])
            )
            try:
                for chunk in iterator:
                    if barge_in_requested.is_set():
                        break
                    if not chunk:
                        continue
                    if first_token is None:
                        first_token = time.monotonic()
                    collected.append(str(chunk))
                    yield str(chunk)
            finally:
                closer = getattr(iterator, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        pass
                brain_done = time.monotonic()

        try:
            if tts_ready and hasattr(tts, "speak_text_stream"):
                agent.set_state(JarvisState.SPEAKING)
                tts.speak_text_stream(brain_chunks())
            else:
                for _chunk in brain_chunks():
                    pass
        except Exception as exc:
            if not barge_in_requested.is_set():
                print(f"[JARVIS] Stream voce/IA degradato: {exc}")
        finally:
            response_active.clear()

        if brain_done is None:
            brain_done = time.monotonic()
        reply = "".join(collected).strip()

        if barge_in_requested.is_set():
            print("[JARVIS] Risposta interrotta naturalmente dall'utente.")
            agent.set_state(JarvisState.IDLE)
            return reply

        if not reply:
            fallback = settings.listener_error_phrase.strip() or "Mi dispiace signore, non ho capito l'ultima parte."
            speak_text(fallback)
            return fallback

        presence.add(turn.text, speaker=turn.speaker_name)
        presence.add(reply, speaker="Jarvis")
        last_reply_at[0] = time.monotonic()
        print(f"JARVIS: {reply}")
        if first_token is not None:
            print(f"[LATENCY] cervello_primo_token={first_token - brain_started:.2f}s")
        print(f"[LATENCY] cervello_completo={brain_done - brain_started:.2f}s")
        agent.set_state(JarvisState.IDLE)
        return reply

    def maybe_proactive_alert() -> None:
        if not settings.proactive_enabled or response_active.is_set():
            return
        alert = proactive.pop()
        if alert is not None:
            print(f"[PROACTIVE] {alert.key}: {alert.message}")
            speak_text(alert.message)

    def serve_ui() -> None:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

    threading.Thread(target=serve_ui, daemon=True, name="jarvis-web").start()
    time.sleep(0.6)
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass

    if not mic.start():
        raise SystemExit(f"Microfono full-duplex non disponibile: {mic.last_error}")

    print("[JARVIS] Desktop realtime online.")
    print("[JARVIS] Conversazione continua FULL-DUPLEX: ON · parli direttamente, nessuna wake word.")
    print(f"[JARVIS] Voice: {voice_name} · {'READY' if tts_ready else 'PENDING'}")
    print(f"[JARVIS] Speaker profiles: {len(speakers.profile_names())} · auth={'ON' if settings.speaker_auth_enabled else 'OFF'}")
    print(f"[JARVIS] Memory: {'ON' if settings.memory_enabled else 'OFF'}")
    print(f"[JARVIS] Screen context: {'ON' if settings.screen_monitor_enabled else 'OFF'}")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        while True:
            audio = mic.get_utterance(timeout=0.20)
            if audio is None:
                maybe_proactive_alert()
                continue

            turn = decode_audio(audio)
            if turn is None:
                continue
            if not turn.authorized:
                speak_unauthorized()
                continue

            # In realtime mode "stop" is a natural interruption, not a switch
            # back to a dormant wake-word state. JARVIS stays present afterward.
            if is_stop_phrase(turn.text, settings.listener_stop_phrases):
                print("[JARVIS] Stop ricevuto · resto disponibile in silenzio.")
                continue

            context = presence.as_context() if settings.presence_enabled else ""
            seconds_since_reply = time.monotonic() - last_reply_at[0] if last_reply_at[0] else 9999.0
            addressed = True
            classifier = getattr(agent, "is_addressed_to_jarvis", None)
            if callable(classifier):
                try:
                    addressed = bool(
                        classifier(
                            turn.text,
                            ambient_context=context,
                            seconds_since_reply=seconds_since_reply,
                        )
                    )
                except Exception:
                    addressed = True

            if not addressed:
                presence.add(turn.text, speaker=turn.speaker_name)
                if getattr(agent, "memory", None):
                    try:
                        agent.memory.record_message(
                            turn.speaker_name,
                            turn.text,
                            {"speaker_role": turn.speaker_role, "addressed_to_jarvis": False},
                        )
                    except Exception:
                        pass
                print(f"[JARVIS] Conversazione ambientale ignorata: {turn.text}")
                continue

            answer_turn(turn, ambient_context=context)
            barge_in_requested.clear()

    except KeyboardInterrupt:
        pass
    finally:
        response_active.clear()
        try:
            if tts_ready:
                tts.stop()
        except Exception:
            pass
        mic.stop()
        proactive.stop()
        screen.stop()
        presence.clear()
        agent.close()


if __name__ == "__main__":
    main()
