from __future__ import annotations

from jarvis.tools.apps import open_application
from jarvis.tools.registry import ToolDefinition, ToolRegistry
from jarvis.tools.security import SecurityLevel
from jarvis.tools.system import get_cpu_usage, get_ram_usage, get_system_information


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="get_cpu_usage",
            description="Legge l'utilizzo reale corrente della CPU del computer.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=get_cpu_usage,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_ram_usage",
            description="Legge utilizzo, memoria disponibile e memoria totale della RAM.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=get_ram_usage,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_system_information",
            description="Restituisce informazioni reali di base sul sistema operativo e sul computer.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=get_system_information,
        )
    )
    registry.register(
        ToolDefinition(
            name="open_application",
            description="Apre realmente un'applicazione sul computer Windows.",
            parameters={
                "type": "object",
                "properties": {
                    "application": {
                        "type": "string",
                        "description": "Nome dell'applicazione, ad esempio 'Blocco Note', 'Spotify' o 'Visual Studio Code'.",
                    }
                },
                "required": ["application"],
                "additionalProperties": False,
            },
            handler=open_application,
            security=SecurityLevel.SAFE,
        )
    )
    return registry
