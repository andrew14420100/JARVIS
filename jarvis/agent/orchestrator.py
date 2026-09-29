from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from jarvis.brain.lmstudio import LMStudioClient
from jarvis.config.settings import Settings
from jarvis.core.prompts import build_system_prompt
from jarvis.core.state import JarvisState
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.security import ConfirmationRequiredError, ToolBlockedError

StateCallback = Callable[[JarvisState], None]


class JarvisOrchestrator:
    def __init__(
        self,
        settings: Settings,
        client: LMStudioClient,
        registry: ToolRegistry,
        on_state_changed: StateCallback | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.registry = registry
        self.on_state_changed = on_state_changed
        self.state = JarvisState.IDLE
        self.model = client.resolve_model(settings.model)
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(settings.user_name)}
        ]

    def set_state(self, state: JarvisState) -> None:
        self.state = state
        if self.on_state_changed:
            self.on_state_changed(state)

    def reset_conversation(self) -> None:
        self.messages = [
            {"role": "system", "content": build_system_prompt(self.settings.user_name)}
        ]
        self.set_state(JarvisState.IDLE)

    def process_message(self, text: str) -> str:
        self.messages.append({"role": "user", "content": text})
        self.set_state(JarvisState.THINKING)

        try:
            for _ in range(self.settings.max_agent_iterations):
                assistant_message = self.client.chat_completion(
                    model=self.model,
                    messages=self.messages,
                    tools=self.registry.schemas(),
                )
                self.messages.append(assistant_message)

                tool_calls = assistant_message.get("tool_calls") or []
                if not tool_calls:
                    content = assistant_message.get("content") or ""
                    self.set_state(JarvisState.SPEAKING)
                    return content

                self.set_state(JarvisState.EXECUTING)
                for call in tool_calls:
                    function = call.get("function", {})
                    name = function.get("name", "")
                    raw_arguments = function.get("arguments") or "{}"
                    try:
                        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                        result = self.registry.execute(name, arguments)
                    except ConfirmationRequiredError as exc:
                        result = {
                            "success": False,
                            "confirmation_required": True,
                            "message": exc.message,
                        }
                    except (ToolBlockedError, KeyError, TypeError, ValueError) as exc:
                        result = {"success": False, "error": str(exc)}
                    except Exception as exc:
                        result = {"success": False, "error": f"Tool error: {exc}"}

                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                self.set_state(JarvisState.THINKING)

            self.set_state(JarvisState.ERROR)
            return "Ho interrotto l'operazione perché ho raggiunto il limite massimo di passaggi dell'agente."
        except Exception:
            self.set_state(JarvisState.ERROR)
            raise
