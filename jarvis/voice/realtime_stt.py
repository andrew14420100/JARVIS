from __future__ import annotations

import base64
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class STTResult:
    text: str
    language: str | None = None


class NvidiaRealtimeSTT:
    """Low-latency local ASR client for NVIDIA NeMo-Speech.cpp.

    The microphone remains local. Audio is streamed as PCM16 to the local
    NeMo-Speech.cpp process, which runs NVIDIA Nemotron 3.5 ASR on the GPU.
    The client owns turn detection so idle silence is never streamed for long.
    """

    def __init__(
        self,
        *,
        http_url: str = "http://127.0.0.1:8080",
        websocket_url: str = "ws://127.0.0.1:8080/v1/audio/transcriptions/realtime",
        language: str = "it-IT",
        input_device: str | int | None = None,
        endpointing_ms: int = 420,
    ) -> None:
        self.http_url = http_url.rstrip("/")
        self.websocket_url = websocket_url
        self.language = language or "it-IT"
        self.input_device = input_device
        self.endpointing_ms = max(200, int(endpointing_ms))

        self.abort_event = threading.Event()
        self.last_recording_heard_speech = False
        self.last_recording_max_rms = 0.0
        self.last_recording_speech_threshold = 0.0
        self.last_recording_noise_floor = 0.0
        self.last_recording_release_threshold = 0.0
        self.last_recording_gain = 1.0
        self.last_recording_end_reason = ""

        self._last_result = STTResult("")
        self._warm = False
        self._last_partial = ""
        self._lock = threading.RLock()

    @staticmethod
    def dependency_status() -> dict[str, bool]:
        status: dict[str, bool] = {}
        for module in ("sounddevice", "numpy", "websockets"):
            try:
                __import__(module)
                status[module] = True
            except Exception:
                status[module] = False
        return status

    def available(self) -> bool:
        if not all(self.dependency_status().values()):
            return False
        try:
            response = httpx.get(f"{self.http_url}/ready", timeout=1.2)
            return response.status_code == 200
        except Exception:
            return False

    def dependency_error(self) -> str:
        missing = [name for name, ok in self.dependency_status().items() if not ok]
        if missing:
            return "Moduli mancanti: " + ", ".join(missing)
        if not self.available():
            return (
                f"NVIDIA NeMo-Speech.cpp non pronto su {self.http_url}. "
                "Avvia start-nvidia-asr.ps1."
            )
        return ""

    def warmup(self) -> tuple[str, float]:
        started = time.monotonic()
        response = httpx.get(f"{self.http_url}/ready", timeout=2.0)
        response.raise_for_status()
        self._warm = True
        return "cuda", time.monotonic() - started

    def abort(self) -> None:
        self.abort_event.set()

    def transcribe(self, audio, sample_rate: int = 16000) -> STTResult:
        del audio, sample_rate
        with self._lock:
            return self._last_result

    @staticmethod
    def _speech_profile(
        rms_values: list[float],
        *,
        base_speech_threshold: float,
        base_release_threshold: float,
    ) -> tuple[float, float, float]:
        import numpy as np

        if not rms_values:
            return 0.0, float(base_speech_threshold), float(base_release_threshold)

        noise = float(np.percentile(np.asarray(rms_values, dtype=np.float32), 45))
        speech = max(float(base_speech_threshold), 0.0010, noise * 2.2)
        release = max(float(base_release_threshold), 0.00055, speech * 0.48)
        return noise, speech, release

    def record_until_silence(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.00045,
        speech_threshold: float = 0.00090,
        silence_seconds: float = 0.30,
        max_seconds: float = 30.0,
        initial_silence_seconds: float | None = 3.0,
        activation_audio=None,
    ):
        import numpy as np
        import sounddevice as sd
        from websockets.sync.client import connect

        self.abort_event.clear()
        self.last_recording_heard_speech = False
        self.last_recording_max_rms = 0.0
        self.last_recording_speech_threshold = float(speech_threshold)
        self.last_recording_noise_floor = 0.0
        self.last_recording_release_threshold = float(silence_threshold)
        self.last_recording_gain = 1.0
        self.last_recording_end_reason = ""
        self._last_result = STTResult("")
        self._last_partial = ""

        chunk_seconds = 0.08
        chunk = int(sample_rate * chunk_seconds)
        silent_needed = max(1, int(silence_seconds / chunk_seconds))
        max_chunks = max(1, int(max_seconds / chunk_seconds))
        initial_chunks = None
        if initial_silence_seconds is not None:
            initial_chunks = max(1, int(max(0.2, initial_silence_seconds) / chunk_seconds))

        audio_chunks: list[Any] = []
        pre_roll: deque[Any] = deque(maxlen=3)
        noise_samples: list[float] = []
        heard_speech = False
        silent_chunks = 0.0
        final_event = threading.Event()
        receiver_error: list[Exception] = []
        final_text: list[str] = []
        final_language: list[str | None] = []

        ws = connect(
            self.websocket_url,
            open_timeout=3.0,
            close_timeout=1.0,
            ping_interval=15.0,
            ping_timeout=8.0,
            max_size=4 * 1024 * 1024,
        )

        try:
            # Session configuration is sent before any audio, as required by
            # NeMo-Speech.cpp's realtime transcription protocol.
            ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "sample_rate": sample_rate,
                    "language": self.language,
                    "automatic_punctuation": True,
                    "verbatim": False,
                    "endpointing_ms": self.endpointing_ms,
                },
            }))

            def receive_events() -> None:
                try:
                    for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        try:
                            event = json.loads(raw)
                        except Exception:
                            continue

                        event_type = str(event.get("type") or "")
                        if event_type == "conversation.item.input_audio_transcription.delta":
                            delta = str(event.get("delta") or "")
                            if delta:
                                self._last_partial += delta
                        elif event_type == "conversation.item.input_audio_transcription.completed":
                            text = str(event.get("transcript") or "").strip()
                            if text:
                                final_text[:] = [text]
                            language = event.get("language")
                            final_language[:] = [str(language) if language else None]
                            final_event.set()
                        elif event_type == "error":
                            message = event.get("error")
                            receiver_error.append(RuntimeError(str(message or event)))
                            final_event.set()
                except Exception as exc:
                    if not self.abort_event.is_set():
                        receiver_error.append(exc)
                        final_event.set()

            receiver = threading.Thread(
                target=receive_events,
                daemon=True,
                name="jarvis-nvidia-asr-recv",
            )
            receiver.start()

            def send_pcm(flat: Any) -> None:
                pcm16 = np.clip(flat * 32768.0, -32768, 32767).astype(np.int16)
                ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm16.tobytes()).decode("ascii"),
                }))

            # Fast-path audio captured by the wake listener. It is sent before
            # opening the command microphone so a one-breath "Hey Jarvis,
            # controlla..." command keeps its first words.
            if activation_audio is not None and getattr(activation_audio, "size", 0):
                activation = np.asarray(activation_audio, dtype=np.float32).reshape(-1)
                activation_chunk = max(320, int(sample_rate * 0.08))
                activation_peak = float(np.max(np.abs(activation))) if activation.size else 0.0
                if activation_peak >= 0.003:
                    heard_speech = True
                    self.last_recording_heard_speech = True
                    for start in range(0, activation.size, activation_chunk):
                        part = activation[start:start + activation_chunk]
                        if part.size:
                            send_pcm(part)
                            audio_chunks.append(part)

            stream_kwargs: dict[str, Any] = {
                "samplerate": sample_rate,
                "channels": 1,
                "dtype": "int16",
                "blocksize": chunk,
            }
            if self.input_device not in (None, ""):
                stream_kwargs["device"] = self.input_device

            with sd.RawInputStream(**stream_kwargs) as stream:
                for index in range(max_chunks):
                    if self.abort_event.is_set():
                        self.last_recording_end_reason = "abort"
                        break

                    data, _overflowed = stream.read(chunk)
                    pcm = np.frombuffer(data, dtype=np.int16).copy()
                    flat = pcm.astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(np.square(flat)))) if flat.size else 0.0
                    self.last_recording_max_rms = max(self.last_recording_max_rms, rms)

                    noise_floor, adaptive_speech, adaptive_release = self._speech_profile(
                        noise_samples,
                        base_speech_threshold=speech_threshold,
                        base_release_threshold=silence_threshold,
                    )
                    self.last_recording_noise_floor = noise_floor
                    self.last_recording_speech_threshold = adaptive_speech
                    self.last_recording_release_threshold = adaptive_release

                    if not heard_speech:
                        if rms >= adaptive_speech:
                            heard_speech = True
                            self.last_recording_heard_speech = True
                            audio_chunks.extend(list(pre_roll))
                            audio_chunks.append(flat)
                            for item in list(pre_roll):
                                send_pcm(item)
                            send_pcm(flat)
                            pre_roll.clear()
                            silent_chunks = 0.0
                        else:
                            pre_roll.append(flat)
                            noise_samples.append(rms)
                            if len(noise_samples) > 30:
                                noise_samples.pop(0)
                            if (
                                not activation_audio
                                and initial_chunks is not None
                                and index + 1 >= initial_chunks
                            ):
                                self.last_recording_end_reason = "initial-timeout"
                                break
                    else:
                        audio_chunks.append(flat)
                        send_pcm(flat)

                        if rms >= adaptive_speech:
                            silent_chunks = 0.0
                        elif rms <= adaptive_release:
                            silent_chunks += 1.0
                        else:
                            silent_chunks += 0.50

                        if silent_chunks >= silent_needed:
                            self.last_recording_end_reason = "silence"
                            break

            if not heard_speech:
                self.last_recording_end_reason = self.last_recording_end_reason or "initial-timeout"
                return np.zeros(0, dtype=np.float32)

            ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            final_event.wait(timeout=4.0)

            if receiver_error:
                raise receiver_error[0]

            text = final_text[0] if final_text else self._last_partial.strip()
            language = final_language[0] if final_language else self.language
            with self._lock:
                self._last_result = STTResult(text=text, language=language)

            if not self.last_recording_end_reason:
                self.last_recording_end_reason = "commit"

            if audio_chunks:
                return np.concatenate(audio_chunks).astype(np.float32, copy=False)
            return np.zeros(0, dtype=np.float32)

        finally:
            try:
                ws.close()
            except Exception:
                pass
