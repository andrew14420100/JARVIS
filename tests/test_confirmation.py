from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.config.settings import Settings
from jarvis.tools.registry import ToolDefinition, ToolRegistry
from jarvis.tools.security import SecurityLevel


class ConfirmationClient:
    def __init__(self):
        self.calls = 0

    def resolve_model(self, configured_model=""):
        return configured_model or "fake-model"

    def chat_completion(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_action",
                    "type": "function",
                    "function": {"name": "guarded_action", "arguments": '{"value": 7}'},
                }],
            }
        if self.calls == 2:
            return {"role": "assistant", "content": "Vuoi che proceda?", "tool_calls": []}
        return {"role": "assistant", "content": "Operazione completata.", "tool_calls": []}


def test_confirmation_required_action_executes_only_after_yes():
    executed = []

    def guarded_action(value: int):
        executed.append(value)
        return {"success": True, "value": value}

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="guarded_action",
        description="Test action",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
        handler=guarded_action,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))

    agent = JarvisOrchestrator(
        Settings(model="fake-model", memory_enabled=False),
        ConfirmationClient(),
        registry,
    )

    assert agent.process_message("Esegui azione") == "Vuoi che proceda?"
    assert executed == []
    assert agent.pending_confirmation is not None

    assert agent.process_message("confermo") == "Operazione completata."
    assert executed == [7]
    assert agent.pending_confirmation is None
