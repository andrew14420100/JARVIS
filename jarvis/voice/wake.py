from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any


class WakeWordListener:
    """Continuous local wake-word listener using openWakeWord.

    `pause()` is used while STT owns the microphone, preventing two audio
    streams from fighting for the same Windows input device.

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

    def resume(self) -> None:
        self._pause.clear()

    def stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        self._stop.clear()
        self._pause.clear()

    def clear_recent_audio(self) -> None:
        with self._audio_lock:
            self._recent_pcm.clear()

    def recent_audio(self, seconds: float | None = None, *, exclude_tail_seconds: float = 0.8):
        """Return recent ambient audio as float32 mono samples in [-1, 1].

        Audio is held only in RAM. `exclude_tail_seconds` removes the wake-word
        tail so the ambient transcript is less likely to duplicate "Hey Jarvis".
        """
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

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            channels=1,
            dtype="int16",
        ) as stream:
            while not self._stop.is_set():
                if self._pause.is_set():
                    time.sleep(0.05)
                    continue

                data, overflowed = stream.read(self.chunk_size)
                if overflowed:
                    continue
                pcm = np.frombuffer(data, dtype=np.int16).copy()
                with self._audio_lock:
                    self._recent_pcm.append(pcm)

                predictions = model.predict(pcm)
                score = float(predictions.get(self.model_name, 0.0))
                if score < self.threshold:
                    continue

                model.reset()
                now = time.monotonic()
                if now < cooldown_until:
                    continue

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

                threading.Thread(target=invoke, daemon=True, name="jarvis-wake-callback").start()
