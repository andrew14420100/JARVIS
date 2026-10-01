from __future__ import annotations

import jarvis.app as jarvis_app
from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator


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

    # Share one hardened orchestrator between the desktop voice loop and FastAPI.
    if jarvis_app.orchestrator is None or not isinstance(
        jarvis_app.orchestrator, StableJarvisOrchestrator
    ):
        jarvis_app.orchestrator = StableJarvisOrchestrator(
            jarvis_app.settings,
            jarvis_app.client,
            jarvis_app.registry,
        )

    # Real microphone logs showed valid "Hey Jarvis" peaks around 0.31.
    jarvis_app.settings.wake_threshold = min(
        float(getattr(jarvis_app.settings, "wake_threshold", 0.28)),
        0.28,
    )

    # Import only after shared settings/orchestrator are installed.
    from jarvis import desktop

    desktop.POST_WAKE_CAPTURE_DELAY_SECONDS = 0.14
    desktop.ACOUSTIC_GUARD_SECONDS = 0.18
    desktop.main()


if __name__ == "__main__":
    main()
