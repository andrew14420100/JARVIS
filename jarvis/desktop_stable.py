from __future__ import annotations

import jarvis.app as jarvis_app
from jarvis.agent.core_orchestrator import JarvisCoreOrchestrator


def main() -> None:
    # Keep every cognitive feature built while the user was away, but let the
    # browser own realtime audio. On the target Windows/SB Katana machine this
    # path was visibly smoother than the later duplicate PortAudio pipeline.
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

    # Full transcript stays persistent, while the live prompt remains compact.
    jarvis_app.settings.conversation_max_messages = min(
        int(getattr(jarvis_app.settings, "conversation_max_messages", 16)),
        16,
    )
    jarvis_app.settings.core_consensus_min_complexity = max(
        int(getattr(jarvis_app.settings, "core_consensus_min_complexity", 4)),
        4,
    )

    # Local model first for lowest latency; free cloud routes remain fallbacks.
    jarvis_app.settings.lm_studio_fallback_enabled = True
    jarvis_app.settings.conversation_local_first = True

    if jarvis_app.orchestrator is None or not isinstance(
        jarvis_app.orchestrator, JarvisCoreOrchestrator
    ):
        jarvis_app.orchestrator = JarvisCoreOrchestrator(
            jarvis_app.settings,
            jarvis_app.client,
            jarvis_app.registry,
        )

    from jarvis import browser_runtime

    browser_runtime.main()


if __name__ == "__main__":
    main()
