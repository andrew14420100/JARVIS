from __future__ import annotations

import jarvis.app as jarvis_app
from jarvis.agent.core_orchestrator import JarvisCoreOrchestrator


def main() -> None:
    # The stable desktop runtime is now genuinely conversational: one persistent
    # microphone stream, no wake gate, local cloned voice, permanent memory and
    # the federated JARVIS-Core behind one identity.
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

    # Keep long-term memory on disk, but keep the live prompt small so casual
    # conversation does not pay a large prefill cost every turn.
    jarvis_app.settings.conversation_max_messages = min(
        int(getattr(jarvis_app.settings, "conversation_max_messages", 16)),
        16,
    )
    jarvis_app.settings.core_consensus_min_complexity = max(
        int(getattr(jarvis_app.settings, "core_consensus_min_complexity", 4)),
        4,
    )

    # Human conversation endpointing. The full-duplex mic remains open after the
    # turn, so there is no device reopen penalty when the user continues.
    jarvis_app.settings.stt_silence_seconds = min(
        float(getattr(jarvis_app.settings, "stt_silence_seconds", 0.28)),
        0.28,
    )
    jarvis_app.settings.barge_in_min_seconds = min(
        float(getattr(jarvis_app.settings, "barge_in_min_seconds", 0.28)),
        0.28,
    )

    # Local first gives the lowest first-token latency. Free cloud routes remain
    # fallbacks if the local server/model is unavailable.
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

    # Import after the shared settings/orchestrator are installed so FastAPI and
    # the voice runtime truly share one JARVIS identity and one conversation.
    from jarvis import desktop_realtime

    desktop_realtime.main()


if __name__ == "__main__":
    main()
