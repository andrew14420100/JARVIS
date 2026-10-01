from __future__ import annotations

from collections.abc import Iterator
import re
import time

from .cosyvoice_proxy import CosyVoiceProxyTTS as _BaseCosyVoiceProxyTTS
from .echo import echo_reference


class CosyVoiceProxyTTS(_BaseCosyVoiceProxyTTS):
    """CosyVoice client that degrades to ordinary streaming instead of silence."""

    def _play_pcm_iterator(self, pcm_chunks: Iterator[bytes], *, label: str) -> None:
        """Play PCM while retaining a short in-memory echo reference."""
        import sounddevice as sd

        stream = None
        carry = b""
        started = time.monotonic()
        first_audio = None
        total_bytes = 0
        echo_reference.clear()
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
                    print(f"[TTS] primo_audio={first_audio:.2f}s · playback={label}")
                total_bytes += len(data)
                echo_reference.push_pcm16(data, self._sample_rate)
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

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Remove hidden Qwen reasoning before the base speech cleanup runs."""
        clean = str(text or "")
        clean = re.sub(
            r"<think\b[^>]*>.*?</think>",
            "",
            clean,
            flags=re.IGNORECASE | re.DOTALL,
        )
        while True:
            match = re.search(r"</think\s*>", clean, flags=re.IGNORECASE)
            if match is None:
                break
            clean = clean[match.end():]
        match = re.search(r"<think\b[^>]*>", clean, flags=re.IGNORECASE)
        if match is not None:
            clean = clean[:match.start()]
        return _BaseCosyVoiceProxyTTS._clean_for_speech(clean)

    @staticmethod
    def _strip_think_chunks(chunks: Iterator[str]) -> Iterator[str]:
        """Yield only visible text, even when think tags are split across chunks."""
        pending = ""
        in_think = False
        open_token = "<think"
        close_token = "</think"

        def partial_suffix_length(value: str) -> int:
            lowered = value.lower()
            keep = 0
            for token in (open_token, close_token):
                upper = min(len(lowered), len(token) - 1)
                for size in range(1, upper + 1):
                    if token.startswith(lowered[-size:]):
                        keep = max(keep, size)
            return keep

        for raw in chunks:
            if raw is None:
                continue
            pending += str(raw)
            while pending:
                lowered = pending.lower()
                if in_think:
                    close_pos = lowered.find(close_token)
                    if close_pos < 0:
                        keep = partial_suffix_length(pending)
                        pending = pending[-keep:] if keep else ""
                        break
                    close_end = pending.find(">", close_pos)
                    if close_end < 0:
                        pending = pending[close_pos:]
                        break
                    pending = pending[close_end + 1:]
                    in_think = False
                    continue

                open_pos = lowered.find(open_token)
                close_pos = lowered.find(close_token)
                if close_pos >= 0 and (open_pos < 0 or close_pos < open_pos):
                    close_end = pending.find(">", close_pos)
                    if close_end < 0:
                        pending = pending[close_pos:]
                        break
                    pending = pending[close_end + 1:]
                    continue

                if open_pos >= 0:
                    visible = pending[:open_pos]
                    if visible:
                        yield visible
                    open_end = pending.find(">", open_pos)
                    if open_end < 0:
                        pending = pending[open_pos:]
                        break
                    pending = pending[open_end + 1:]
                    in_think = True
                    continue

                keep = partial_suffix_length(pending)
                if keep:
                    visible = pending[:-keep]
                    if visible:
                        yield visible
                    pending = pending[-keep:]
                else:
                    yield pending
                    pending = ""
                break

        if pending and not in_think and not pending.lstrip().startswith("<"):
            yield pending

    @classmethod
    def _segments_from_live_text(cls, chunks: Iterator[str]) -> Iterator[str]:
        buffer = ""
        first_packet = True
        for raw in cls._strip_think_chunks(chunks):
            if raw is None:
                continue
            buffer += str(raw)
            while buffer:
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

                min_len = 14 if first_packet else 34
                target = 20 if first_packet else 54
                max_len = 38 if first_packet else 88
                boundary = None
                punctuation = list(re.finditer(r"[.!?;:,](?:\s+|$)", buffer))
                for match in punctuation:
                    if min_len <= match.end() <= max_len:
                        boundary = match.end()
                        break
                if boundary is None:
                    for match in punctuation:
                        if target <= match.end() <= max_len:
                            boundary = match.end()
                            break
                if boundary is None and len(buffer) >= max_len:
                    cut = buffer.rfind(" ", 0, max_len + 1)
                    if cut >= min_len:
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

    def speak_text_stream(self, chunks: Iterator[str]) -> None:
        source = iter(chunks)
        collected: list[str] = []

        def tracking() -> Iterator[str]:
            for chunk in source:
                text = str(chunk or "")
                if text:
                    collected.append(text)
                    yield text

        try:
            super().speak_text_stream(tracking())
            return
        except Exception as exc:
            if self._interrupt.is_set():
                return
            print(f"[TTS] bistream degradato, fallback stream standard: {exc}")

        for chunk in source:
            text = str(chunk or "")
            if text:
                collected.append(text)
        fallback = "".join(collected).strip()
        if fallback and not self._interrupt.is_set():
            self.speak(fallback, streamed=True)
