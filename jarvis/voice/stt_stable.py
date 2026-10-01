from __future__ import annotations

from .stt import LocalSTT as _BaseLocalSTT


class LocalSTT(_BaseLocalSTT):
    """STT tuned for quick but natural conversational endpointing."""

    def __init__(self, *args, endpoint_silence_seconds: float = 0.42, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.endpoint_silence_seconds = max(0.28, min(1.2, float(endpoint_silence_seconds)))

    def record_until_silence(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.00045,
        speech_threshold: float = 0.00090,
        silence_seconds: float | None = None,
        max_seconds: float = 30.0,
        initial_silence_seconds: float | None = 6.0,
    ):
        effective_silence = (
            self.endpoint_silence_seconds
            if silence_seconds is None
            else max(0.28, min(1.2, float(silence_seconds)))
        )
        return super().record_until_silence(
            sample_rate=sample_rate,
            silence_threshold=silence_threshold,
            speech_threshold=speech_threshold,
            silence_seconds=effective_silence,
            max_seconds=max_seconds,
            initial_silence_seconds=initial_silence_seconds,
        )
