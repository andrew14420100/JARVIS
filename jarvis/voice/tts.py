from __future__ import annotations

import re
import threading
from typing import Any


class LocalTTS:
    """Lazy local Kokoro TTS wrapper.

    The engine is optional and only loaded on a local desktop machine. This
    keeps the Emergent preview/backend independent from Torch/Kokoro.
    """

    def __init__(
        self,
        voice: str = "af_heart",
        speed: float = 1.05,
        lang_code: str = "a",
        sample_rate: int = 24000,
    ) -> None:
        self.voice = voice
        self.speed = speed
        self.lang_code = lang_code
        self.sample_rate = sample_rate
        self._pipeline: Any | None = None
        self._speaking = threading.Event()
        self._interrupt = threading.Event()

    @staticmethod
    def dependency_status() -> dict[str, bool]:
        status: dict[str, bool] = {}
        for module in ("kokoro", "sounddevice", "numpy"):
            try:
                __import__(module)
                status[module] = True
            except Exception:
                status[module] = False
        return status

    def available(self) -> bool:
        return all(self.dependency_status().values())

    def _get_pipeline(self):
        if self._pipeline is None:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code=self.lang_code)
        return self._pipeline

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def stop(self) -> None:
        self._interrupt.set()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        self._speaking.clear()

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]

    def _synthesize(self, text: str):
        import numpy as np

        pipeline = self._get_pipeline()
        chunks = []
        for _graphemes, _phonemes, audio in pipeline(text, voice=self.voice, speed=self.speed):
            if self._interrupt.is_set():
                break
            if audio is not None:
                chunks.append(audio)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def speak(self, text: str, streamed: bool = True) -> None:
        if not text or not text.strip():
            return

        import sounddevice as sd

        self._interrupt.clear()
        segments = self._sentences(text) if streamed else [text.strip()]
        self._speaking.set()
        try:
            for sentence in segments:
                if self._interrupt.is_set():
                    break
                audio = self._synthesize(sentence)
                if audio.size == 0 or self._interrupt.is_set():
                    continue
                sd.play(audio, samplerate=self.sample_rate)
                while True:
                    stream = sd.get_stream()
                    if not stream or not stream.active:
                        break
                    if self._interrupt.wait(0.05):
                        sd.stop()
                        break
        finally:
            try:
                sd.stop()
            except Exception:
                pass
            self._speaking.clear()
            self._interrupt.clear()
