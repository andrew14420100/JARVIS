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


def test_falls_back_from_groq_to_openrouter_free():
    seen_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content.decode("utf-8"))
            seen_models.append(payload["model"])
            if request.url.host == "api.groq.com":
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
        groq_api_key="groq-test",
        openrouter_api_key="router-test",
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    message = client.chat_completion(
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": "ciao"}],
    )

    assert message["content"] == "fallback ok"
    assert seen_models == ["qwen/qwen3.8-27b", "openrouter/free"]
    assert client.status()["active_provider"] == "openrouter-free"
    assert client.status()["paid_fallback"] is False

    client.close()


def test_requires_at_least_one_cloud_key():
    client = CloudAIClient()
    with pytest.raises(CloudAIError):
        client.resolve_model()
    client.close()
