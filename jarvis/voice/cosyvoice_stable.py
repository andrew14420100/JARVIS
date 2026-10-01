from __future__ import annotations

from collections.abc import Iterator
import re

from .cosyvoice_proxy import CosyVoiceProxyTTS as _BaseCosyVoiceProxyTTS


class CosyVoiceProxyTTS(_BaseCosyVoiceProxyTTS):
    """CosyVoice client that degrades to ordinary streaming instead of silence."""

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Remove hidden Qwen reasoning before the base speech cleanup runs.

        The base cleaner removes markup tags, but removing only ``<think>`` and
        ``</think>`` would leave the reasoning body behind and make JARVIS read
        it aloud.  This stable runtime therefore strips complete reasoning
        blocks first and handles malformed/orphan boundaries defensively.
        """
        clean = str(text or "")
        clean = re.sub(
            r"<think\b[^>]*>.*?</think>",
            "",
            clean,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # If a stream/fallback starts in the middle of a reasoning block, an
        # orphan closing tag can arrive without its opening tag.  Everything
        # before that closing boundary is treated as hidden reasoning.
        while True:
            match = re.search(r"</think\s*>", clean, flags=re.IGNORECASE)
            if match is None:
                break
            clean = clean[match.end():]

        # Never speak the tail of an unfinished reasoning block.
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
                        # Discard reasoning immediately, retaining only a tiny
                        # suffix that may become a split closing tag next chunk.
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

                # Defensive recovery when the provider starts the stream in the
                # middle of a reasoning section and only the closing tag arrives.
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

                # Hold a partial '<think' / '</think' suffix so a tag split by
                # the LLM transport can never leak as speech.
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

        # Hidden reasoning is intentionally discarded at end-of-stream.  A
        # dangling '<th...' fragment is markup, not user-facing speech.
        if pending and not in_think and not pending.lstrip().startswith("<"):
            yield pending

    @classmethod
    def _segments_from_live_text(cls, chunks: Iterator[str]) -> Iterator[str]:
        # Release the first natural phrase early so JARVIS can start speaking
        # while the LLM is still generating the rest of the sentence.
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

                # Prefer a real punctuation boundary inside the latency window.
                punctuation = list(re.finditer(r"[.!?;:,](?:\s+|$)", buffer))
                for match in punctuation:
                    if min_len <= match.end() <= max_len:
                        boundary = match.end()
                        break
                # Otherwise use the first punctuation after the target only if
                # it is still reasonably close.
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
            # stop() is used for intentional barge-in. In that case replaying
            # the answer through /tts would make JARVIS talk again immediately
            # after the user interrupted it.
            if self._interrupt.is_set():
                return
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
