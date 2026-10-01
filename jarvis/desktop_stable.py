from __future__ import annotations

import jarvis.app as jarvis_app
from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator


def main() -> None:
    # This runtime must always use the user's cloned local JARVIS voice.
    # If CosyVoice is unavailable we prefer silence + a clear diagnostic over
    # silently changing to another speaker/voice provider.
    jarvis_app.settings.tts_mode = "cosyvoice-local"
    jarvis_app.settings.cosyvoice_enabled = True
    jarvis_app.settings.cloud_tts_enabled = False
    jarvis_app.settings.cloud_tts_fallback_enabled = False
    jarvis_app.settings.tts_enabled = True

    # Share one hardened orchestrator between the desktop voice loop and FastAPI.
    if jarvis_app.orchestrator is None or not isinstance(
        jarvis_app.orchestrator, StableJarvisOrchestrator
    ):
        jarvis_app.orchestrator = StableJarvisOrchestrator(
            jarvis_app.settings,
            jarvis_app.client,
            jarvis_app.registry,
        )

    # The real microphone logs showed valid "Hey Jarvis" peaks around 0.31.
    # Keep the verified threshold below that while still removing the old 0.16
    # soft-trigger path that caused normal speech / the wake phrase itself to be
    # mistaken for a user command.
    jarvis_app.settings.wake_threshold = min(
        float(getattr(jarvis_app.settings, "wake_threshold", 0.28)),
        0.28,
    )

    # Import only after the shared stable agent/settings are installed.
    from jarvis import desktop

    # The wake listener captures post-wake PCM concurrently, so the old 380 ms
    # delay only made first response slower. Keep a short acoustic tail guard.
    desktop.POST_WAKE_CAPTURE_DELAY_SECONDS = 0.14
    desktop.ACOUSTIC_GUARD_SECONDS = 0.18
    desktop.main()


if __name__ == "__main__":
    main()
