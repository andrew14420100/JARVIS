import json

import httpx
import pytest

from jarvis.brain.cloud import CloudAIClient, CloudAIError


def test_rejects_paid_openrouter_model():
    with pytest.raises(CloudAIError):
        CloudAIClient(
            openrouter_api_key="test-key",
            openrouter_model="anthropic/claude-sonnet-5",
        )


def test_rejects_unlisted_nvidia_model():
    with pytest.raises(CloudAIError):
        CloudAIClient(
            nvidia_api_key="test-key",
            nvidia_model="nvidia/not-a-free-model",
        )


def _tool_schema():
    return [{"type": "function", "function": {"name": "demo", "parameters": {"type": "object"}}}]


def test_prefers_nemotron_and_enables_thinking_for_complex_agentic_calls():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content.decode("utf-8"))
            seen.append(payload)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "nemotron ok"}}
                    ]
                },
            )
        return httpx.Response(200, json={"data": []})

    client = CloudAIClient(
        nvidia_api_key="nvapi-test",
        zai_api_key="zai-test",
        groq_api_key="groq-test",
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    message = client.chat_completion(
        model="nvidia/nemotron-3-ultra-550b-a55b",
        messages=[{
            "role": "user",
            "content": "analizza il progetto, diagnostica il problema, pianifica i passaggi e verifica e correggi il risultato",
        }],
        tools=_tool_schema(),
    )

    assert message["content"] == "nemotron ok"
    assert seen[0]["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
    assert seen[0]["chat_template_kwargs"]["enable_thinking"] is True
    assert client.status()["active_provider"] == "nvidia-free"
    assert client.status()["paid_fallback"] is False
    client.close()


def test_keeps_thinking_disabled_for_short_conversation_even_with_tools_available():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen.append(payload)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "Bene, signore."}}]},
        )

    client = CloudAIClient(nvidia_api_key="nvapi-test")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    message = client.chat_completion(
        model="nvidia/nemotron-3-ultra-550b-a55b",
        messages=[{"role": "user", "content": "come va?"}],
        tools=_tool_schema(),
    )

    assert message["content"] == "Bene, signore."
    assert seen[0]["chat_template_kwargs"]["enable_thinking"] is False
    assert "tools" in seen[0]
    client.close()


def test_falls_back_from_nvidia_and_groq_to_openrouter_free():
    seen_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content.decode("utf-8"))
            seen_models.append(payload["model"])
            if request.url.host in {"integrate.api.nvidia.com", "api.groq.com"}:
                return httpx.Response(429, json={"error": {"message": "quota"}})
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "fallback ok"}}
                    ]
                },
            )
        return httpx.Response(200, json={"data": []})

    client = CloudAIClient(
        nvidia_api_key="nvapi-test",
        groq_api_key="groq-test",
        openrouter_api_key="router-test",
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    message = client.chat_completion(
        model="nvidia/nemotron-3-ultra-550b-a55b",
        messages=[{"role": "user", "content": "ciao"}],
    )

    assert message["content"] == "fallback ok"
    assert seen_models == [
        "nvidia/nemotron-3-ultra-550b-a55b",
        "qwen/qwen3.8-27b",
        "openrouter/free",
    ]
    assert client.status()["active_provider"] == "openrouter-free"
    assert client.status()["paid_fallback"] is False
    client.close()


def test_requires_at_least_one_cloud_key():
    client = CloudAIClient()
    with pytest.raises(CloudAIError):
        client.resolve_model()
    client.close()
