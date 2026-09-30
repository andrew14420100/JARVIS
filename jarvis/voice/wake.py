from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any


class WakeWordListener:
    """Continuous local wake-word listener using openWakeWord.

    While STT owns the microphone, the wake stream is closed completely. This
    is important on Windows devices that do not reliably deliver audio to two
    simultaneous input streams.

    The listener also keeps a short in-memory ring buffer of recent PCM audio.
    This makes it possible to reconstruct conversational context *before* the
    wake phrase without persisting ambient audio to disk.
    """

    def __init__(
        self,
        model_name: str = "hey_jarvis",
        threshold: float = 0.50,
        chunk_size: int = 1280,
        sample_rate: int = 16000,
        context_seconds: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate
        self.context_seconds = max(2.0, context_seconds)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._stream_released = threading.Event()
        self._stream_released.set()
        self._audio_lock = threading.RLock()
        chunks = max(1, int((self.context_seconds * self.sample_rate) / self.chunk_size))
        self._recent_pcm: deque[Any] = deque(maxlen=chunks)

    @staticmethod
    def dependency_status() -> dict[str, bool]:
        status: dict[str, bool] = {}
        for module in ("openwakeword", "sounddevice", "numpy"):
            try:
                __import__(module)
                status[module] = True
            except Exception:
                status[module] = False
        return status

    def available(self) -> bool:
        return all(self.dependency_status().values())

    def pause(self) -> None:
        self._pause.set()
        # Wait for the RawInputStream context to close before STT opens the same
        # Windows microphone. The stream reads 80 ms chunks, so one second is
        # ample without adding noticeable latency in the normal path.
        self._stream_released.wait(timeout=1.0)

    def resume(self) -> None:
        self._pause.clear()

    def stop(self) -> None:
        self._stop.set()
        self._pause.clear()

    def reset(self) -> None:
        self._stop.clear()
        self._pause.clear()
        self._stream_released.set()

    def clear_recent_audio(self) -> None:
        with self._audio_lock:
            self._recent_pcm.clear()

    def recent_audio(self, seconds: float | None = None, *, exclude_tail_seconds: float = 0.8):
        """Return recent ambient audio as float32 mono samples in [-1, 1]."""
        import numpy as np

        with self._audio_lock:
            chunks = [chunk.copy() for chunk in self._recent_pcm]
        if not chunks:
            return np.zeros(0, dtype=np.float32)

        audio = np.concatenate(chunks).astype(np.float32) / 32768.0
        max_seconds = self.context_seconds if seconds is None else max(0.0, min(seconds, self.context_seconds))
        max_samples = int(max_seconds * self.sample_rate)
        if max_samples > 0 and audio.size > max_samples:
            audio = audio[-max_samples:]

        trim = int(max(0.0, exclude_tail_seconds) * self.sample_rate)
        if trim and audio.size > trim:
            audio = audio[:-trim]
        elif trim:
            return np.zeros(0, dtype=np.float32)
        return audio

    def _prediction_score(self, predictions: dict[str, Any]) -> tuple[str, float]:
        """Resolve openWakeWord's versioned prediction key safely."""
        if not predictions:
            return self.model_name, 0.0

        wanted = self.model_name.lower().replace(".onnx", "").replace(".tflite", "")
        matches: list[tuple[str, float]] = []
        for key, value in predictions.items():
            normalized = str(key).lower().replace(".onnx", "").replace(".tflite", "")
            if wanted == normalized or wanted in normalized or normalized in wanted:
                try:
                    matches.append((str(key), float(value)))
                except (TypeError, ValueError):
                    continue

        if not matches:
            if len(predictions) == 1:
                key, value = next(iter(predictions.items()))
                try:
                    return str(key), float(value)
                except (TypeError, ValueError):
                    return str(key), 0.0
            return self.model_name, 0.0

        return max(matches, key=lambda item: item[1])

    def run(
        self,
        callback: Callable[[], None],
        busy: Callable[[], bool] | None = None,
        interrupt: Callable[[], None] | None = None,
    ) -> None:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model

        self.reset()
        model = Model(wakeword_models=[self.model_name], inference_framework="onnx")
        cooldown_until = 0.0
        callback_lock = threading.Lock()
        prediction_key_reported = False
        last_candidate_log = 0.0

        soft_threshold = max(0.12, min(0.18, self.threshold * 0.45))
        speech_rms_gate = 0.008

        try:
            default_input = sd.query_devices(kind="input")
            if default_input:
                print(
                    "[JARVIS] Microfono: "
                    f"{default_input.get('name', 'input predefinito')} · "
                    f"{default_input.get('default_samplerate', self.sample_rate):.0f} Hz"
                )
        except Exception as exc:
            print(f"[JARVIS] Microfono predefinito non identificato: {exc}")

        while not self._stop.is_set():
            if self._pause.is_set():
                self._stream_released.set()
                time.sleep(0.02)
                continue

            self._stream_released.clear()
            try:
                with sd.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.chunk_size,
                    channels=1,
                    dtype="int16",
                ) as stream:
                    while not self._stop.is_set() and not self._pause.is_set():
                        data, overflowed = stream.read(self.chunk_size)
                        if overflowed:
                            continue
                        pcm = np.frombuffer(data, dtype=np.int16).copy()
                        with self._audio_lock:
                            self._recent_pcm.append(pcm)

                        predictions = model.predict(pcm)
                        prediction_key, score = self._prediction_score(predictions)
                        pcm_float = pcm.astype(np.float32) / 32768.0
                        rms = float(np.sqrt(np.mean(np.square(pcm_float)))) if pcm_float.size else 0.0

                        if not prediction_key_reported:
                            print(
                                f"[JARVIS] Wake detector: {prediction_key} · "
                                f"soglia {self.threshold:.2f} · soft {soft_threshold:.3f} con voce"
                            )
                            prediction_key_reported = True

                        now = time.monotonic()
                        diagnostic_floor = min(0.20, max(0.08, soft_threshold * 0.75))
                        if score >= diagnostic_floor and now - last_candidate_log >= 0.6:
                            print(f"[WAKE] {prediction_key} score={score:.3f} rms={rms:.4f}")
                            last_candidate_log = now

                        hard_match = score >= self.threshold
                        soft_match = score >= soft_threshold and rms >= speech_rms_gate
                        if not (hard_match or soft_match):
                            continue

                        model.reset()
                        if now < cooldown_until:
                            continue

                        mode = "hard" if hard_match else "soft"
                        print(
                            f"[JARVIS] Wake word rilevata · {prediction_key} "
                            f"score={score:.3f} rms={rms:.4f} mode={mode}"
                        )

                        if busy and busy():
                            cooldown_until = now + 2.0
                            if interrupt:
                                interrupt()
                            continue

                        if callback_lock.locked():
                            continue
                        cooldown_until = now + 1.5

                        def invoke() -> None:
                            with callback_lock:
                                callback()

                        threading.Thread(
                            target=invoke,
                            daemon=True,
                            name="jarvis-wake-callback",
                        ).start()
            finally:
                # Leaving the stream context here truly releases the input
                # device, allowing STT to open it exclusively on Windows.
                self._stream_released.set()

            if self._pause.is_set():
                while self._pause.is_set() and not self._stop.is_set():
                    time.sleep(0.02)
