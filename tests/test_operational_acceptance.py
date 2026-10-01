from __future__ import annotations

import json
import time
from types import SimpleNamespace

import psutil

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.config.settings import Settings
from jarvis.core.state import JarvisState
from jarvis.monitoring.proactive import ProactiveMonitor
from jarvis.tools.registry import ToolDefinition, ToolRegistry
from jarvis.tools.security import SecurityLevel
import jarvis.tools.system as system_tools


class OperationalClient:
    """Deterministic model double that behaves like a tool-capable assistant."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve_model(self, configured_model=""):
        return configured_model or "jarvis-test-model"

    @staticmethod
    def _tool_call(name: str, arguments: dict, call_id: str):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments),
                    },
                }
            ],
        }

    def chat_completion(self, **kwargs):
        self.calls += 1
        messages = kwargs["messages"]
        last = messages[-1]

        if last.get("role") == "tool":
            payload = json.loads(last["content"])
            if payload.get("confirmation_required"):
                return {
                    "role": "assistant",
                    "content": "Signore, questa azione richiede la sua conferma.",
                    "tool_calls": [],
                }
            if "percent" in payload:
                return {
                    "role": "assistant",
                    "content": f"Signore, la CPU è al {payload['percent']} per cento.",
                    "tool_calls": [],
                }
            if payload.get("timer"):
                return {
                    "role": "assistant",
                    "content": "Timer impostato, signore.",
                    "tool_calls": [],
                }
            if payload.get("success") is False:
                return {
                    "role": "assistant",
                    "content": "Signore, l'operazione non è riuscita, ma sono ancora operativo.",
                    "tool_calls": [],
                }
            return {
                "role": "assistant",
                "content": "Operazione completata, signore.",
                "tool_calls": [],
            }

        if last.get("role") == "system" and "Risultato reale dello strumento" in str(last.get("content")):
            return {
                "role": "assistant",
                "content": "Confermato ed eseguito, signore.",
                "tool_calls": [],
            }

        user_messages = [m for m in messages if m.get("role") == "user"]
        text = str(user_messages[-1].get("content") or "").casefold() if user_messages else ""
        if "cpu" in text:
            return self._tool_call("fake_cpu", {}, "cpu_1")
        if "timer" in text:
            return self._tool_call("fake_timer", {"seconds": 10, "message": "Controllo completato"}, "timer_1")
        if "volume" in text:
            return self._tool_call("fake_volume", {"level": 30}, "volume_1")
        if "automazione guasta" in text:
            return self._tool_call("broken_automation", {}, "broken_1")
        if "tool inesistente" in text:
            return self._tool_call("missing_tool", {}, "missing_1")
        return {
            "role": "assistant",
            "content": "Certamente, signore. Sono operativo.",
            "tool_calls": [],
        }

    def close(self):
        pass


def _registry(events: list[tuple]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="fake_cpu",
        description="CPU sintetica per collaudo.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda: {"percent": 42},
    ))
    registry.register(ToolDefinition(
        name="fake_timer",
        description="Timer sintetico per collaudo.",
        parameters={
            "type": "object",
            "properties": {"seconds": {"type": "integer"}, "message": {"type": "string"}},
            "required": ["seconds"],
            "additionalProperties": False,
        },
        handler=lambda seconds, message="Timer completato": (
            events.append(("timer", seconds, message)) or
            {"success": True, "timer": True, "seconds": seconds, "message": message}
        ),
    ))
    registry.register(ToolDefinition(
        name="fake_volume",
        description="Volume sintetico protetto.",
        parameters={
            "type": "object",
            "properties": {"level": {"type": "integer"}},
            "required": ["level"],
            "additionalProperties": False,
        },
        handler=lambda level: events.append(("volume", level)) or {"success": True, "volume": level},
        security=SecurityLevel.CONFIRMATION_REQUIRED,
    ))

    def broken():
        raise RuntimeError("errore hardware simulato")

    registry.register(ToolDefinition(
        name="broken_automation",
        description="Automazione che fallisce per verificare la resilienza.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=broken,
    ))
    return registry


def _agent(events: list[tuple]) -> JarvisOrchestrator:
    return JarvisOrchestrator(
        Settings(
            model="jarvis-test-model",
            memory_enabled=False,
            openjarvis_enabled=False,
            max_agent_iterations=5,
        ),
        OperationalClient(),
        _registry(events),
    )


def test_realistic_conversation_tool_timer_confirmation_and_recovery_flow():
    events: list[tuple] = []
    agent = _agent(events)

    assert agent.process_message("Jarvis, controlla la CPU") == "Signore, la CPU è al 42 per cento."
    assert agent.state is JarvisState.SPEAKING

    assert agent.process_message("Imposta un timer") == "Timer impostato, signore."
    assert events == [("timer", 10, "Controllo completato")]

    protected = agent.process_message("Metti il volume al 30 per cento")
    assert "conferma" in protected.casefold()
    assert agent.pending_confirmation is not None
    assert not any(item[0] == "volume" for item in events)

    confirmed = agent.process_message("confermo")
    assert confirmed == "Confermato ed eseguito, signore."
    assert ("volume", 30) in events
    assert agent.pending_confirmation is None
    assert agent.state is JarvisState.SPEAKING

    failed = agent.process_message("Esegui automazione guasta")
    assert "ancora operativo" in failed.casefold()
    assert agent.state is JarvisState.SPEAKING

    missing = agent.process_message("Usa tool inesistente")
    assert "ancora operativo" in missing.casefold()
    assert agent.state is JarvisState.SPEAKING

    normal = agent.process_message("Come stai?")
    assert normal == "Certamente, signore. Sono operativo."
    assert agent.state is JarvisState.SPEAKING


def test_protected_automation_can_be_cancelled_without_execution():
    events: list[tuple] = []
    agent = _agent(events)
    response = agent.process_message("Metti il volume al 30 per cento")
    assert "conferma" in response.casefold()
    assert agent.pending_confirmation is not None

    assert agent.process_message("annulla") == "Operazione annullata."
    assert agent.pending_confirmation is None
    assert not any(item[0] == "volume" for item in events)
    assert agent.state is JarvisState.IDLE


def test_100_mixed_agent_automation_cycles_have_no_state_or_latency_growth():
    events: list[tuple] = []
    agent = _agent(events)
    started = time.perf_counter()
    for index in range(100):
        if index % 4 == 0:
            reply = agent.process_message("Controlla la CPU")
            assert "42" in reply
        elif index % 4 == 1:
            reply = agent.process_message("Imposta un timer")
            assert reply == "Timer impostato, signore."
        elif index % 4 == 2:
            reply = agent.process_message("Esegui automazione guasta")
            assert "ancora operativo" in reply.casefold()
        else:
            reply = agent.process_message("Dimmi se sei operativo")
            assert reply == "Certamente, signore. Sono operativo."
        assert agent.state is JarvisState.SPEAKING
    elapsed = time.perf_counter() - started
    assert elapsed < 4.0, f"100 operational cycles took {elapsed:.2f}s"


def test_timer_callback_notifies_and_removes_completed_timer(monkeypatch):
    created = []
    notifications = []

    class FakeTimer:
        def __init__(self, seconds, callback):
            self.seconds = seconds
            self.callback = callback
            self.daemon = False
            self.alive = False
            created.append(self)

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

        def fire(self):
            self.alive = False
            self.callback()

    monkeypatch.setattr(system_tools.threading, "Timer", FakeTimer)
    monkeypatch.setattr(
        system_tools,
        "show_notification",
        lambda title, message: notifications.append((title, message)) or {"success": True},
    )
    with system_tools._timers_lock:
        system_tools._timers.clear()

    result = system_tools.set_timer(1, "È ora di controllare JARVIS")
    assert result["success"] is True
    assert len(system_tools._timers) == 1
    assert created[0].daemon is True

    created[0].fire()
    assert notifications == [("JARVIS", "È ora di controllare JARVIS")]
    assert system_tools._timers == []


def test_proactive_monitor_emits_important_alerts_once_per_cooldown(monkeypatch):
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 99.0)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(percent=98.0))
    monkeypatch.setattr(psutil, "disk_usage", lambda _path: SimpleNamespace(percent=97.0))
    monkeypatch.setattr(ProactiveMonitor, "_gpu_temperature", staticmethod(lambda: 91.0))

    monitor = ProactiveMonitor(
        cooldown_seconds=300,
        cpu_percent=97,
        memory_percent=96,
        disk_percent=96,
        gpu_temp_c=88,
    )
    monitor._check_once()
    first = []
    while True:
        alert = monitor.pop()
        if alert is None:
            break
        first.append(alert)
    assert {item.key for item in first} == {"cpu", "memory", "disk", "gpu-temp"}
    assert all(item.message.startswith("Signore,") for item in first)

    monitor._check_once()
    assert monitor.pop() is None


def test_proactive_monitor_thread_start_stop_is_idempotent():
    monitor = ProactiveMonitor(poll_seconds=5.0)
    monitor._check_once = lambda: None  # type: ignore[method-assign]
    monitor.start()
    first_thread = monitor._thread
    assert first_thread is not None and first_thread.is_alive()
    monitor.start()
    assert monitor._thread is first_thread
    monitor.stop()
    assert not first_thread.is_alive()
