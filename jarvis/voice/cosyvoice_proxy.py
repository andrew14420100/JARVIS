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
    """Low-latency client for the local CosyVoice 3 service.

    Complete replies use the ordinary streaming endpoint. Live LLM replies use
    one native CosyVoice bistream session so acoustic state and prosody remain
    continuous while new text arrives.
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
        self._active_bistream_session: str | None = None
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
            return bool(self._health().get("ok"))
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
            "live_text_streaming": True,
            "native_bistream": False,
            "service_url": self.base_url,
            "sample_rate": self._sample_rate,
        }
        try:
            health = self._health()
            data.update({
                "provider": health.get("provider") or "cosyvoice3-local",
                "ready": bool(health.get("ok")),
                "sample_rate": int(health.get("sample_rate") or self._sample_rate),
                "model": health.get("model") or "Fun-CosyVoice3-0.5B",
                "device": health.get("device") or "unknown",
                "precision": health.get("precision") or "unknown",
                "native_bistream": bool(health.get("bistream")),
                "reference_voice_configured": bool(health.get("reference_voice_configured")),
                "speaker_cached": bool(health.get("speaker_cached")),
                "model_warm": bool(health.get("model_warm")),
            })
        except Exception:
            data["ready"] = False
            data["device"] = "unavailable"
        return data

    def stop(self) -> None:
        self._interrupt.set()
        session_id = self._active_bistream_session
        if session_id:
            try:
                httpx.post(
                    f"{self.base_url}/tts/bistream/{session_id}/finish",
                    timeout=1.0,
                )
            except Exception:
                pass
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
        clean = str(text or "")
        clean = re.sub(r"<invoke\b[^>]*>.*?</invoke>", "", clean, flags=re.IGNORECASE | re.DOTALL)
        clean = re.sub(r"<tool_call\b[^>]*>.*?</tool_call>", "", clean, flags=re.IGNORECASE | re.DOTALL)
        clean = re.sub(r"<parameter\b[^>]*>.*?</parameter>", "", clean, flags=re.IGNORECASE | re.DOTALL)
        clean = re.sub(r"```(?:[\w.+-]+)?\s*", "", clean)
        clean = clean.replace("```", "")
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
        clean = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", clean)
        clean = re.sub(r"(?m)^\s*[-*+]\s+", "", clean)
        clean = re.sub(r"(?m)^\s*\d+[.)]\s+", "", clean)
        clean = re.sub(r"[*_~`]+", "", clean)
        clean = re.sub(r"<[^>]+>", "", clean)
        return " ".join(clean.strip().split())

    @classmethod
    def _segments_from_live_text(cls, chunks: Iterator[str]) -> Iterator[str]:
        """Create modest text packets without restarting TTS acoustic state."""
        buffer = ""
        first_packet = True

        for raw in chunks:
            if raw is None:
                continue
            buffer += str(raw)

            while buffer:
                # Never release an unfinished internal markup block to speech.
                lowered = buffer.lower()
                unfinished_markup = False
                for opening, closing in (
                    ("<invoke", "</invoke>"),
                    ("<tool_call", "</tool_call>"),
                    ("<parameter", "</parameter>"),
                ):
                    pos = lowered.find(opening)
                    if pos >= 0 and lowered.find(closing, pos) < 0:
                        unfinished_markup = True
                        break
                if unfinished_markup:
                    break

                # A short first packet minimizes time-to-first-speech. Later
                # packets are larger because native bistream preserves prosody.
                target = 34 if first_packet else 64
                max_len = 52 if first_packet else 96
                boundary: int | None = None

                punctuation = list(re.finditer(r"[.!?;:,](?:\s+|$)", buffer))
                for match in punctuation:
                    if match.end() >= target:
                        boundary = match.end()
                        break

                if boundary is None and len(buffer) >= max_len:
                    cut = buffer.rfind(" ", 0, max_len + 1)
                    if cut >= max(18, target // 2):
                        boundary = cut

                if boundary is None:
                    break

                piece = buffer[:boundary].strip()
                buffer = buffer[boundary:].lstrip()
                clean = cls._clean_for_speech(piece)
                if clean:
                    first_packet = False
                    yield clean

        clean = cls._clean_for_speech(buffer)
        if clean:
            yield clean

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

    def _play_pcm_iterator(self, pcm_chunks: Iterator[bytes], *, label: str) -> None:
        import sounddevice as sd

        stream = None
        carry = b""
        started = time.monotonic()
        first_audio = None
        total_bytes = 0

        try:
            stream = sd.RawOutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                blocksize=0,
                latency="low",
            )
            stream.start()

            for chunk in pcm_chunks:
                if self._interrupt.is_set():
                    break
                if not chunk:
                    continue
                data = carry + chunk
                carry = b""
                if len(data) % 2:
                    carry = data[-1:]
                    data = data[:-1]
                if not data:
                    continue
                if first_audio is None:
                    first_audio = time.monotonic() - started
                    print(
                        f"[TTS] primo_audio={first_audio:.2f}s · "
                        f"playback={label}"
                    )
                total_bytes += len(data)
                stream.write(data)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            if first_audio is not None:
                audio_seconds = total_bytes / float(max(1, self._sample_rate * 2))
                print(f"[TTS] audio_riprodotto={audio_seconds:.2f}s · playback={label}")

    def speak_text_stream(self, chunks: Iterator[str]) -> None:
        """Feed live LLM text into one native CosyVoice3 bistream session."""
        import sounddevice as sd  # noqa: F401 - dependency check before session start

        health = self._health()
        if not health.get("bistream"):
            # Backwards-compatible fallback for an older voice service.
            full_text = "".join(str(chunk or "") for chunk in chunks)
            self.speak(full_text, streamed=True)
            return

        self._interrupt.clear()
        self._speaking.set()
        session_id: str | None = None
        audio_thread: threading.Thread | None = None
        audio_errors: list[Exception] = []
        packets_sent = 0
        turn_started = time.monotonic()

        try:
            start = httpx.post(
                f"{self.base_url}/tts/bistream/start",
                timeout=3.0,
            )
            start.raise_for_status()
            payload = start.json()
            session_id = str(payload["session_id"])
            self._active_bistream_session = session_id
            rate = int(payload.get("sample_rate") or self._sample_rate)
            if rate > 0:
                self._sample_rate = rate

            def consume_audio() -> None:
                try:
                    with httpx.stream(
                        "GET",
                        f"{self.base_url}/tts/bistream/{session_id}/audio",
                        timeout=self.timeout_seconds,
                    ) as response:
                        self._active_response = response
                        response.raise_for_status()
                        response_rate = int(response.headers.get("X-Sample-Rate") or self._sample_rate)
                        if response_rate > 0:
                            self._sample_rate = response_rate
                        self._play_pcm_iterator(
                            response.iter_bytes(),
                            label="cosyvoice-bistream",
                        )
                except Exception as exc:
                    audio_errors.append(exc)
                finally:
                    self._active_response = None

            audio_thread = threading.Thread(
                target=consume_audio,
                daemon=True,
                name="jarvis-cosyvoice-bistream-audio",
            )
            audio_thread.start()

            for packet in self._segments_from_live_text(chunks):
                if self._interrupt.is_set():
                    break
                response = httpx.post(
                    f"{self.base_url}/tts/bistream/{session_id}/push",
                    json={"text": packet},
                    timeout=3.0,
                )
                response.raise_for_status()
                packets_sent += 1

        except Exception as exc:
            raise CosyVoiceProxyError(f"Errore bistream CosyVoice: {exc}") from exc
        finally:
            if session_id:
                try:
                    httpx.post(
                        f"{self.base_url}/tts/bistream/{session_id}/finish",
                        timeout=3.0,
                    )
                except Exception:
                    pass

            if audio_thread is not None:
                audio_thread.join(timeout=self.timeout_seconds)

            self._active_bistream_session = None
            self._speaking.clear()

        if audio_errors:
            raise CosyVoiceProxyError(f"Playback bistream fallito: {audio_errors[0]}")

        print(
            f"[TTS] bistream_completo={time.monotonic() - turn_started:.2f}s · "
            f"pacchetti_testo={packets_sent}"
        )
        self._interrupt.clear()

    def speak(self, text: str, streamed: bool = True) -> None:
        del streamed
        clean = self._clean_for_speech(text)
        if not clean:
            return

        self._interrupt.clear()
        self._speaking.set()
        try:
            self._play_pcm_iterator(self.stream_pcm(clean), label="cosyvoice-stream")
        finally:
            self._speaking.clear()
            self._interrupt.clear()
