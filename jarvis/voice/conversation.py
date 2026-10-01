from __future__ import annotations

import queue
import re
import threading
import time

import numpy as np

from jarvis.core.events import EventBus, JarvisEvent
from jarvis.core.router import JarvisRouter
from jarvis.core.state import JarvisState


_MARKDOWN_RE = re.compile(r"(\*\*|__|\*|_|~~|\x60{1,3}|^\s*[-*•]\s+|^\s*#{1,6}\s+)", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|(?<=[;:])\s+")
_WS_RE = re.compile(r"\s+")


def clean_voice_text(text: str) -> str:
    text = str(text or "")
    text = _LINK_RE.sub(r"\1", text)
    text = text.replace("\x60\x60\x60", " ").replace("\n", " ")
    text = _MARKDOWN_RE.sub(" ", text)
    text = text.replace("•", " ")
    text = _WS_RE.sub(" ", text).strip()
    return text


def split_voice_sentences(text: str) -> list[str]:
    clean = clean_voice_text(text)
    if not clean:
        return []
    parts = _SENTENCE_RE.split(clean)
    return [part.strip(" -–—") for part in parts if part.strip(" -–—")]


def _speech_profile(audio, sample_rate: int = 16000) -> tuple[bool, float, float, float]:
    array = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not array.size:
        return False, 0.0, 0.0, 0.0012

    frame = max(320, int(sample_rate * 0.06))
    rms_values: list[float] = []
    for start in range(0, array.size, frame):
        chunk = array[start:start + frame]
        if chunk.size < frame // 2:
            continue
        rms_values.append(float(np.sqrt(np.mean(np.square(chunk)))))

    if not rms_values:
        return False, 0.0, 0.0, 0.0012

    peak = max(rms_values)
    noise = float(np.percentile(np.asarray(rms_values, dtype=np.float32), 30))
    threshold = max(0.0012, noise * 2.5)
    voiced = sum(value >= threshold for value in rms_values)
    return voiced >= 2 and peak >= threshold, peak, noise, threshold


class VoiceConversationEngine:
    def __init__(
        self,
        *,
        settings,
        stt,
        tts,
        tts_ready: bool,
        wake,
        agent,
        presence,
        router: JarvisRouter,
        event_bus: EventBus,
    ) -> None:
        self.settings = settings
        self.stt = stt
        self.tts = tts
        self.tts_ready = tts_ready
        self.wake = wake
        self.agent = agent
        self.presence = presence
        self.router = router
        self.event_bus = event_bus
        self.busy = threading.Event()
        self._turn_cancel = threading.Event()
        self._tts_thread: threading.Thread | None = None

    def is_busy(self) -> bool:
        return self.busy.is_set()

    def interrupt(self) -> None:
        self._turn_cancel.set()
        self.stt.abort()
        try:
            self.tts.stop()
        except Exception:
            pass
        self.agent.set_state(JarvisState.IDLE)
        self.busy.clear()

    def _capture(
        self,
        *,
        initial_silence_seconds: float,
        max_seconds: float,
        activation_audio=None,
        activation_has_speech: bool = False,
    ) -> str:
        self.agent.set_state(JarvisState.LISTENING)
        started = time.monotonic()
        audio = self.stt.record_until_silence(
            initial_silence_seconds=initial_silence_seconds,
            silence_seconds=0.24,
            speech_threshold=0.00090,
            silence_threshold=0.00050,
            max_seconds=max_seconds,
        )
        capture_seconds = time.monotonic() - started

        diagnostic = (
            f"max_rms={self.stt.last_recording_max_rms:.4f} "
            f"noise={self.stt.last_recording_noise_floor:.4f} "
            f"soglia_voce={self.stt.last_recording_speech_threshold:.4f} "
            f"release={self.stt.last_recording_release_threshold:.4f} "
            f"fine={self.stt.last_recording_end_reason or 'unknown'}"
        )

        if not self.stt.last_recording_heard_speech and not activation_has_speech:
            print(
                f"[STT] {diagnostic} speech=no capture={capture_seconds:.2f}s "
                "decode=saltata (nessuna voce)"
            )
            return ""

        pieces = []
        if activation_audio is not None and getattr(activation_audio, "size", 0):
            pieces.append(np.asarray(activation_audio, dtype=np.float32))
        if getattr(audio, "size", 0):
            pieces.append(np.asarray(audio, dtype=np.float32))

        if not pieces:
            print(f"[STT] {diagnostic} speech=no decode=saltata (audio vuoto)")
            return ""

        combined = pieces[0] if len(pieces) == 1 else np.concatenate(pieces)
        self.agent.set_state(JarvisState.THINKING)
        started = time.monotonic()
        result = self.stt.transcribe(combined)
        decode_seconds = time.monotonic() - started
        text = clean_voice_text(result.text.strip())

        print(
            f"[STT] {diagnostic} speech="
            f"{'si' if self.stt.last_recording_heard_speech else 'post-wake'} "
            f"capture={capture_seconds:.2f}s decode={decode_seconds:.2f}s"
        )
        return text

    def _speak_stream(self, sentence_queue: queue.Queue[str | None]) -> None:
        if not self.tts_ready:
            return

        def source():
            while not self._turn_cancel.is_set():
                sentence = sentence_queue.get()
                if sentence is None:
                    return
                if sentence.strip():
                    yield sentence

        try:
            stream_method = getattr(self.tts, "speak_stream", None)
            if callable(stream_method):
                stream_method(source())
            else:
                for sentence in source():
                    if self._turn_cancel.is_set():
                        break
                    self.tts.speak(sentence, streamed=True)
        except Exception as exc:
            print(f"[JARVIS] TTS non disponibile: {exc}")

    def _stream_general_reply(self, text: str, ambient_context: str) -> str:
        sentence_queue: queue.Queue[str | None] = queue.Queue(maxsize=4)
        self._turn_cancel.clear()
        self._tts_thread = threading.Thread(
            target=self._speak_stream,
            args=(sentence_queue,),
            daemon=True,
            name="jarvis-voice-tts",
        )
        self._tts_thread.start()

        full: list[str] = []
        pending = ""
        started = time.monotonic()

        try:
            for event in self.agent.process_message_stream(
                text,
                ambient_context=ambient_context,
            ):
                if self._turn_cancel.is_set():
                    break
                if event.get("type") != "delta":
                    continue

                delta = clean_voice_text(str(event.get("text") or ""))
                if not delta:
                    continue

                full.append(delta)
                pending += delta

                parts = split_voice_sentences(pending)
                if len(parts) > 1:
                    for sentence in parts[:-1]:
                        sentence_queue.put(sentence)
                    pending = parts[-1]

                if len(pending) >= 90:
                    sentence_queue.put(pending)
                    pending = ""

            if pending.strip() and not self._turn_cancel.is_set():
                sentence_queue.put(clean_voice_text(pending))

            sentence_queue.put(None)
            if self._tts_thread is not None:
                self._tts_thread.join(timeout=30)

            reply = clean_voice_text("".join(full))
            print(f"[LATENCY] risposta_stream={time.monotonic() - started:.2f}s")
            return reply
        except Exception:
            try:
                sentence_queue.put_nowait(None)
            except Exception:
                pass
            raise

    def _answer(self, text: str) -> str:
        print(f"TU: {text}")
        intent = self.router.classify(text)
        self.event_bus.emit(JarvisEvent("USER_COMMAND", {"text": text, "intent": intent}))
        print(f"[CORE] Intent rilevato: {intent}")

        context = self.presence.as_context() if self.settings.presence_enabled else ""
        started = time.monotonic()

        if intent == "general" and callable(getattr(self.agent, "process_message_stream", None)):
            reply = self._stream_general_reply(text, context)
        else:
            reply = clean_voice_text(
                self.agent.process_message(text, ambient_context=context)
            )
            if self.tts_ready and reply:
                self.agent.set_state(JarvisState.SPEAKING)
                self.tts.speak(reply, streamed=True)

        self.presence.add(text, speaker="utente")
        if reply:
            self.presence.add(reply, speaker="Jarvis")

        print(f"JARVIS: {reply}")
        print(f"[LATENCY] turno={time.monotonic() - started:.2f}s")
        return reply

    def handle_wake(self) -> None:
        if self.busy.is_set():
            self.interrupt()
            return

        self.busy.set()
        self._turn_cancel.clear()
        if self.wake.selected_device is not None:
            self.stt.input_device = self.wake.selected_device

        try:
            self.wake.pause()
            time.sleep(0.10)
            post = self.wake.post_wake_audio(seconds=0.34, exclude_head_seconds=0.12)
            continued, peak, noise, threshold = _speech_profile(post)

            print("[JARVIS] Ti ascolto...")
            if continued:
                print(
                    "[JARVIS] Comando continuo rilevato · "
                    f"peak={peak:.4f} noise={noise:.4f} soglia={threshold:.4f}"
                )
                text = self._capture(
                    initial_silence_seconds=0.45,
                    max_seconds=min(self.settings.listener_max_utterance_seconds, 16.0),
                    activation_audio=post,
                    activation_has_speech=True,
                )
            else:
                print(
                    "[JARVIS] Wake isolata · "
                    f"peak={peak:.4f} noise={noise:.4f} soglia={threshold:.4f}"
                )
                if self.settings.listener_wake_ack_enabled and self.tts_ready:
                    self.tts.speak("Sì?", streamed=True)
                print("[JARVIS] In ascolto del comando...")
                text = self._capture(
                    initial_silence_seconds=2.2,
                    max_seconds=min(self.settings.listener_max_utterance_seconds, 16.0),
                )

            if not text:
                print("[JARVIS] Nessun comando rilevato.")
                return

            self._answer(text)

            while not self.stt.abort_event.is_set() and not self._turn_cancel.is_set():
                print("[JARVIS] Conversazione attiva · ascolto...")
                followup = self._capture(
                    initial_silence_seconds=min(
                        self.settings.listener_followup_silence_seconds, 4.0
                    ),
                    max_seconds=min(self.settings.listener_max_utterance_seconds, 20.0),
                )
                if not followup:
                    print("[JARVIS] Standby.")
                    break

                normalized = followup.casefold().strip(" .,!?:;")
                stop_phrases = {
                    item.casefold().strip(" .,!?:;")
                    for item in self.settings.listener_stop_phrases.split("|")
                    if item.strip()
                }
                if normalized in stop_phrases:
                    print("[JARVIS] Standby richiesto.")
                    break

                self._answer(followup)
        except Exception as exc:
            self.agent.set_state(JarvisState.ERROR)
            print(f"[JARVIS] Errore voce: {exc}")
        finally:
            self.wake.resume()
            if self.agent.state is not JarvisState.ERROR:
                self.agent.set_state(JarvisState.IDLE)
            self.busy.clear()
            self._turn_cancel.clear()

    def run(self) -> None:
        self.wake.run(
            self.handle_wake,
            busy=self.busy.is_set,
            interrupt=self.interrupt,
        )
