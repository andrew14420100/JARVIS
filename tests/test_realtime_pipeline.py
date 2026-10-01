import httpx

from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator
from jarvis.brain.cloud import CloudAIClient
from jarvis.brain.lmstudio import LMStudioClient
from jarvis.config.settings import Settings
from jarvis.voice.cosyvoice_proxy import CosyVoiceProxyTTS


class EmptyRegistry:
    def schemas(self):
        return []

    def execute(self, *_args, **_kwargs):
        raise AssertionError("No tool should execute in this test")


class StreamClient:
    def resolve_model(self, configured_model=""):
        return configured_model or "qwen-local"

    def can_stream_chat(self, **_kwargs):
        return True

    def chat_completion_stream(self, **_kwargs):
        yield "Ciao"
        yield ", signore."

    def chat_completion(self, **_kwargs):
        return {"role": "assistant", "content": "fallback", "tool_calls": []}


def test_lmstudio_streams_sse_deltas():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = (
            'data: {"choices":[{"delta":{"content":"Ciao"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":", signore."}}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, text=body)

    client = LMStudioClient("http://lm.test/v1")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        chunks = list(
            client.chat_completion_stream(
                model="qwen",
                messages=[{"role": "user", "content": "ciao"}],
            )
        )
    finally:
        client.close()
    assert chunks == ["Ciao", ", signore."]


def test_lmstudio_keeps_likely_tool_turns_on_guarded_path():
    client = LMStudioClient("http://lm.test/v1")
    try:
        assert client.can_stream_chat(
            messages=[{"role": "user", "content": "Come stai?"}],
            tools=[{"type": "function"}],
        )
        assert not client.can_stream_chat(
            messages=[{"role": "user", "content": "Apri il browser"}],
            tools=[{"type": "function"}],
        )
    finally:
        client.close()


def test_cloud_client_can_run_only_from_local_streaming_fallback():
    class FakeLocal:
        def list_models(self):
            return ["qwen-local"]

        def resolve_model(self, _configured=""):
            return "qwen-local"

        def chat_completion_stream(self, **_kwargs):
            yield "Locale"
            yield " pronto"

        def chat_completion(self, **_kwargs):
            return {"role": "assistant", "content": "Locale pronto", "tool_calls": []}

        def close(self):
            pass

    client = CloudAIClient(local_fallback_enabled=True)
    real_local = client._local_fallback
    if real_local is not None:
        real_local.close()
    client._local_fallback = FakeLocal()
    try:
        assert client.resolve_model("") == "qwen-local"
        assert client.list_models() == ["qwen-local"]
        chunks = list(
            client.chat_completion_stream(
                model="qwen-local",
                messages=[{"role": "user", "content": "ciao"}],
            )
        )
        assert chunks == ["Locale", " pronto"]
        assert client.last_provider == "lmstudio-local-fallback"
    finally:
        client.close()


def test_stream_interruption_keeps_history_valid():
    agent = StableJarvisOrchestrator(
        Settings(
            model="qwen-local",
            memory_enabled=False,
            openjarvis_enabled=False,
            conversation_max_messages=8,
        ),
        StreamClient(),
        EmptyRegistry(),
    )
    stream = agent.process_message_stream("Dimmi qualcosa")
    assert next(stream) == "Ciao"
    stream.close()
    assert agent.messages[-1]["role"] == "assistant"
    assert agent.messages[-1]["content"] == "Ciao"


def test_history_is_bounded_across_long_voice_session():
    agent = StableJarvisOrchestrator(
        Settings(
            model="qwen-local",
            memory_enabled=False,
            openjarvis_enabled=False,
            conversation_max_messages=8,
        ),
        StreamClient(),
        EmptyRegistry(),
    )
    for index in range(20):
        assert "".join(agent.process_message_stream(f"Turno {index}")) == "Ciao, signore."
    assert len(agent.messages) <= 9
    assert agent.messages[0]["role"] == "system"
    assert agent.messages[1]["role"] == "user"


def test_cosyvoice_first_live_packet_is_small():
    packets = list(
        CosyVoiceProxyTTS._segments_from_live_text(
            iter(["Certamente signore, controllo subito la situazione e le rispondo."])
        )
    )
    assert packets
    assert len(packets[0]) <= 40
