from __future__ import annotations

import jarvis.app as jarvis_app
from jarvis.agent.core_orchestrator import JarvisCoreOrchestrator


def main() -> None:
    # Stable runtime contract: always use the user's cloned local voice and the
    # persistent conversational features requested for desktop JARVIS. This also
    # protects upgraded installations whose old .env still contains legacy
    # values such as JARVIS_PRESENCE_ENABLED=false.
    jarvis_app.settings.tts_mode = "cosyvoice-local"
    jarvis_app.settings.cosyvoice_enabled = True
    jarvis_app.settings.cloud_tts_enabled = False
    jarvis_app.settings.cloud_tts_fallback_enabled = False
    jarvis_app.settings.tts_enabled = True

    jarvis_app.settings.persistent_session_enabled = True
    jarvis_app.settings.presence_enabled = True
    jarvis_app.settings.listener_barge_in_enabled = True
    jarvis_app.settings.speaker_auth_enabled = True
    jarvis_app.settings.prosody_enabled = True
    jarvis_app.settings.screen_monitor_enabled = True
    jarvis_app.settings.proactive_enabled = True
    jarvis_app.settings.memory_enabled = True
    jarvis_app.settings.memory_full_transcript = True
    jarvis_app.settings.memory_auto_semantic = True
    jarvis_app.settings.core_router_enabled = True
    jarvis_app.settings.core_consensus_enabled = True

    # The local model is the fastest and most reliable zero-cost brain when it is
    # available. Cloud-free providers remain fallbacks, never the only route.
    jarvis_app.settings.lm_studio_fallback_enabled = True
    jarvis_app.settings.conversation_local_first = True

    # Real microphone logs from the target PC showed valid hey_jarvis candidates
    # around 0.247 with a very low USB input level. Keep wake score as the main
    # confidence signal and use a tiny floor only to reject literal digital zero.
    jarvis_app.settings.wake_threshold = min(
        float(getattr(jarvis_app.settings, "wake_threshold", 0.22)),
        0.22,
    )
    jarvis_app.settings.wake_min_rms = min(
        float(getattr(jarvis_app.settings, "wake_min_rms", 0.00005)),
        0.00005,
    )

    # Share one federated JARVIS-Core between the desktop voice loop and FastAPI.
    # The user still experiences one assistant, while the core can route each
    # turn to the best available specialist model behind the scenes.
    if jarvis_app.orchestrator is None or not isinstance(
        jarvis_app.orchestrator, JarvisCoreOrchestrator
    ):
        jarvis_app.orchestrator = JarvisCoreOrchestrator(
            jarvis_app.settings,
            jarvis_app.client,
            jarvis_app.registry,
        )

    # Import only after shared settings/orchestrator are installed.
    from jarvis import desktop

    desktop.POST_WAKE_CAPTURE_DELAY_SECONDS = 0.14
    desktop.ACOUSTIC_GUARD_SECONDS = 0.18
    desktop.main()


if __name__ == "__main__":
    main()
