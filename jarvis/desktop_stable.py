from __future__ import annotations

import jarvis.app as jarvis_app
from jarvis.agent.stable_orchestrator import StableJarvisOrchestrator


def main() -> None:
    # Share one stable orchestrator between the desktop voice loop and FastAPI.
    if jarvis_app.orchestrator is None or not isinstance(
        jarvis_app.orchestrator, StableJarvisOrchestrator
    ):
        jarvis_app.orchestrator = StableJarvisOrchestrator(
            jarvis_app.settings,
            jarvis_app.client,
            jarvis_app.registry,
        )

    # Import after the shared agent has been installed: desktop.get_orchestrator
    # will now return the stable instance above.
    from jarvis import desktop

    # The wake listener already captures post-wake PCM concurrently. Waiting
    # 380 ms before handing it to STT was unnecessary and made the assistant
    # feel sluggish. 140 ms is enough to avoid the trigger tail while retaining
    # the first words after "Hey Jarvis".
    desktop.POST_WAKE_CAPTURE_DELAY_SECONDS = 0.14
    desktop.ACOUSTIC_GUARD_SECONDS = 0.18
    desktop.main()


if __name__ == "__main__":
    main()
