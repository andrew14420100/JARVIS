from __future__ import annotations

from collections.abc import Iterable, Iterator
import json
import re
from typing import Any

import httpx


class LMStudioError(RuntimeError):
    pass


class LMStudioClient:
    """OpenAI-compatible LM Studio client with real token streaming."""

    _TOOL_MARKERS = (
        "apri", "chiudi", "avvia", "ferma", "stoppa", "riavvia",
        "controlla", "verifica", "cerca", "trova", "scarica", "installa",
        "disinstalla", "modifica", "cambia", "crea", "elimina", "cancella",
        "sposta", "rinomina", "salva", "carica", "invia", "manda", "scrivi",
        "pubblica", "esegui", "lancia", "compra", "ordina", "prenota",
        "analizza", "debug", "correggi", "progetta", "pianifica",
        "confronta", "ottimizza", "investiga", "diagnostica", "implementa",
        "testa", "github", "browser", "file", "cartella", "sito", "pc",
    )
    _DEEP_MARKERS = (
        "dimostra", "dimostrazione", "integrale", "derivata", "equazione",
        "matematica", "calcola", "debug", "correggi", "implementa", "codice",
        "architettura", "analizza", "analisi", "ottimizza", "progetta",
        "pianifica", "confronta", "ricerca", "investiga", "diagnostica",
        "github", "deploy", "backend", "frontend", "database", "api",
    )

    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        timeout = httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds))
        self._client = httpx.Client(timeout=timeout)
        self.last_error = ""

    def close(self) -> None:
        self._client.close()

    def list_models(self) -> list[str]:
        try:
            response = self._client.get(f"{self.base_url}/models")
            response.raise_for_status()
            payload = response.json()
            return [item["id"] for item in payload.get("data", []) if item.get("id")]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            self.last_error = str(exc)
            raise LMStudioError(f"Impossibile leggere i modelli da LM Studio: {exc}") from exc

    @staticmethod
    def _normalize_model_name(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

    @classmethod
    def _matches_preference(cls, loaded_model: str, preferred_model: str) -> bool:
        loaded = cls._normalize_model_name(loaded_model)
        preferred = cls._normalize_model_name(preferred_model)
        if not loaded or not preferred:
            return False
        return loaded == preferred or preferred in loaded or loaded in preferred

    @staticmethod
    def _parse_preferences(preferred_models: str | Iterable[str] | None) -> list[str]:
        if preferred_models is None:
            return []
        if isinstance(preferred_models, str):
            raw = preferred_models.replace("\n", "|").replace(",", "|")
            return [item.strip() for item in raw.split("|") if item.strip()]
        return [str(item).strip() for item in preferred_models if str(item).strip()]

    def resolve_best_model(self, preferred_models: str | Iterable[str] | None = None) -> str:
        models = self.list_models()
        if not models:
            raise LMStudioError("Nessun modello caricato in LM Studio.")

        preferences = self._parse_preferences(preferred_models)
        for preferred in preferences:
            for loaded in models:
                if self._matches_preference(loaded, preferred):
                    return loaded
        return models[0]

    def resolve_model(self, configured_model: str = "") -> str:
        if configured_model:
            return configured_model
        return self.resolve_best_model()

    @staticmethod
    def _latest_user_text(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    return content.strip().lower()
        return ""

    @classmethod
    def _is_fast_voice_turn(
        cls,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> bool:
        if tools:
            return False
        text = cls._latest_user_text(messages)
        if not text:
            return False
        words = text.split()
        if len(words) > 32:
            return False
        return not any(marker in text for marker in cls._DEEP_MARKERS)

    @classmethod
    def _prepare_messages_for_latency(
        cls,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        fast = cls._is_fast_voice_turn(messages, tools)
        if not fast or "qwen" not in cls._normalize_model_name(model):
            return messages, fast

        # Qwen's soft switch disables long hidden reasoning for the current turn.
        # Work on a shallow copy so the permanent conversation transcript remains
        # clean and never stores the control token.
        prepared = [dict(message) for message in messages]
        for index in range(len(prepared) - 1, -1, -1):
            if prepared[index].get("role") != "user":
                continue
            content = prepared[index].get("content")
            if isinstance(content, str) and "/no_think" not in content:
                prepared[index]["content"] = content.rstrip() + "\n/no_think"
            break
        return prepared, fast

    def can_stream_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> bool:
        if not tools:
            return True
        text = self._latest_user_text(messages)
        if not text:
            return True
        return not any(marker in text for marker in self._TOOL_MARKERS)

    @staticmethod
    def _content_from_delta(delta: dict[str, Any]) -> str:
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        return ""

    def chat_completion_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.4,
    ) -> Iterator[str]:
        prepared_messages, fast_turn = self._prepare_messages_for_latency(model, messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": prepared_messages,
            "temperature": temperature,
            "stream": True,
        }
        if fast_turn:
            payload["max_tokens"] = 220

        produced = False
        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = self._content_from_delta(delta)
                    if text:
                        produced = True
                        yield text
            if not produced:
                raise LMStudioError("LM Studio non ha prodotto testo in streaming.")
            self.last_error = ""
        except (httpx.HTTPError, ValueError, KeyError, IndexError, LMStudioError) as exc:
            self.last_error = str(exc)
            if isinstance(exc, LMStudioError):
                raise
            raise LMStudioError(f"Errore streaming LM Studio: {exc}") from exc

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        prepared_messages, fast_turn = self._prepare_messages_for_latency(model, messages, tools)
        payload: dict[str, Any] = {
            "model": model,
            "messages": prepared_messages,
            "temperature": temperature,
        }
        if fast_turn:
            payload["max_tokens"] = 220
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            response = self._client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            self.last_error = ""
            return message
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            self.last_error = str(exc)
            raise LMStudioError(f"Errore durante la richiesta a LM Studio: {exc}") from exc
