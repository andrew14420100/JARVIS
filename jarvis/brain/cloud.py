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
    extra_body: dict[str, Any] | None = None
    supports_dynamic_thinking: bool = False


class CloudAIClient:
    """OpenAI-compatible cloud client restricted to explicitly free routes.

    Provider priority is deterministic:
    NVIDIA Nemotron 3 Ultra -> Z.AI free GLM -> Groq Free -> OpenRouter Free.

    JARVIS never substitutes a paid model. If every configured free provider is
    unavailable or rate-limited, the request fails instead of becoming billable.
    """

    NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
    ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"
    GROQ_BASE_URL = "https://api.groq.com/openai/v1"
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    NVIDIA_FREE_MODELS = {"nvidia/nemotron-3-ultra-550b-a55b"}
    ZAI_FREE_MODELS = {"glm-4.7-flash", "glm-4.5-flash"}

    def __init__(
        self,
        *,
        nvidia_api_key: str = "",
        nvidia_model: str = "nvidia/nemotron-3-ultra-550b-a55b",
        zai_api_key: str = "",
        zai_model: str = "glm-4.7-flash",
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

        if nvidia_api_key.strip():
            selected_nvidia = nvidia_model.strip() or "nvidia/nemotron-3-ultra-550b-a55b"
            if selected_nvidia not in self.NVIDIA_FREE_MODELS:
                raise CloudAIError(
                    "JARVIS_NVIDIA_MODEL deve essere un modello NVIDIA esplicitamente "
                    f"ammesso come endpoint gratuito ({', '.join(sorted(self.NVIDIA_FREE_MODELS))})."
                )
            self.providers.append(
                CloudProvider(
                    name="nvidia-free",
                    base_url=self.NVIDIA_BASE_URL,
                    api_key=nvidia_api_key.strip(),
                    model=selected_nvidia,
                    extra_headers={},
                    supports_dynamic_thinking=True,
                )
            )

        if zai_api_key.strip():
            selected_zai = zai_model.strip() or "glm-4.7-flash"
            if selected_zai not in self.ZAI_FREE_MODELS:
                raise CloudAIError(
                    "JARVIS_ZAI_MODEL deve essere un modello Z.AI esplicitamente gratuito "
                    f"({', '.join(sorted(self.ZAI_FREE_MODELS))})."
                )
            self.providers.append(
                CloudProvider(
                    name="zai-free",
                    base_url=self.ZAI_BASE_URL,
                    api_key=zai_api_key.strip(),
                    model=selected_zai,
                    extra_headers={},
                    extra_body={"thinking": {"type": "disabled"}},
                )
            )

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
                "Nessun provider cloud gratuito configurato. Imposta JARVIS_NVIDIA_API_KEY, "
                "JARVIS_ZAI_API_KEY, JARVIS_GROQ_API_KEY e/o JARVIS_OPENROUTER_API_KEY."
            )
        return self.providers

    def list_models(self) -> list[str]:
        """Return only the configured free-only model ids."""
        return [provider.model for provider in self._configured_or_raise()]

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

    @staticmethod
    def _latest_user_text(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content") or "").strip().lower()
        return ""

    @classmethod
    def _is_agentic_request(
        cls,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> bool:
        """Use deep thinking only when the actual turn benefits from it.

        Tools may stay available on every turn so Nemotron can still open apps or
        inspect the PC. Their mere presence must not force expensive reasoning for
        a greeting or a short conversational reply.
        """
        if not tools:
            return False
        text = cls._latest_user_text(messages)
        words = text.split()
        if len(words) >= 20:
            return True
        deep_markers = (
            "analizza", "debug", "correggi", "progetta", "pianifica",
            "confronta", "ottimizza", "investiga", "diagnostica",
            "architettura", "implementa", "multi-step", "passaggi",
            "ragiona", "strategia", "verifica e correggi", "testa e",
        )
        return any(marker in text for marker in deep_markers)

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        del model  # each provider is pinned to its own free-only model id.
        errors: list[str] = []

        for provider in self._configured_or_raise():
            payload: dict[str, Any] = {
                "model": provider.model,
                "messages": messages,
                "temperature": temperature,
            }
            if provider.extra_body:
                payload.update(provider.extra_body)
            if provider.supports_dynamic_thinking:
                payload["chat_template_kwargs"] = {
                    "enable_thinking": self._is_agentic_request(messages, tools)
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
                errors.append(f"{provider.name}: {exc}")

        self.last_error = " | ".join(errors)
        raise CloudAIError(
            "Tutti i provider AI gratuiti configurati sono temporaneamente non disponibili "
            f"o hanno raggiunto i propri limiti. Dettagli: {self.last_error}"
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
