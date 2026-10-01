from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.core.state import JarvisState


class StableJarvisOrchestrator(JarvisOrchestrator):
    """Realtime-safe orchestrator for a persistent natural voice session."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.screen_monitor = None
        self.current_speaker_name = "utente"
        self.current_speaker_role = "owner"
        self.current_prosody = ""
        self._conversation_local_model = ""
        self._vision_local_model = ""

    def attach_screen_monitor(self, monitor) -> None:
        self.screen_monitor = monitor

    def set_interaction_context(
        self,
        *,
        speaker_name: str = "utente",
        speaker_role: str = "owner",
        prosody: str = "",
    ) -> None:
        self.current_speaker_name = str(speaker_name or "utente")[:80]
        self.current_speaker_role = str(speaker_role or "unknown")[:32]
        self.current_prosody = str(prosody or "")[:400]

    def _trim_history(self) -> None:
        limit = max(8, int(getattr(self.settings, "conversation_max_messages", 40)))
        if len(self.messages) <= limit + 1:
            return
        system = self.messages[0]
        rest = self.messages[1:]
        start = max(0, len(rest) - limit)
        while start < len(rest) and rest[start].get("role") != "user":
            start += 1
        tail = rest[-limit:] if start >= len(rest) else rest[start:]
        self.messages = [system, *tail]

    def _record_exchange(self, text: str, reply: str, *, partial: bool = False) -> None:
        if not self.memory or not text.strip():
            return
        try:
            self.memory.record_turn(
                text,
                reply,
                speaker=self.current_speaker_name,
                metadata={
                    "speaker_role": self.current_speaker_role,
                    "prosody": self.current_prosody,
                    "partial": bool(partial),
                },
                auto_semantic=bool(getattr(self.settings, "memory_auto_semantic", True)),
            )
        except Exception as exc:
            self.last_reasoning["memory_error"] = str(exc)

    def start_session(self, *, local_time: str = "", locale: str = "it-IT") -> str:
        if self.memory:
            try:
                self.memory.start_session("voice-wake")
            except Exception:
                pass
        reply = super().start_session(local_time=local_time, locale=locale)
        self._trim_history()
        return reply

    def process_message(self, text: str, *, ambient_context: str = "") -> str:
        self._trim_history()
        reply = super().process_message(text, ambient_context=ambient_context)
        if reply:
            self._record_exchange(text, reply)
        self._trim_history()
        return reply

    def _messages_with_context(
        self,
        query: str,
        *,
        ambient_context: str = "",
        cognitive_context: str = "",
        base_messages: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        copied = super()._messages_with_context(
            query,
            ambient_context=ambient_context,
            cognitive_context=cognitive_context,
            base_messages=base_messages,
        )

        identity_context = (
            f"Parlante verificato: {self.current_speaker_name}; ruolo autorizzativo: "
            f"{self.current_speaker_role}."
        )
        if self.current_prosody:
            identity_context += " " + self.current_prosody
        insert_at = max(1, len(copied) - 1)
        copied.insert(insert_at, {"role": "system", "content": identity_context})

        monitor = self.screen_monitor
        if (
            monitor is not None
            and bool(getattr(self.settings, "screen_attach_on_visual_request", True))
        ):
            try:
                visual = monitor.message_content(query)
            except Exception:
                visual = None
            if visual:
                # Replace only the current user turn. The image remains ephemeral
                # and is never copied into the durable conversation history.
                for index in range(len(copied) - 1, 0, -1):
                    if copied[index].get("role") == "user":
                        copied[index] = {"role": "user", "content": visual}
                        break
        return copied

    @staticmethod
    def _request_has_image(messages: list[dict]) -> bool:
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    return True
        return False

    def _resolve_realtime_local_model(self, local, *, visual: bool = False) -> str:
        cache_attr = "_vision_local_model" if visual else "_conversation_local_model"
        cached = getattr(self, cache_attr, "")
        if cached:
            return cached
        priority = (
            getattr(self.settings, "vision_model_priority", "")
            if visual else getattr(self.settings, "local_model_priority", "")
        )
        resolver = getattr(local, "resolve_best_model", None)
        if callable(resolver):
            model = resolver(priority)
        else:
            model = local.resolve_model("")
        setattr(self, cache_attr, model)
        return model

    def _chat_stream(self, request_messages: list[dict]) -> Iterator[str]:
        """Use the best already-served local model, then free cloud fallback."""
        prefer_local = bool(getattr(self.settings, "conversation_local_first", True))
        local = getattr(self.client, "_local_fallback", None) if prefer_local else None
        visual = self._request_has_image(request_messages)

        if local is not None:
            emitted = False
            try:
                local_model = self._resolve_realtime_local_model(local, visual=visual)
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
                if visual:
                    self._vision_local_model = ""
                else:
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
            self._record_exchange(text, content)
            self._trim_history()
            self.set_state(JarvisState.SPEAKING)
        except GeneratorExit:
            partial = "".join(chunks).strip()
            if partial:
                self.messages.append({"role": "assistant", "content": partial})
                self._record_exchange(text, partial, partial=True)
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
                self.messages.append({"role": "assistant", "content": partial})
                self._record_exchange(text, partial, partial=True)
                self._trim_history()
                self.set_state(JarvisState.IDLE)
                return
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

    def close(self) -> None:
        if self.memory:
            try:
                self.memory.close()
            except Exception:
                pass
        super().close()
