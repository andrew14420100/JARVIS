from __future__ import annotations

from typing import Any
import httpx


class LMStudioError(RuntimeError):
    pass


class LMStudioClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def list_models(self) -> list[str]:
        try:
            response = self._client.get(f"{self.base_url}/models")
            response.raise_for_status()
            payload = response.json()
            return [item["id"] for item in payload.get("data", []) if item.get("id")]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LMStudioError(f"Impossibile leggere i modelli da LM Studio: {exc}") from exc

    def resolve_model(self, configured_model: str = "") -> str:
        if configured_model:
            return configured_model
        models = self.list_models()
        if not models:
            raise LMStudioError("Nessun modello caricato in LM Studio.")
        return models[0]

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            response = self._client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise LMStudioError(f"Errore durante la richiesta a LM Studio: {exc}") from exc
