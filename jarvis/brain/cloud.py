from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
from typing import Any

import httpx

from jarvis.brain.lmstudio import LMStudioClient, LMStudioError


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
    """Free cloud priority with a fully streaming local LM Studio fallback."""

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
        local_fallback_enabled: bool = False,
        local_fallback_base_url: str = "http://127.0.0.1:1234/v1",
    ) -> None:
        timeout = httpx.Timeout(timeout_seconds, connect=min(8.0, timeout_seconds))
        self._client = httpx.Client(timeout=timeout)
        self.providers: list[CloudProvider] = []
        self.last_provider = ""
        self.last_model = ""
        self.last_error = ""
        self._local_fallback_enabled = bool(local_fallback_enabled)
        self._local_fallback = (
            LMStudioClient(local_fallback_base_url, timeout_seconds)
            if self._local_fallback_enabled
            else None
        )

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
        if self._local_fallback is not None:
            self._local_fallback.close()

    def _headers(self, provider: CloudProvider) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            **provider.extra_headers,
        }

    def _has_any_brain(self) -> bool:
        return bool(self.providers) or self._local_fallback is not None

    def _ensure_any_brain(self) -> None:
        if not self._has_any_brain():
            raise CloudAIError(
                "Nessun cervello AI configurato. Imposta almeno un provider gratuito "
                "oppure abilita il fallback LM Studio locale."
            )

    def list_models(self) -> list[str]:
        models = [provider.model for provider in self.providers]
        if not models and self._local_fallback is not None:
            try:
                models.extend(self._local_fallback.list_models())
            except LMStudioError as exc:
                self.last_error = f"lmstudio-local-fallback: {exc}"
        if not models:
            self._ensure_any_brain()
        return models

    def resolve_model(self, configured_model: str = "") -> str:
        configured = configured_model.strip()
        if configured:
            cloud_allowed = {provider.model for provider in self.providers}
            if configured in cloud_allowed:
                return configured
            if self._local_fallback is not None:
                local_models = self._local_fallback.list_models()
                if configured in local_models:
                    return configured
            raise CloudAIError("Il modello configurato non è disponibile nei cervelli abilitati.")

        if self.providers:
            return self.providers[0].model
        if self._local_fallback is not None:
            return self._local_fallback.resolve_model("")
        self._ensure_any_brain()
        raise CloudAIError("Nessun modello disponibile.")

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

    @classmethod
    def _should_offer_tools(
        cls,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> bool:
        if not tools:
            return False
        text = cls._latest_user_text(messages)
        if not text:
            return False
        markers = (
            "apri", "chiudi", "avvia", "ferma", "stoppa", "riavvia",
            "controlla", "verifica", "cerca", "trova", "scarica", "installa",
            "disinstalla", "modifica", "cambia", "crea", "elimina", "cancella",
            "sposta", "rinomina", "salva", "carica", "invia", "manda", "scrivi",
            "pubblica", "esegui", "lancia", "compra", "ordina", "prenota",
            "analizza", "debug", "correggi", "progetta", "pianifica",
            "confronta", "ottimizza", "investiga", "diagnostica", "implementa",
            "testa", "github", "browser", "file", "cartella", "sito", "pc",
        )
        return any(marker in text for marker in markers)

    def can_stream_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> bool:
        return self._has_any_brain() and not self._should_offer_tools(messages, tools)

    def _payload(
        self,
        provider: CloudProvider,
        *,
        messages: list[dict[str, Any]],
        selected_tools: list[dict[str, Any]] | None,
        temperature: float,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
        }
        if stream:
            payload["stream"] = True
        if provider.extra_body:
            payload.update(provider.extra_body)
        if provider.supports_dynamic_thinking:
            payload["chat_template_kwargs"] = {
                "enable_thinking": self._is_agentic_request(messages, selected_tools)
            }
        if selected_tools:
            payload["tools"] = selected_tools
            payload["tool_choice"] = "auto"
        return payload

    def _request_provider(
        self,
        provider: CloudProvider,
        *,
        messages: list[dict[str, Any]],
        selected_tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"{provider.base_url}/chat/completions",
            headers=self._headers(provider),
            json=self._payload(
                provider,
                messages=messages,
                selected_tools=selected_tools,
                temperature=temperature,
            ),
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]

    def _stream_provider(
        self,
        provider: CloudProvider,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
    ) -> Iterator[str]:
        produced = False
        with self._client.stream(
            "POST",
            f"{provider.base_url}/chat/completions",
            headers=self._headers(provider),
            json=self._payload(
                provider,
                messages=messages,
                selected_tools=None,
                temperature=temperature,
                stream=True,
            ),
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
                data = json.loads(line)
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    produced = True
                    yield content
        if not produced:
            raise CloudAIError(f"{provider.name} non ha prodotto testo in streaming.")

    def _request_local_fallback(
        self,
        *,
        messages: list[dict[str, Any]],
        selected_tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> dict[str, Any]:
        if self._local_fallback is None:
            raise LMStudioError("Fallback locale LM Studio disabilitato.")
        local_model = self._local_fallback.resolve_model("")
        message = self._local_fallback.chat_completion(
            model=local_model,
            messages=messages,
            tools=selected_tools,
            temperature=temperature,
        )
        self.last_provider = "lmstudio-local-fallback"
        self.last_model = local_model
        return message

    def _stream_local_fallback(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
    ) -> Iterator[str]:
        if self._local_fallback is None:
            raise LMStudioError("Fallback locale LM Studio disabilitato.")
        local_model = self._local_fallback.resolve_model("")
        emitted = False
        for chunk in self._local_fallback.chat_completion_stream(
            model=local_model,
            messages=messages,
            temperature=temperature,
        ):
            if not emitted:
                self.last_provider = "lmstudio-local-fallback"
                self.last_model = local_model
            emitted = True
            yield chunk
        if not emitted:
            raise LMStudioError("Fallback locale LM Studio senza output streaming.")

    def chat_completion_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.4,
    ) -> Iterator[str]:
        del model
        self._ensure_any_brain()
        errors: list[str] = []
        local_tried = False

        for provider in self.providers:
            emitted = False
            try:
                for chunk in self._stream_provider(
                    provider,
                    messages=messages,
                    temperature=temperature,
                ):
                    if not emitted:
                        self.last_provider = provider.name
                        self.last_model = provider.model
                        self.last_error = ""
                    emitted = True
                    yield chunk
                if emitted:
                    return
            except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError, IndexError, CloudAIError) as exc:
                if emitted:
                    self.last_error = f"{provider.name}: stream interrotto: {exc}"
                    raise CloudAIError(self.last_error) from exc
                errors.append(f"{provider.name}: {exc}")

            if provider.name == "nvidia-free" and self._local_fallback is not None:
                local_tried = True
                try:
                    yield from self._stream_local_fallback(
                        messages=messages,
                        temperature=temperature,
                    )
                    self.last_error = " | ".join(errors)
                    return
                except (LMStudioError, ValueError, KeyError, IndexError) as exc:
                    errors.append(f"lmstudio-local-fallback: {exc}")

        if self._local_fallback is not None and not local_tried:
            try:
                yield from self._stream_local_fallback(
                    messages=messages,
                    temperature=temperature,
                )
                self.last_error = " | ".join(errors)
                return
            except (LMStudioError, ValueError, KeyError, IndexError) as exc:
                errors.append(f"lmstudio-local-fallback: {exc}")

        self.last_error = " | ".join(errors)
        raise CloudAIError(
            "Tutti i cervelli AI gratuiti configurati sono temporaneamente non disponibili. "
            f"Dettagli: {self.last_error}"
        )

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        del model
        self._ensure_any_brain()
        errors: list[str] = []
        selected_tools = tools if self._should_offer_tools(messages, tools) else None

        start_index = 0
        if self.providers and self.providers[0].name == "nvidia-free":
            nvidia = self.providers[0]
            try:
                message = self._request_provider(
                    nvidia,
                    messages=messages,
                    selected_tools=selected_tools,
                    temperature=temperature,
                )
                self.last_provider = nvidia.name
                self.last_model = nvidia.model
                self.last_error = ""
                return message
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                errors.append(f"{nvidia.name}: {exc}")
                start_index = 1

            if self._local_fallback is not None:
                try:
                    message = self._request_local_fallback(
                        messages=messages,
                        selected_tools=selected_tools,
                        temperature=temperature,
                    )
                    self.last_error = " | ".join(errors)
                    return message
                except (LMStudioError, ValueError, KeyError, IndexError) as exc:
                    errors.append(f"lmstudio-local-fallback: {exc}")

        for provider in self.providers[start_index:]:
            try:
                message = self._request_provider(
                    provider,
                    messages=messages,
                    selected_tools=selected_tools,
                    temperature=temperature,
                )
                self.last_provider = provider.name
                self.last_model = provider.model
                self.last_error = ""
                return message
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                errors.append(f"{provider.name}: {exc}")

        if self._local_fallback is not None and start_index == 0:
            try:
                message = self._request_local_fallback(
                    messages=messages,
                    selected_tools=selected_tools,
                    temperature=temperature,
                )
                self.last_error = " | ".join(errors)
                return message
            except (LMStudioError, ValueError, KeyError, IndexError) as exc:
                errors.append(f"lmstudio-local-fallback: {exc}")

        self.last_error = " | ".join(errors)
        raise CloudAIError(
            "Tutti i cervelli AI gratuiti configurati sono temporaneamente non disponibili. "
            f"Dettagli: {self.last_error}"
        )

    def status(self) -> dict[str, object]:
        configured = [provider.name for provider in self.providers]
        if self._local_fallback is not None:
            configured.append("lmstudio-local-fallback")
        return {
            "mode": "cloud-free-with-local-fallback" if self._local_fallback is not None else "cloud-free",
            "configured": configured,
            "models": [provider.model for provider in self.providers],
            "active_provider": self.last_provider,
            "active_model": self.last_model,
            "last_error": self.last_error,
            "local_fallback_enabled": self._local_fallback is not None,
            "paid_fallback": False,
        }
