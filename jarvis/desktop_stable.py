from __future__ import annotations

import jarvis.app as jarvis_app
from jarvis.agent.core_orchestrator import JarvisCoreOrchestrator


def main() -> None:
    # Keep every cognitive feature, but keep heavy services out of the realtime
    # audio loop. The browser owns microphone, echo processing and playback.
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

    # Full transcript remains persistent on disk. The live prompt is deliberately
    # small so casual conversation does not pay a long prefill on every turn.
    jarvis_app.settings.conversation_max_messages = min(
        int(getattr(jarvis_app.settings, "conversation_max_messages", 14)),
        14,
    )
    jarvis_app.settings.core_consensus_min_complexity = max(
        int(getattr(jarvis_app.settings, "core_consensus_min_complexity", 4)),
        4,
    )

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
