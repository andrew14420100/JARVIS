from __future__ import annotations

from dataclasses import dataclass
import io
import threading
import wave
from typing import Iterator

import httpx


class CosyVoiceProxyError(RuntimeError):
    pass


@dataclass(slots=True)
class CosyVoiceAudio:
    data: bytes
    media_type: str = "audio/wav"
    provider: str = "cosyvoice3-local"


class CosyVoiceProxyTTS:
    """Client for the local CosyVoice 3 voice-cloning service.

    The heavy TTS model runs in a separate Python 3.10 process so it does not
    pollute the main JARVIS environment. Audio is streamed as mono signed 16-bit
    PCM for low-latency playback.
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
            "requires_api_key": False,
            "requires_local_gpu": True,
            "cloned_voice": True,
            "streaming": True,
            "service_url": self.base_url,
            "sample_rate": self._sample_rate,
        }
        try:
            health = self._health()
            data.update({
                "ready": bool(health.get("ok")),
                "sample_rate": int(health.get("sample_rate") or self._sample_rate),
                "model": health.get("model") or "Fun-CosyVoice3-0.5B-2512",
                "reference_voice_configured": bool(health.get("reference_voice_configured")),
            })
        except Exception:
            data["ready"] = False
            data["reference_voice_configured"] = False
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

        self._interrupt.clear()
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

    def speak(self, text: str, streamed: bool = True) -> None:
        del streamed
        if not text or not text.strip():
            return

        import sounddevice as sd

        self._interrupt.clear()
        self._speaking.set()
        stream = None
        try:
            # Prime health once so the correct model sample rate is known before
            # the first PCM chunk is sent to the audio device.
            self._health()
            stream = sd.RawOutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                blocksize=0,
                latency="low",
            )
            stream.start()
            for chunk in self.stream_pcm(text):
                if self._interrupt.is_set():
                    break
                if len(chunk) % 2:
                    chunk = chunk[:-1]
                if chunk:
                    stream.write(chunk)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            self._speaking.clear()
            self._interrupt.clear()
