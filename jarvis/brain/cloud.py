from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class CloudAIError(RuntimeError):
    pass


@dataclass(slots=True)
class CloudProvider:
    name: str
    base_url: str
    api_key: str
    model: str
    extra_headers: dict[str, str]


class CloudAIClient:
    """OpenAI-compatible cloud client with free-only provider fallback.

    The router never substitutes a paid OpenRouter model. OpenRouter is pinned
    to ``openrouter/free`` and Groq is pinned to the configured free-plan model.
    If all configured free providers fail or exhaust their quota, JARVIS raises
    an error instead of falling back to a billable endpoint.
    """

    GROQ_BASE_URL = "https://api.groq.com/openai/v1"
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        *,
        groq_api_key: str = "",
        openrouter_api_key: str = "",
        groq_model: str = "qwen/qwen3.8-27b",
        openrouter_model: str = "openrouter/free",
        timeout_seconds: float = 120.0,
        app_name: str = "JARVIS",
        app_url: str = "",
    ) -> None:
        self._client = httpx.Client(timeout=timeout_seconds)
        self.providers: list[CloudProvider] = []
        self.last_provider = ""
        self.last_model = ""
        self.last_error = ""

        if groq_api_key.strip():
            self.providers.append(
                CloudProvider(
                    name="groq-free",
                    base_url=self.GROQ_BASE_URL,
                    api_key=groq_api_key.strip(),
                    model=groq_model.strip() or "qwen/qwen3.8-27b",
                    extra_headers={},
                )
            )

        if openrouter_api_key.strip():
            # Deliberately force the free router. A paid model id is never
            # accepted here, even if an environment variable is changed later.
            free_model = openrouter_model.strip() or "openrouter/free"
            if free_model != "openrouter/free" and not free_model.endswith(":free"):
                raise CloudAIError(
                    "JARVIS_OPENROUTER_MODEL deve essere 'openrouter/free' oppure terminare con ':free'."
                )
            headers: dict[str, str] = {"X-Title": app_name}
            if app_url.strip():
                headers["HTTP-Referer"] = app_url.strip()
            self.providers.append(
                CloudProvider(
                    name="openrouter-free",
                    base_url=self.OPENROUTER_BASE_URL,
                    api_key=openrouter_api_key.strip(),
                    model=free_model,
                    extra_headers=headers,
                )
            )

    def close(self) -> None:
        self._client.close()

    def _headers(self, provider: CloudProvider) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            **provider.extra_headers,
        }

    def _configured_or_raise(self) -> list[CloudProvider]:
        if not self.providers:
            raise CloudAIError(
                "Nessun provider cloud gratuito configurato. Imposta JARVIS_GROQ_API_KEY "
                "e/o JARVIS_OPENROUTER_API_KEY nel backend."
            )
        return self.providers

    def list_models(self) -> list[str]:
        """Verify at least one configured provider and return only free model ids."""
        errors: list[str] = []
        for provider in self._configured_or_raise():
            try:
                response = self._client.get(
                    f"{provider.base_url}/models",
                    headers=self._headers(provider),
                )
                response.raise_for_status()
                self.last_provider = provider.name
                self.last_model = provider.model
                self.last_error = ""
                return [item.model for item in self.providers]
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{provider.name}: {exc}")
        self.last_error = " | ".join(errors)
        raise CloudAIError(f"Provider cloud gratuiti non raggiungibili: {self.last_error}")

    def resolve_model(self, configured_model: str = "") -> str:
        providers = self._configured_or_raise()
        if configured_model.strip():
            allowed = {provider.model for provider in providers}
            if configured_model.strip() not in allowed:
                raise CloudAIError(
                    "Il modello configurato non appartiene alla whitelist gratuita di JARVIS."
                )
            return configured_model.strip()
        return providers[0].model

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        del model  # each provider is pinned to its own verified free model id.
        errors: list[str] = []

        for provider in self._configured_or_raise():
            payload: dict[str, Any] = {
                "model": provider.model,
                "messages": messages,
                "temperature": temperature,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            try:
                response = self._client.post(
                    f"{provider.base_url}/chat/completions",
                    headers=self._headers(provider),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                self.last_provider = provider.name
                self.last_model = provider.model
                self.last_error = ""
                return message
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                # Includes quota/rate-limit failures. The next configured free
                # provider is tried automatically; no paid route exists.
                errors.append(f"{provider.name}: {exc}")

        self.last_error = " | ".join(errors)
        raise CloudAIError(
            "Tutti i provider AI gratuiti configurati sono temporaneamente non disponibili "
            f"o hanno esaurito la quota gratuita. Dettagli: {self.last_error}"
        )

    def status(self) -> dict[str, object]:
        return {
            "mode": "cloud-free",
            "configured": [provider.name for provider in self.providers],
            "models": [provider.model for provider in self.providers],
            "active_provider": self.last_provider,
            "active_model": self.last_model,
            "last_error": self.last_error,
            "paid_fallback": False,
        }
