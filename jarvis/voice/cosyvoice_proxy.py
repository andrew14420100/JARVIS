from __future__ import annotations

from dataclasses import dataclass
import io
import queue
import re
import threading
import time
import wave
from typing import Iterator

import httpx


class CosyVoiceProxyError(RuntimeError):
    pass


@dataclass(slots=True)
class CosyVoiceAudio:
    data: bytes
    media_type: str = "audio/wav"
    provider: str = "cosyvoice3-emergent"


class CosyVoiceProxyTTS:
    """Client for the warm CosyVoice 3 service running beside JARVIS.

    CosyVoice can emit streaming PCM with irregular generation cadence. Writing
    each generated chunk directly to PortAudio makes audible gaps whenever the
    model momentarily generates slower than real time. Desktop speech therefore
    buffers complete short speech segments and pipelines generation of the next
    segment while the current one is being played. This preserves a responsive
    first utterance without starving the audio device between inference chunks.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._interrupt = threading.Event()
        self._speaking = threading.Event()
        self._active_response: httpx.Response | None = None
        self._sample_rate = 24000

    def _health(self) -> dict[str, object]:
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=1.5)
            response.raise_for_status()
            data = response.json()
            rate = int(data.get("sample_rate") or 24000)
            if rate > 0:
                self._sample_rate = rate
            return data
        except Exception as exc:
            raise CosyVoiceProxyError(f"CosyVoice locale non raggiungibile: {exc}") from exc

    def available(self) -> bool:
        try:
            data = self._health()
            return bool(data.get("ok"))
        except Exception:
            return False

    def dependency_status(self) -> dict[str, bool]:
        return {
            "cosyvoice_service": self.available(),
            "sounddevice": self._module_available("sounddevice"),
            "numpy": self._module_available("numpy"),
        }

    @staticmethod
    def _module_available(name: str) -> bool:
        try:
            __import__(name)
            return True
        except Exception:
            return False

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def status(self) -> dict[str, object]:
        data: dict[str, object] = {
            "enabled": True,
            "provider": "cosyvoice3-local",
            "remote": False,
            "runs_on": "local",
            "requires_api_key": False,
            "requires_gpu": True,
            "cloned_voice": True,
            "streaming": True,
            "buffered_playback": True,
            "service_url": self.base_url,
            "sample_rate": self._sample_rate,
        }
        try:
            health = self._health()
            data.update({
                "provider": health.get("provider") or "cosyvoice3-local",
                "ready": bool(health.get("ok")),
                "sample_rate": int(health.get("sample_rate") or self._sample_rate),
                "model": health.get("model") or "Fun-CosyVoice3-0.5B-2512",
                "device": health.get("device") or "unknown",
                "reference_voice_configured": bool(health.get("reference_voice_configured")),
                "speaker_cached": bool(health.get("speaker_cached")),
                "model_warm": bool(health.get("model_warm")),
            })
        except Exception:
            data["ready"] = False
            data["reference_voice_configured"] = False
            data["speaker_cached"] = False
            data["model_warm"] = False
            data["device"] = "unavailable"
        return data

    def stop(self) -> None:
        self._interrupt.set()
        response = self._active_response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        self._speaking.clear()

    def stream_pcm(self, text: str) -> Iterator[bytes]:
        clean = " ".join(str(text or "").strip().split())
        if not clean:
            return

        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/tts",
                json={"text": clean},
                timeout=self.timeout_seconds,
            ) as response:
                self._active_response = response
                response.raise_for_status()
                rate = int(response.headers.get("X-Sample-Rate") or self._sample_rate)
                if rate > 0:
                    self._sample_rate = rate
                for chunk in response.iter_bytes():
                    if self._interrupt.is_set():
                        break
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise CosyVoiceProxyError(f"Errore dal motore vocale locale: {exc}") from exc
        finally:
            self._active_response = None

    def synthesize(self, text: str) -> CosyVoiceAudio:
        self._interrupt.clear()
        pcm = b"".join(self.stream_pcm(text))
        if not pcm:
            raise CosyVoiceProxyError("CosyVoice non ha restituito audio.")

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(pcm)
        return CosyVoiceAudio(buffer.getvalue())

    @staticmethod
    def _speech_segments(text: str, max_chars: int = 150) -> list[str]:
        """Create short natural segments that can be buffered before playback."""
        clean = " ".join(str(text or "").strip().split())
        if not clean:
            return []

        rough = re.split(r"(?<=[.!?;:])\s+", clean)
        segments: list[str] = []
        for part in rough:
            part = part.strip()
            while len(part) > max_chars:
                cut = max(
                    part.rfind(", ", 0, max_chars),
                    part.rfind(" ", 0, max_chars),
                )
                if cut < max_chars // 2:
                    cut = max_chars
                segment = part[:cut].strip(" ,")
                if segment:
                    segments.append(segment)
                part = part[cut:].strip(" ,")
            if part:
                segments.append(part)
        return segments or [clean]

    def _buffer_segment(self, text: str) -> bytes:
        pcm = b"".join(self.stream_pcm(text))
        if len(pcm) % 2:
            pcm = pcm[:-1]
        return pcm

    def speak(self, text: str, streamed: bool = True) -> None:
        del streamed
        if not text or not text.strip():
            return

        import sounddevice as sd

        segments = self._speech_segments(text)
        if not segments:
            return

        self._interrupt.clear()
        self._speaking.set()
        stream = None
        producer: threading.Thread | None = None
        audio_queue: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=2)
        try:
            self._health()
            first_started = time.monotonic()
            first_pcm = self._buffer_segment(segments[0])
            first_buffer_seconds = time.monotonic() - first_started
            if not first_pcm or self._interrupt.is_set():
                return

            def produce_remaining() -> None:
                try:
                    for segment in segments[1:]:
                        if self._interrupt.is_set():
                            break
                        pcm = self._buffer_segment(segment)
                        if pcm:
                            audio_queue.put(pcm)
                    audio_queue.put(None)
                except Exception as exc:
                    audio_queue.put(exc)

            if len(segments) > 1:
                producer = threading.Thread(
                    target=produce_remaining,
                    daemon=True,
                    name="jarvis-tts-buffer",
                )
                producer.start()

            # A stable output buffer is preferable to ultra-low latency here:
            # inference latency is already paid before playback starts, while a
            # PortAudio underflow is perceived as the voice cutting in and out.
            stream = sd.RawOutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                blocksize=0,
                latency="high",
            )
            stream.start()
            print(
                f"[TTS] buffer iniziale={first_buffer_seconds:.2f}s · "
                f"segmenti={len(segments)} · playback=buffered"
            )
            stream.write(first_pcm)

            while len(segments) > 1 and not self._interrupt.is_set():
                item = audio_queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                if item:
                    stream.write(item)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            self._speaking.clear()
            self._interrupt.clear()
