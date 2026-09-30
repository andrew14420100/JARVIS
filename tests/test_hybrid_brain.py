from jarvis.brain.hybrid import HybridReasoner
from jarvis.config.settings import Settings
from jarvis.presence import PresenceContext


def test_simple_command_stays_on_fast_local_path():
    settings = Settings(
        openjarvis_enabled=True,
        deep_reasoning_enabled=True,
        deep_reasoning_min_score=4,
    )
    reasoner = HybridReasoner(settings)
    decision = reasoner.decide("Apri Spotify")
    assert decision.use_openjarvis is False
    assert decision.score < 4


def test_complex_multistep_request_routes_to_second_brain():
    settings = Settings(
        openjarvis_enabled=True,
        deep_reasoning_enabled=True,
        deep_reasoning_min_score=4,
    )
    reasoner = HybridReasoner(settings)
    decision = reasoner.decide(
        "Analizza tutto il progetto, trova il bug, correggi il codice e alla fine verifica che non ci siano crash."
    )
    assert decision.use_openjarvis is True
    assert decision.score >= 4


def test_presence_is_ephemeral_and_rejects_obvious_secrets():
    presence = PresenceContext(max_items=3, max_chars=1000)
    assert presence.add("Domani potremmo andare al mare", speaker="persona 1") is True
    assert presence.add("la mia password è supersegreta", speaker="persona 2") is False
    context = presence.as_context()
    assert "mare" in context
    assert "supersegreta" not in context
    presence.clear()
    assert presence.as_context() == ""
