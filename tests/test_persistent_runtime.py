from types import SimpleNamespace

from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator
from jarvis.monitoring.proactive import ProactiveMonitor
from jarvis.vision.screen import ScreenMonitor


def bare_agent(role: str = "owner") -> StableJarvisOrchestrator:
    agent = StableJarvisOrchestrator.__new__(StableJarvisOrchestrator)
    agent.current_speaker_role = role
    agent.current_speaker_name = "Test"
    agent.current_prosody = ""
    agent.client = SimpleNamespace()
    agent.settings = SimpleNamespace(local_model_priority="", vision_model_priority="")
    agent._conversation_local_model = ""
    agent._vision_local_model = ""
    return agent


def test_owner_can_execute_operational_requests():
    agent = bare_agent("owner")
    assert agent.role_allows_request("modifica il file di configurazione") is True


def test_family_can_chat_but_not_change_pc():
    agent = bare_agent("family")
    assert agent.role_allows_request("spiegami gli integrali") is True
    assert agent.role_allows_request("elimina il file dal pc") is False


def test_unknown_voice_cannot_issue_operational_request():
    agent = bare_agent("unknown")
    assert agent.role_allows_request("apri github e modifica il sito") is False


def test_recent_followup_is_addressed_without_wake_word():
    agent = bare_agent("owner")
    assert agent.is_addressed_to_jarvis(
        "No, aspetta, intendevo Milano",
        ambient_context="Jarvis: domani a Roma pioverà",
        seconds_since_reply=2.0,
    ) is True


def test_explicit_name_is_addressed_even_after_long_silence():
    agent = bare_agent("owner")
    assert agent.is_addressed_to_jarvis("Jarvis controlla questo", seconds_since_reply=7200.0) is True


def test_screen_monitor_only_attaches_for_visual_language():
    assert ScreenMonitor.relevant_query("guarda cosa c'è nella finestra a sinistra") is True
    assert ScreenMonitor.relevant_query("spiegami il teorema di Rolle") is False


def test_proactive_alert_queue_has_cooldown():
    monitor = ProactiveMonitor(cooldown_seconds=300)
    monitor._emit("gpu", "GPU calda")
    monitor._emit("gpu", "GPU ancora calda")
    first = monitor.pop()
    assert first is not None
    assert first.message == "GPU calda"
    assert monitor.pop() is None
