from __future__ import annotations

import json
from typing import Any, Generator
import httpx


class LMStudioError(RuntimeError):
    pass


class LMStudioClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_seconds)


    def chat_completion_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.35,
    ) -> Generator[dict[str, Any], None, None]:
        """Stream text deltas from the local OpenAI-compatible LM Studio server."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "max_tokens": 128,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                full_content = ""
                for raw in response.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    text = str(delta.get("content") or "")
                    if text:
                        full_content += text
                        yield {"type": "delta", "text": text}
                yield {"type": "done", "content": full_content, "tool_calls": []}
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise LMStudioError(f"Errore nello streaming da LM Studio: {exc}") from exc

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
