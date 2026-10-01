from __future__ import annotations

from .stt import LocalSTT as _BaseLocalSTT


class LocalSTT(_BaseLocalSTT):
    """STT tuned for natural conversational pauses.

    The previous 360 ms endpoint frequently cut a speaker at short thinking
    pauses. 520 ms stays responsive while being much less eager to end a turn.
    """

    def record_until_silence(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.00045,
        speech_threshold: float = 0.00090,
        silence_seconds: float = 0.52,
        max_seconds: float = 30.0,
        initial_silence_seconds: float | None = 6.0,
    ):
        return super().record_until_silence(
            sample_rate=sample_rate,
            silence_threshold=silence_threshold,
            speech_threshold=speech_threshold,
            silence_seconds=silence_seconds,
            max_seconds=max_seconds,
            initial_silence_seconds=initial_silence_seconds,
        )
