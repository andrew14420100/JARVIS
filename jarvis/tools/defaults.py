from __future__ import annotations

from jarvis.tools.apps import open_application
from jarvis.tools.desktop import (
    click_at,
    find_text_on_screen,
    focus_window,
    get_open_windows,
    move_mouse,
    press_key,
    read_screen_text,
    scroll_screen,
    take_screenshot,
    type_text,
)
from jarvis.tools.registry import ToolDefinition, ToolRegistry
from jarvis.tools.security import SecurityLevel
from jarvis.tools.system import get_cpu_usage, get_ram_usage, get_system_information


def _xy_parameters() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["x", "y"],
        "additionalProperties": False,
    }


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
                        "description": "Nome dell'applicazione, ad esempio Blocco Note, Spotify o Visual Studio Code.",
                    }
                },
                "required": ["application"],
                "additionalProperties": False,
            },
            handler=open_application,
            security=SecurityLevel.SAFE,
        )
    )

    # Read-only / low-risk desktop vision tools.
    registry.register(
        ToolDefinition(
            name="read_screen_text",
            description="Legge il testo visibile sullo schermo Windows con OCR e restituisce testo e coordinate.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=read_screen_text,
            security=SecurityLevel.SAFE,
        )
    )
    registry.register(
        ToolDefinition(
            name="find_text_on_screen",
            description="Cerca una scritta o un pulsante visibile sullo schermo e restituisce le coordinate approssimative.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=find_text_on_screen,
            security=SecurityLevel.SAFE,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_open_windows",
            description="Elenca i titoli delle finestre aperte sul desktop Windows.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=get_open_windows,
            security=SecurityLevel.SAFE,
        )
    )
    registry.register(
        ToolDefinition(
            name="focus_window",
            description="Porta in primo piano una finestra già aperta usando parte del suo titolo.",
            parameters={
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
                "additionalProperties": False,
            },
            handler=focus_window,
            security=SecurityLevel.SAFE,
        )
    )
    registry.register(
        ToolDefinition(
            name="scroll_screen",
            description="Scorre la finestra attiva verso l'alto o il basso.",
            parameters={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down"]},
                    "amount": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["direction"],
                "additionalProperties": False,
            },
            handler=scroll_screen,
            security=SecurityLevel.SAFE,
        )
    )

    # State-changing controls require an explicit user confirmation turn.
    registry.register(
        ToolDefinition(
            name="move_mouse",
            description="Sposta il cursore del mouse alle coordinate indicate.",
            parameters=_xy_parameters(),
            handler=move_mouse,
            security=SecurityLevel.CONFIRMATION_REQUIRED,
        )
    )
    registry.register(
        ToolDefinition(
            name="click_at",
            description="Fa clic alle coordinate indicate. Può usare left, right o double.",
            parameters={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string", "enum": ["left", "right", "double"]},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
            handler=click_at,
            security=SecurityLevel.CONFIRMATION_REQUIRED,
        )
    )
    registry.register(
        ToolDefinition(
            name="type_text",
            description="Digita testo nella finestra attiva alla posizione corrente del cursore.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "maxLength": 4000}},
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=type_text,
            security=SecurityLevel.CONFIRMATION_REQUIRED,
        )
    )
    registry.register(
        ToolDefinition(
            name="press_key",
            description="Premi un tasto o una combinazione, ad esempio enter, alt+tab o ctrl+l.",
            parameters={
                "type": "object",
                "properties": {"keys": {"type": "string"}},
                "required": ["keys"],
                "additionalProperties": False,
            },
            handler=press_key,
            security=SecurityLevel.CONFIRMATION_REQUIRED,
        )
    )
    registry.register(
        ToolDefinition(
            name="take_screenshot",
            description="Salva uno screenshot PNG sul Desktop locale.",
            parameters={
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "additionalProperties": False,
            },
            handler=take_screenshot,
            security=SecurityLevel.CONFIRMATION_REQUIRED,
        )
    )
    return registry
