from __future__ import annotations

from collections.abc import Iterator

from .cosyvoice_proxy import CosyVoiceProxyTTS as _BaseCosyVoiceProxyTTS


class CosyVoiceProxyTTS(_BaseCosyVoiceProxyTTS):
    """CosyVoice client that degrades to ordinary streaming instead of silence."""

    @classmethod
    def _segments_from_live_text(cls, chunks: Iterator[str]) -> Iterator[str]:
        # Reuse the native-bistream segmenter but release the first phrase a bit
        # earlier so JARVIS starts speaking closer to the first LLM tokens.
        import re

        buffer = ""
        first_packet = True
        for raw in chunks:
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

                target = 22 if first_packet else 56
                max_len = 38 if first_packet else 88
                boundary = None
                for match in re.finditer(r"[.!?;:,](?:\s+|$)", buffer):
                    if match.end() >= target:
                        boundary = match.end()
                        break
                if boundary is None and len(buffer) >= max_len:
                    cut = buffer.rfind(" ", 0, max_len + 1)
                    if cut >= max(14, target // 2):
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
            print(f"[TTS] bistream degradato, fallback stream standard: {exc}")

        # Finish consuming the LLM stream so an audio error never truncates the
        # assistant's answer/history. Then retry once through the simpler /tts
        # endpoint, which is independent from the bistream session state.
        for chunk in source:
            text = str(chunk or "")
            if text:
                collected.append(text)
        fallback = "".join(collected).strip()
        if fallback and not self._interrupt.is_set():
            self.speak(fallback, streamed=True)
