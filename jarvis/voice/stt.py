from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class STTResult:
    text: str
    language: str | None = None


class LocalSTT:
    """Low-latency faster-whisper microphone engine.

    The model is kept warm on CUDA. Endpoint detection happens before decode,
    so Whisper receives only the spoken turn instead of a long silence window.
    """

    def __init__(
        self,
        model_name: str = "turbo",
        device: str = "auto",
        compute_type: str = "float16",
        language: str = "it",
        input_device: str | int | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.input_device = input_device
        self._model: Any | None = None
        self._model_device: str | None = None
        self._warm = False
        self.abort_event = threading.Event()
        self.last_recording_heard_speech = False
        self.last_recording_max_rms = 0.0
        self.last_recording_speech_threshold = 0.0
        self.last_recording_noise_floor = 0.0
        self.last_recording_release_threshold = 0.0
        self.last_recording_gain = 1.0
        self.last_recording_end_reason = ""

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
            compute_type = "int8" if force_cpu else self.compute_type
            model = WhisperModel(
                self.model_name,
                device=requested_device,
                compute_type=compute_type,
                cpu_threads=4,
                num_workers=1,
            )
            self._model = model
            self._model_device = requested_device
        except Exception:
            if requested_device == "cpu":
                raise
            print(
                f"[STT] Modello {self.model_name!r} non disponibile su CUDA; "
                "provo lo stesso modello su CPU."
            )
            model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
                num_workers=1,
            )
            self._model = model
            self._model_device = "cpu"
        return self._model

    def _transcribe_once(self, model, audio, *, beam_size: int = 1):
        """Decode only text; no timestamps, beam search or temperature fallback."""
        segments, info = model.transcribe(
            audio,
            beam_size=beam_size,
            best_of=1,
            language=self.language or None,
            task="transcribe",
            temperature=0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
            word_timestamps=False,
            vad_filter=False,
            suppress_blank=True,
            max_new_tokens=128,
        )
        segments = list(segments)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected = getattr(info, "language", None)
        return STTResult(text=text, language=detected)

    def warmup(self) -> tuple[str, float]:
        if self._warm:
            return self._model_device or "unknown", 0.0

        import numpy as np

        started = time.monotonic()
        model = self._load_model()
        probe = np.zeros(3200, dtype=np.float32)
        try:
            self._transcribe_once(model, probe, beam_size=1)
        except Exception as exc:
            if self._model_device != "cpu":
                print(f"[STT] Warm-up GPU non disponibile ({exc}); fallback CPU.")
                model = self._load_model(force_cpu=True)
                self._transcribe_once(model, probe, beam_size=1)
            else:
                raise

        self._warm = True
        return self._model_device or "unknown", time.monotonic() - started

    def _normalize_audio(self, audio):
        import numpy as np

        array = np.asarray(audio, dtype=np.float32)
        if not array.size:
            self.last_recording_gain = 1.0
            return array

        peak = float(np.max(np.abs(array)))
        if peak <= 1e-6:
            self.last_recording_gain = 1.0
            return array

        # Normalize quiet microphones without amplifying room silence to a
        # level where Whisper starts hallucinating.
        target_peak = 0.22
        gain = min(12.0, max(1.0, target_peak / peak))
        self.last_recording_gain = gain
        if gain <= 1.01:
            return array
        return np.clip(array * gain, -1.0, 1.0).astype(np.float32, copy=False)

    def transcribe(self, audio, sample_rate: int = 16000) -> STTResult:
        del sample_rate
        normalized = self._normalize_audio(audio)
        if getattr(normalized, "size", 0) == 0:
            return STTResult(text="", language=self.language or None)

        model = self._load_model()
        try:
            return self._transcribe_once(model, normalized, beam_size=1)
        except Exception as exc:
            if self._model_device != "cpu":
                print(f"[STT] GPU non disponibile ({exc}); fallback CPU.")
                model = self._load_model(force_cpu=True)
                self._warm = True
                return self._transcribe_once(model, normalized, beam_size=1)
            raise

    def record_until_silence(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.00045,
        speech_threshold: float = 0.00075,
        silence_seconds: float = 0.28,
        max_seconds: float = 30.0,
        initial_silence_seconds: float | None = 2.0,
    ):
        """Capture one spoken turn with fast adaptive endpoint detection."""
        import numpy as np
        import sounddevice as sd

        self.abort_event.clear()
        self.last_recording_heard_speech = False
        self.last_recording_max_rms = 0.0
        self.last_recording_speech_threshold = float(speech_threshold)
        self.last_recording_noise_floor = 0.0
        self.last_recording_release_threshold = float(silence_threshold)
        self.last_recording_gain = 1.0
        self.last_recording_end_reason = ""

        chunk_seconds = 0.06
        chunk = int(sample_rate * chunk_seconds)
        silent_needed = max(1, int(np.ceil(silence_seconds / chunk_seconds)))
        max_chunks = max(1, int(max_seconds / chunk_seconds))
        initial_chunks = None
        if initial_silence_seconds is not None:
            initial_chunks = max(
                1,
                int(max(0.15, initial_silence_seconds) / chunk_seconds),
            )

        silent_chunks = 0.0
        heard_speech = False
        recording: list[Any] = []
        pre_roll: deque[Any] = deque(maxlen=2)
        noise_samples: list[float] = []
        frozen_speech_threshold = float(speech_threshold)
        frozen_release_threshold = float(silence_threshold)

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

                if not heard_speech:
                    noise_floor = (
                        float(np.percentile(np.asarray(noise_samples, dtype=np.float32), 45))
                        if noise_samples
                        else 0.0
                    )
                    adaptive_speech = max(
                        float(speech_threshold),
                        0.00075,
                        noise_floor * 2.10,
                    )
                    self.last_recording_noise_floor = noise_floor
                    self.last_recording_speech_threshold = adaptive_speech

                    if rms >= adaptive_speech:
                        heard_speech = True
                        self.last_recording_heard_speech = True
                        frozen_speech_threshold = adaptive_speech
                        frozen_release_threshold = max(
                            float(silence_threshold),
                            0.00045,
                            noise_floor * 1.55,
                            adaptive_speech * 0.45,
                        )
                        self.last_recording_release_threshold = frozen_release_threshold
                        recording.extend(pre_roll)
                        recording.append(flat)
                        pre_roll.clear()
                        silent_chunks = 0.0
                    else:
                        pre_roll.append(flat)
                        noise_samples.append(rms)
                        if len(noise_samples) > 30:
                            noise_samples.pop(0)
                else:
                    recording.append(flat)
                    if rms >= frozen_speech_threshold:
                        silent_chunks = 0.0
                    elif rms <= frozen_release_threshold:
                        silent_chunks += 1.0
                    else:
                        silent_chunks += 0.50

                    if silent_chunks >= silent_needed:
                        self.last_recording_end_reason = "silence"
                        break

                if (
                    not heard_speech
                    and initial_chunks is not None
                    and index + 1 >= initial_chunks
                ):
                    self.last_recording_end_reason = "initial-timeout"
                    break
            else:
                self.last_recording_end_reason = "max-timeout"

        if not heard_speech or not recording:
            return np.zeros(0, dtype=np.float32)

        return np.concatenate(recording).astype(np.float32, copy=False)

    def abort(self) -> None:
        self.abort_event.set()
