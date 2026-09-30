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

    Audio is consumed while CosyVoice is still generating it. A very small
    PCM prebuffer absorbs inference jitter without forcing JARVIS to wait for
    a complete sentence before it starts speaking.
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

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Remove Markdown/control punctuation that should not be spoken."""
        clean = str(text or "")
        clean = re.sub(r"```(?:[\w.+-]+)?\s*", "", clean)
        clean = clean.replace("```", "")
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
        clean = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", clean)
        clean = re.sub(r"(?m)^\s*[-*+]\s+", "", clean)
        clean = re.sub(r"(?m)^\s*\d+[.)]\s+", "", clean)
        clean = re.sub(r"[*_~`]+", "", clean)
        return " ".join(clean.strip().split())

    def stream_pcm(self, text: str) -> Iterator[bytes]:
        clean = self._clean_for_speech(text)
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
        if len(pcm) % 2:
            pcm = pcm[:-1]

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(pcm)
        return CosyVoiceAudio(buffer.getvalue())

    def speak(self, text: str, streamed: bool = True) -> None:
        del streamed
        clean = self._clean_for_speech(text)
        if not clean:
            return

        import sounddevice as sd

        self._interrupt.clear()
        self._speaking.set()
        stream = None
        producer: threading.Thread | None = None
        audio_queue: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=24)

        def queue_item(item: bytes | Exception | None) -> bool:
            while not self._interrupt.is_set():
                try:
                    audio_queue.put(item, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def produce_audio() -> None:
            carry = b""
            try:
                for chunk in self.stream_pcm(clean):
                    if self._interrupt.is_set():
                        break
                    data = carry + chunk
                    carry = b""
                    if len(data) % 2:
                        carry = data[-1:]
                        data = data[:-1]
                    if data and not queue_item(data):
                        break
            except Exception as exc:
                queue_item(exc)
            finally:
                queue_item(None)

        try:
            self._health()
            sample_rate = self._sample_rate
            bytes_per_second = sample_rate * 2
            target_prebuffer_bytes = max(4096, int(bytes_per_second * 0.30))

            started = time.monotonic()
            producer = threading.Thread(
                target=produce_audio,
                daemon=True,
                name="jarvis-tts-stream",
            )
            producer.start()

            prebuffer = bytearray()
            source_finished = False
            while len(prebuffer) < target_prebuffer_bytes and not self._interrupt.is_set():
                try:
                    item = audio_queue.get(timeout=0.10)
                except queue.Empty:
                    if producer is not None and not producer.is_alive():
                        break
                    continue

                if item is None:
                    source_finished = True
                    break
                if isinstance(item, Exception):
                    raise item
                prebuffer.extend(item)

            if not prebuffer or self._interrupt.is_set():
                return

            stream = sd.RawOutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                blocksize=0,
                latency="low",
            )
            stream.start()
            first_audio_seconds = time.monotonic() - started
            buffered_seconds = len(prebuffer) / float(max(1, self._sample_rate * 2))
            print(
                f"[TTS] primo_audio={first_audio_seconds:.2f}s · "
                f"prebuffer={buffered_seconds:.2f}s · playback=streaming"
            )
            stream.write(bytes(prebuffer))

            while not source_finished and not self._interrupt.is_set():
                try:
                    item = audio_queue.get(timeout=0.10)
                except queue.Empty:
                    if producer is not None and not producer.is_alive():
                        break
                    continue

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
