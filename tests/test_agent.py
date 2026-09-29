import json

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.config.settings import Settings
from jarvis.tools.defaults import build_default_registry


class FakeClient:
    def __init__(self):
        self.calls = 0

    def resolve_model(self, configured_model=""):
        return configured_model or "fake-qwen"

    def chat_completion(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_ram_usage", "arguments": "{}"},
                    }
                ],
            }
        tool_messages = [m for m in kwargs["messages"] if m.get("role") == "tool"]
        assert tool_messages
        payload = json.loads(tool_messages[-1]["content"])
        assert payload["total_gb"] > 0
        return {"role": "assistant", "content": "RAM controllata.", "tool_calls": []}


def test_agent_loops_tool_result_back_into_model():
    agent = JarvisOrchestrator(
        Settings(model="fake-qwen"),
        FakeClient(),
        build_default_registry(),
    )
    assert agent.process_message("Quanta RAM uso?") == "RAM controllata."
    assert agent.client.calls == 2
