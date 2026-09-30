from __future__ import annotations

import asyncio
from dataclasses import dataclass


class EdgeTTSError(RuntimeError):
    pass


@dataclass(slots=True)
class EdgeAudio:
    data: bytes
    media_type: str = "audio/mpeg"
    provider: str = "edge-neural-tts"


class EdgeCloudTTS:
    """No-key online neural TTS fallback based on the Edge speech service."""

    def __init__(
        self,
        *,
        voice: str = "it-IT-GiuseppeMultilingualNeural",
        rate: str = "-8%",
        pitch: str = "-6Hz",
        volume: str = "+0%",
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume

    async def _synthesize_async(self, text: str) -> EdgeAudio:
        try:
            import edge_tts
        except ImportError as exc:  # pragma: no cover - deployment configuration
            raise EdgeTTSError("edge-tts non è installato nel backend.") from exc

        clean = " ".join(str(text or "").strip().split())
        if not clean:
            raise EdgeTTSError("Testo vuoto.")
        if len(clean) > 1800:
            clean = clean[:1800].rsplit(" ", 1)[0] + "…"

        try:
            communicate = edge_tts.Communicate(
                clean,
                self.voice,
                rate=self.rate,
                volume=self.volume,
                pitch=self.pitch,
            )
            chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
        except Exception as exc:  # pragma: no cover - remote service dependent
            raise EdgeTTSError(f"Edge Neural TTS non disponibile: {exc}") from exc

        audio = b"".join(chunks)
        if not audio:
            raise EdgeTTSError("Edge Neural TTS non ha restituito audio.")
        return EdgeAudio(audio)

    def synthesize(self, text: str) -> EdgeAudio:
        try:
            return asyncio.run(self._synthesize_async(text))
        except RuntimeError as exc:
            # FastAPI executes sync endpoints in a worker thread, so normally
            # there is no running loop. Keep a clear error if this assumption
            # ever changes in a future runtime.
            raise EdgeTTSError(f"Impossibile avviare il fallback vocale: {exc}") from exc

    def status(self) -> dict[str, object]:
        return {
            "provider": "edge-neural-tts",
            "voice": self.voice,
            "remote": True,
            "requires_api_key": False,
            "requires_local_gpu": False,
        }
