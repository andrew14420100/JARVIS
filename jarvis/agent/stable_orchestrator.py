from __future__ import annotations

from collections.abc import Iterator

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.core.state import JarvisState


class StableJarvisOrchestrator(JarvisOrchestrator):
    """Realtime-safe orchestrator.

    Keeps the live prompt bounded during long conversations and preserves a
    valid message history when speech/streaming is interrupted mid-response.
    """

    def _trim_history(self) -> None:
        limit = max(8, int(getattr(self.settings, "conversation_max_messages", 32)))
        if len(self.messages) <= limit + 1:
            return
        system = self.messages[0]
        rest = self.messages[1:]
        start = max(0, len(rest) - limit)
        while start < len(rest) and rest[start].get("role") != "user":
            start += 1
        if start >= len(rest):
            tail = rest[-limit:]
        else:
            tail = rest[start:]
        self.messages = [system, *tail]

    def start_session(self, *, local_time: str = "", locale: str = "it-IT") -> str:
        reply = super().start_session(local_time=local_time, locale=locale)
        self._trim_history()
        return reply

    def process_message(self, text: str, *, ambient_context: str = "") -> str:
        self._trim_history()
        reply = super().process_message(text, ambient_context=ambient_context)
        self._trim_history()
        return reply

    def process_message_stream(self, text: str, *, ambient_context: str = "") -> Iterator[str]:
        self._trim_history()

        if self.pending_confirmation is not None:
            reply = self.process_message(text, ambient_context=ambient_context)
            if reply:
                yield reply
            return

        decision = self.reasoner.decide(text)
        if decision.use_openjarvis:
            reply = self.process_message(text, ambient_context=ambient_context)
            if reply:
                yield reply
            return

        candidate_messages = [*self.messages, {"role": "user", "content": text}]
        request_messages = self._messages_with_context(
            text,
            ambient_context=ambient_context,
            base_messages=candidate_messages,
        )
        can_stream = getattr(self.client, "can_stream_chat", None)
        stream_method = getattr(self.client, "chat_completion_stream", None)
        tools = self.registry.schemas()
        if (
            not callable(can_stream)
            or not callable(stream_method)
            or not can_stream(messages=request_messages, tools=tools)
        ):
            reply = self.process_message(text, ambient_context=ambient_context)
            if reply:
                yield reply
            return

        self.messages.append({"role": "user", "content": text})
        self.set_state(JarvisState.THINKING)
        self.last_reasoning = {
            "used_openjarvis": False,
            "score": decision.score,
            "reasons": decision.reasons,
            "agent": "",
            "model": "",
        }

        chunks: list[str] = []
        try:
            for chunk in stream_method(
                model=self.model,
                messages=request_messages,
                temperature=0.4,
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                if len(chunks) == 1:
                    self.set_state(JarvisState.SPEAKING)
                yield chunk

            content = "".join(chunks).strip()
            if not content:
                raise RuntimeError("Il modello non ha prodotto testo in streaming.")
            self.messages.append({"role": "assistant", "content": content})
            if self.memory:
                try:
                    self.memory.remember_if_requested(text)
                except Exception:
                    pass
            self._trim_history()
            self.set_state(JarvisState.SPEAKING)
        except GeneratorExit:
            partial = "".join(chunks).strip()
            if partial:
                self.messages.append({"role": "assistant", "content": partial})
            elif self.messages and self.messages[-1].get("role") == "user" and self.messages[-1].get("content") == text:
                self.messages.pop()
            self._trim_history()
            self.set_state(JarvisState.IDLE)
            raise
        except Exception:
            partial = "".join(chunks).strip()
            if partial:
                self.messages.append({"role": "assistant", "content": partial})
            elif self.messages and self.messages[-1].get("role") == "user" and self.messages[-1].get("content") == text:
                self.messages.pop()
            self._trim_history()
            self.set_state(JarvisState.ERROR)
            raise
