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
from jarvis.tools.system import (
    get_clipboard,
    get_cpu_usage,
    get_ram_usage,
    get_system_information,
    get_volume,
    lock_screen,
    power_command,
    set_clipboard,
    set_timer,
    set_volume,
    show_notification,
)


def _xy_parameters() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
        "required": ["x", "y"],
        "additionalProperties": False,
    }


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    # Read-only system information.
    registry.register(ToolDefinition(
        name="get_cpu_usage",
        description="Legge l'utilizzo reale corrente della CPU del computer.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_cpu_usage,
    ))
    registry.register(ToolDefinition(
        name="get_ram_usage",
        description="Legge utilizzo, memoria disponibile e memoria totale della RAM.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_ram_usage,
    ))
    registry.register(ToolDefinition(
        name="get_system_information",
        description="Restituisce informazioni reali di base sul sistema operativo, disco e computer.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_system_information,
    ))
    registry.register(ToolDefinition(
        name="get_volume",
        description="Legge il volume audio corrente di Windows.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_volume,
    ))

    # Application/window operations.
    registry.register(ToolDefinition(
        name="open_application",
        description="Apre realmente un'applicazione sul computer Windows.",
        parameters={
            "type": "object",
            "properties": {"application": {"type": "string", "description": "Nome dell'applicazione."}},
            "required": ["application"],
            "additionalProperties": False,
        },
        handler=open_application,
        security=SecurityLevel.SAFE,
    ))
    registry.register(ToolDefinition(
        name="get_open_windows",
        description="Elenca i titoli delle finestre aperte sul desktop Windows.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_open_windows,
    ))
    registry.register(ToolDefinition(
        name="focus_window",
        description="Porta in primo piano una finestra già aperta usando parte del suo titolo.",
        parameters={
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        handler=focus_window,
    ))

    # Screen reading is read-only. Actions that can change the PC require confirmation.
    registry.register(ToolDefinition(
        name="read_screen_text",
        description="Legge il testo visibile sullo schermo Windows con OCR e restituisce testo e coordinate.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=read_screen_text,
    ))
    registry.register(ToolDefinition(
        name="find_text_on_screen",
        description="Cerca una scritta o un pulsante visibile sullo schermo e restituisce coordinate approssimative.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=find_text_on_screen,
    ))
    registry.register(ToolDefinition(
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
    ))
    registry.register(ToolDefinition(
        name="move_mouse",
        description="Sposta il cursore del mouse alle coordinate indicate.",
        parameters=_xy_parameters(),
        handler=move_mouse,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))
    registry.register(ToolDefinition(
        name="click_at",
        description="Fa clic alle coordinate indicate. Può usare left, right o double.",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "double"]},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        },
        handler=click_at,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))
    registry.register(ToolDefinition(
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
    ))
    registry.register(ToolDefinition(
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
    ))
    registry.register(ToolDefinition(
        name="take_screenshot",
        description="Salva uno screenshot PNG sul Desktop locale.",
        parameters={
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "additionalProperties": False,
        },
        handler=take_screenshot,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))

    # Guarded Windows system actions.
    registry.register(ToolDefinition(
        name="set_volume",
        description="Imposta il volume di Windows tra 0 e 100.",
        parameters={
            "type": "object",
            "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["level"],
            "additionalProperties": False,
        },
        handler=set_volume,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))
    registry.register(ToolDefinition(
        name="get_clipboard",
        description="Legge il testo presente negli appunti di Windows. Può contenere dati privati.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=get_clipboard,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))
    registry.register(ToolDefinition(
        name="set_clipboard",
        description="Sostituisce il testo presente negli appunti di Windows.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 10000}},
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=set_clipboard,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))
    registry.register(ToolDefinition(
        name="show_notification",
        description="Mostra una notifica locale di JARVIS su Windows.",
        parameters={
            "type": "object",
            "properties": {"title": {"type": "string"}, "message": {"type": "string"}},
            "required": ["title", "message"],
            "additionalProperties": False,
        },
        handler=show_notification,
    ))
    registry.register(ToolDefinition(
        name="set_timer",
        description="Imposta un timer locale che mostrerà una notifica alla scadenza.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "minimum": 1, "maximum": 604800},
                "message": {"type": "string"},
            },
            "required": ["seconds"],
            "additionalProperties": False,
        },
        handler=set_timer,
    ))
    registry.register(ToolDefinition(
        name="lock_screen",
        description="Blocca la sessione Windows corrente.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lock_screen,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))
    registry.register(ToolDefinition(
        name="power_command",
        description="Mette il PC in sospensione, lo riavvia oppure lo spegne. Richiede conferma esplicita.",
        parameters={
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["sleep", "restart", "shutdown"]}},
            "required": ["action"],
            "additionalProperties": False,
        },
        handler=power_command,
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))
    return registry
