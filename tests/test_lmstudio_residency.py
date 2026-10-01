import httpx

from jarvis.brain.lmstudio import LMStudioClient


def test_list_models_returns_only_loaded_native_instances():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "type": "llm",
                            "key": "qwen/qwen3-4b",
                            "loaded_instances": [
                                {"id": "jarvis-fast", "config": {"context_length": 2048}}
                            ],
                        },
                        {
                            "type": "llm",
                            "key": "qwen/qwen3.8-27b",
                            "loaded_instances": [],
                        },
                        {
                            "type": "embedding",
                            "key": "embed-small",
                            "loaded_instances": [{"id": "embed-small"}],
                        },
                    ]
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    client = LMStudioClient("http://127.0.0.1:1234/v1")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        assert client.list_models() == ["jarvis-fast"]
    finally:
        client.close()


def test_list_models_falls_back_for_older_lm_studio():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(404)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "legacy-loaded"}]})
        raise AssertionError(f"unexpected path {request.url.path}")

    client = LMStudioClient("http://127.0.0.1:1234/v1")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        assert client.list_models() == ["legacy-loaded"]
    finally:
        client.close()
