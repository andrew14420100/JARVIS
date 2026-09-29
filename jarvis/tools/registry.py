from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from jarvis.tools.security import SecurityLevel, ToolBlockedError, ConfirmationRequiredError

ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    security: SecurityLevel = SecurityLevel.SAFE

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        if tool.security is SecurityLevel.BLOCKED:
            raise ToolBlockedError(f"Tool blocked by security policy: {name}")
        if tool.security is SecurityLevel.CONFIRMATION_REQUIRED and not confirmed:
            raise ConfirmationRequiredError(
                name,
                f"L'azione '{name}' richiede conferma esplicita.",
            )
        return tool.handler(**arguments)
