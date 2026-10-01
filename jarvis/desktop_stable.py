from __future__ import annotations

import threading
import time

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

    # Hands-free means genuinely hands-free: the desktop runtime opens one
    # persistent conversation as soon as the microphone has been selected. The
    # wake detector remains alive only as a recovery/reopen mechanism if the
    # user explicitly closes the session. Do not speak a synthetic activation
    # acknowledgement at startup: JARVIS should simply be ready to hear the
    # first natural sentence.
    jarvis_app.settings.listener_activation_phrase = ""

    # Keep the complete transcript in SQLite but keep the live prompt compact.
    # This preserves long-term memory without making every casual voice turn pay
    # for a large multi-turn prefill.
    jarvis_app.settings.conversation_max_messages = min(
        int(getattr(jarvis_app.settings, "conversation_max_messages", 20)),
        20,
    )
    jarvis_app.settings.core_consensus_min_complexity = max(
        int(getattr(jarvis_app.settings, "core_consensus_min_complexity", 4)),
        4,
    )

    # Natural endpointing: a human pause around 300 ms should normally finish a
    # short turn, while the incomplete-phrase detector still gives hesitations a
    # second chance when a sentence clearly hangs.
    jarvis_app.settings.stt_silence_seconds = min(
        float(getattr(jarvis_app.settings, "stt_silence_seconds", 0.32)),
        0.32,
    )
    jarvis_app.settings.barge_in_min_seconds = min(
        float(getattr(jarvis_app.settings, "barge_in_min_seconds", 0.34)),
        0.34,
    )

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
    from jarvis.voice.wake_stable import WakeWordListener

    desktop.POST_WAKE_CAPTURE_DELAY_SECONDS = 0.10
    desktop.ACOUSTIC_GUARD_SECONDS = 0.10

    # The previous stable runtime stopped after printing "Wake detector" because
    # it intentionally waited for a wake phrase before invoking the conversation
    # callback. For the requested human-like mode, bootstrap that same guarded
    # callback automatically once the listener has selected a real microphone.
    # The normal wake listener continues running, so barge-in/echo handling is
    # unchanged and a closed session can still be reopened with Jarvis.
    original_run = WakeWordListener.run
    if not getattr(WakeWordListener, "_jarvis_autostart_patched", False):
        def run_with_autostart(self, callback, *args, **kwargs):
            bootstrap_started = threading.Event()

            def bootstrap_conversation() -> None:
                deadline = time.monotonic() + 15.0
                while (
                    self.selected_device is None
                    and not self._stop.is_set()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.025)
                if self.selected_device is None or self._stop.is_set():
                    print("[JARVIS] Avvio hands-free non riuscito: microfono non pronto.")
                    return
                if bootstrap_started.is_set():
                    return
                bootstrap_started.set()
                time.sleep(0.08)
                print("[JARVIS] Conversazione hands-free: ON · parli pure, non serve la wake word.")
                callback()

            threading.Thread(
                target=bootstrap_conversation,
                daemon=True,
                name="jarvis-handsfree-bootstrap",
            ).start()
            return original_run(self, callback, *args, **kwargs)

        WakeWordListener.run = run_with_autostart
        WakeWordListener._jarvis_autostart_patched = True

    desktop.main()


if __name__ == "__main__":
    main()
