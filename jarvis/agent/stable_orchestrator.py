from __future__ import annotations

from collections.abc import Iterator

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.core.state import JarvisState


class StableJarvisOrchestrator(JarvisOrchestrator):
    """Realtime-safe orchestrator for natural desktop voice conversation."""

    def _trim_history(self) -> None:
        limit = max(8, int(getattr(self.settings, "conversation_max_messages", 32)))
        if len(self.messages) <= limit + 1:
            return
        system = self.messages[0]
        rest = self.messages[1:]
        start = max(0, len(rest) - limit)
        while start < len(rest) and rest[start].get("role") != "user":
            start += 1
        tail = rest[-limit:] if start >= len(rest) else rest[start:]
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

    def _chat_stream(self, request_messages: list[dict]) -> Iterator[str]:
        """Use local Qwen first for ordinary speech, cloud as immediate fallback.

        Tool-bearing and deep-agent turns never enter this method because the
        guarded path is selected before streaming. This keeps NVIDIA/cloud
        available for complex work while removing network latency from normal
        back-and-forth conversation when LM Studio is already running.
        """
        prefer_local = bool(getattr(self.settings, "conversation_local_first", True))
        local = getattr(self.client, "_local_fallback", None) if prefer_local else None

        if local is not None:
            emitted = False
            try:
                local_model = getattr(self, "_conversation_local_model", "")
                if not local_model:
                    local_model = local.resolve_model("")
                    self._conversation_local_model = local_model
                for chunk in local.chat_completion_stream(
                    model=local_model,
                    messages=request_messages,
                    temperature=0.4,
                ):
                    if not chunk:
                        continue
                    if not emitted:
                        if hasattr(self.client, "last_provider"):
                            self.client.last_provider = "lmstudio-local-realtime"
                        if hasattr(self.client, "last_model"):
                            self.client.last_model = local_model
                    emitted = True
                    yield chunk
                if emitted:
                    return
            except Exception as exc:
                if emitted:
                    raise
                self.last_reasoning["local_stream_error"] = str(exc)
                # The cached model may have been unloaded or replaced.
                self._conversation_local_model = ""

        stream_method = getattr(self.client, "chat_completion_stream")
        yield from stream_method(
            model=self.model,
            messages=request_messages,
            temperature=0.4,
        )

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
            for chunk in self._chat_stream(request_messages):
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
            elif (
                self.messages
                and self.messages[-1].get("role") == "user"
                and self.messages[-1].get("content") == text
            ):
                self.messages.pop()
            self._trim_history()
            self.set_state(JarvisState.IDLE)
            raise
        except Exception as exc:
            partial = "".join(chunks).strip()
            self.last_reasoning["stream_error"] = str(exc)

            if partial:
                # Never restart with a second provider after the user already
                # heard part of an answer: that creates duplicate/mixed speech.
                self.messages.append({"role": "assistant", "content": partial})
                self._trim_history()
                self.set_state(JarvisState.IDLE)
                return

            # No token reached the speaker. Remove the provisional turn and use
            # the guarded request path once, preserving provider fallback logic.
            if (
                self.messages
                and self.messages[-1].get("role") == "user"
                and self.messages[-1].get("content") == text
            ):
                self.messages.pop()
            self._trim_history()
            try:
                reply = self.process_message(text, ambient_context=ambient_context)
            except Exception:
                self.set_state(JarvisState.ERROR)
                raise
            if reply:
                yield reply
