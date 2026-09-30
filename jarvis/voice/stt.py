from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class STTResult:
    text: str
    language: str | None = None


class LocalSTT:
    """Lazy faster-whisper wrapper with microphone VAD-style recording.

    The module imports faster-whisper/sounddevice only when used so the normal
    FastAPI/React preview stays lightweight.
    """

    def __init__(
        self,
        model_name: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "it",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model: Any | None = None
        self._model_device: str | None = None
        self.abort_event = threading.Event()
        self.last_recording_heard_speech = False

    @staticmethod
    def dependency_status() -> dict[str, bool]:
        status: dict[str, bool] = {}
        for module in ("faster_whisper", "sounddevice", "numpy"):
            try:
                __import__(module)
                status[module] = True
            except Exception:
                status[module] = False
        return status

    def available(self) -> bool:
        return all(self.dependency_status().values())

    def _load_model(self, force_cpu: bool = False):
        if self._model is not None and not force_cpu:
            return self._model

        from faster_whisper import WhisperModel

        requested_device = "cpu" if force_cpu else self.device
        if requested_device == "auto":
            requested_device = "cuda"

        try:
            model = WhisperModel(
                self.model_name,
                device=requested_device,
                compute_type="int8" if force_cpu else self.compute_type,
            )
            self._model = model
            self._model_device = requested_device
        except Exception:
            if requested_device == "cpu":
                raise
            model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            self._model = model
            self._model_device = "cpu"
        return self._model

    def transcribe(self, audio, sample_rate: int = 16000) -> STTResult:
        del sample_rate  # faster-whisper accepts the 16 kHz float array directly.
        model = self._load_model()
        try:
            segments, info = model.transcribe(
                audio,
                beam_size=3,
                language=self.language or None,
                vad_filter=True,
            )
        except Exception:
            if self._model_device != "cpu":
                model = self._load_model(force_cpu=True)
                segments, info = model.transcribe(
                    audio,
                    beam_size=3,
                    language=self.language or None,
                    vad_filter=True,
                )
            else:
                raise
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected = getattr(info, "language", None)
        return STTResult(text=text, language=detected)

    def record_until_silence(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.010,
        speech_threshold: float = 0.014,
        silence_seconds: float = 1.0,
        max_seconds: float = 45.0,
        initial_silence_seconds: float | None = None,
    ):
        """Record one natural conversational turn.

        Recording starts immediately, ends after speech followed by a short
        silence, and can optionally time out if the user never begins speaking.
        `last_recording_heard_speech` lets callers leave an active conversation
        without wasting a Whisper pass on pure silence.
        """
        import numpy as np
        import sounddevice as sd

        self.abort_event.clear()
        self.last_recording_heard_speech = False
        chunk_seconds = 0.16
        chunk = int(sample_rate * chunk_seconds)
        silent_needed = max(1, int(silence_seconds / chunk_seconds))
        max_chunks = max(1, int(max_seconds / chunk_seconds))
        initial_chunks = None
        if initial_silence_seconds is not None:
            initial_chunks = max(1, int(max(0.2, initial_silence_seconds) / chunk_seconds))

        silent_chunks = 0
        heard_speech = False
        recording: list[Any] = []

        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32") as stream:
            for index in range(max_chunks):
                if self.abort_event.is_set():
                    break
                data, _overflowed = stream.read(chunk)
                flat = data.reshape(-1).copy()
                recording.append(flat)
                rms = float(np.sqrt(np.mean(np.square(flat)))) if flat.size else 0.0

                if rms >= speech_threshold:
                    heard_speech = True
                    self.last_recording_heard_speech = True
                    silent_chunks = 0
                elif heard_speech and rms < silence_threshold:
                    silent_chunks += 1

                if heard_speech and silent_chunks >= silent_needed:
                    break
                if not heard_speech and initial_chunks is not None and index + 1 >= initial_chunks:
                    break

        if not recording:
            return np.zeros(chunk, dtype=np.float32)
        return np.concatenate(recording).astype(np.float32, copy=False)

    def abort(self) -> None:
        self.abort_event.set()
