from __future__ import annotations

from collections.abc import Iterator
import time
from typing import Any

from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator
from jarvis.brain.core_router import CoreDecision, JarvisCoreRouter, classify_task


class JarvisCoreOrchestrator(StableJarvisOrchestrator):
    """One JARVIS identity backed by a federation of specialist AI models."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.core_router = JarvisCoreRouter(
            consensus_enabled=bool(getattr(self.settings, "core_consensus_enabled", True)),
            consensus_min_complexity=int(getattr(self.settings, "core_consensus_min_complexity", 3)),
        )
        self._core_decision: CoreDecision | None = None
        self._core_advisor_context = ""
        self._loaded_models_cache: list[str] = []
        self._loaded_models_cached_at = 0.0

    def _local_brain(self):
        local = getattr(self.client, "_local_fallback", None)
        if local is None and self.client.__class__.__name__.lower().startswith("lmstudio"):
            local = self.client
        return local

    def _loaded_local_models(self, local) -> list[str]:
        now = time.monotonic()
        if self._loaded_models_cache and now - self._loaded_models_cached_at < 30.0:
            return list(self._loaded_models_cache)
        loaded = [str(item) for item in local.list_models() if str(item).strip()]
        self._loaded_models_cache = loaded
        self._loaded_models_cached_at = now
        return list(loaded)

    def _prepare_core_route(self, text: str, *, has_image: bool = False) -> None:
        self._core_decision = None
        self._core_advisor_context = ""
        if not bool(getattr(self.settings, "core_router_enabled", True)):
            return

        local = self._local_brain()
        if local is None:
            return
        try:
            loaded = self._loaded_local_models(local)
        except Exception as exc:
            self.last_reasoning["core_router_error"] = str(exc)
            return

        priority = (
            getattr(self.settings, "vision_model_priority", "")
            if has_image else getattr(self.settings, "local_model_priority", "")
        )
        decision = self.core_router.decide(
            loaded,
            text=text,
            has_image=has_image,
            configured_priority=priority,
        )
        self._core_decision = decision

        if not decision.advisor_model:
            return
        if not bool(getattr(self.settings, "core_consensus_enabled", True)):
            return

        try:
            recent = []
            for message in self.messages[-8:]:
                role = str(message.get("role") or "")
                content = message.get("content")
                if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                    recent.append({"role": role, "content": content[-1800:]})
            advisor_prompt = (
                "Agisci come consulente interno di JARVIS. Analizza la richiesta seguente "
                "in modo tecnico e molto compatto. Individua errori, rischi, passaggi mancanti "
                "e la strategia migliore. Non rivolgerti all'utente e non fingere di avere "
                "eseguito strumenti o azioni. Massimo 1200 caratteri.\n\nRichiesta: " + text
            )
            advisor_messages = [
                {
                    "role": "system",
                    "content": (
                        "Sei un modulo consulente interno. Produci solo un'analisi consultiva "
                        "breve e fattuale per il modello principale di JARVIS."
                    ),
                },
                *recent,
                {"role": "user", "content": advisor_prompt},
            ]
            response = local.chat_completion(
                model=decision.advisor_model,
                messages=advisor_messages,
                tools=None,
                temperature=0.15,
            )
            content = str(response.get("content") or "").strip()
            max_chars = max(300, int(getattr(self.settings, "core_advisor_max_chars", 1400)))
            if content:
                self._core_advisor_context = content[:max_chars]
        except Exception as exc:
            self.last_reasoning["core_advisor_error"] = str(exc)
            self._core_advisor_context = ""

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
        decision = self._core_decision
        if decision is None:
            task, complexity = classify_task(query)
            routing = f"JARVIS-Core: categoria {task}; complessità {complexity}."
        else:
            routing = (
                f"JARVIS-Core: categoria {decision.task}; complessità {decision.complexity}; "
                f"modello specialista selezionato {decision.primary_model or 'fallback globale'}."
            )
        if self._core_advisor_context:
            routing += (
                "\nAnalisi consultiva di un secondo modello interno. È un parere, non un risultato "
                "di strumenti e non prova che alcuna azione sia già avvenuta:\n"
                + self._core_advisor_context
            )
        insert_at = max(1, len(copied) - 1)
        copied.insert(insert_at, {"role": "system", "content": routing})
        return copied

    def _chat_stream(self, request_messages: list[dict]) -> Iterator[str]:
        decision = self._core_decision
        local = self._local_brain()
        if decision is None or not decision.primary_model or local is None:
            yield from super()._chat_stream(request_messages)
            return

        emitted = False
        try:
            for chunk in local.chat_completion_stream(
                model=decision.primary_model,
                messages=request_messages,
                temperature=0.4,
            ):
                if not chunk:
                    continue
                if not emitted:
                    if hasattr(self.client, "last_provider"):
                        self.client.last_provider = "jarvis-core-local"
                    if hasattr(self.client, "last_model"):
                        self.client.last_model = decision.primary_model
                emitted = True
                yield chunk
            if emitted:
                return
        except Exception as exc:
            if emitted:
                raise
            self.last_reasoning["core_primary_error"] = str(exc)
            self._loaded_models_cached_at = 0.0

        yield from super()._chat_stream(request_messages)

    def _visual_intent(self, text: str) -> bool:
        task, _ = classify_task(text)
        return task == "vision"

    def _stamp_core_reasoning(self) -> None:
        decision = self._core_decision
        if decision is None:
            return
        self.last_reasoning.update(
            {
                "core_task": decision.task,
                "core_complexity": decision.complexity,
                "core_primary_model": decision.primary_model,
                "core_advisor_model": decision.advisor_model,
                "core_consensus_used": bool(self._core_advisor_context),
                "core_reason": decision.reason,
            }
        )

    def process_message(self, text: str, *, ambient_context: str = "") -> str:
        self._prepare_core_route(text, has_image=self._visual_intent(text))
        try:
            reply = super().process_message(text, ambient_context=ambient_context)
            self._stamp_core_reasoning()
            return reply
        finally:
            self._core_advisor_context = ""

    def process_message_stream(self, text: str, *, ambient_context: str = "") -> Iterator[str]:
        self._prepare_core_route(text, has_image=self._visual_intent(text))
        try:
            for chunk in super().process_message_stream(text, ambient_context=ambient_context):
                yield chunk
            self._stamp_core_reasoning()
        finally:
            self._core_advisor_context = ""
