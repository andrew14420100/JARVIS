from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

from jarvis.app import app, get_orchestrator
from jarvis.config.settings import get_settings
from jarvis.monitoring import ProactiveMonitor
from jarvis.vision import ScreenMonitor


def main() -> None:
    """Run JARVIS with the browser as the only realtime audio owner.

    The browser already proved smoother on the target Windows/SB Katana setup:
    it provides OS/browser echo cancellation, continuous SpeechRecognition and
    WebAudio PCM scheduling. Python keeps the cognitive core, memory, tools,
    screen context and proactive monitor, but it does not open a second input
    stream through PortAudio. That prevents microphone contention and duplicate
    endpointing while preserving the voice-only UI.
    """

    settings = get_settings()
    # The browser owns input/output. Mark desktop voice as disabled so App.js
    # does not overwrite browser LISTENING/SPEAKING state from /api/state.
    settings.voice_enabled = False

    agent = get_orchestrator()
    screen = ScreenMonitor(
        interval_seconds=settings.screen_capture_interval_seconds,
        max_width=settings.screen_max_width,
        jpeg_quality=settings.screen_jpeg_quality,
    )
    proactive = ProactiveMonitor(
        poll_seconds=settings.proactive_poll_seconds,
        cooldown_seconds=settings.proactive_cooldown_seconds,
        cpu_percent=settings.proactive_cpu_percent,
        memory_percent=settings.proactive_memory_percent,
        disk_percent=settings.proactive_disk_percent,
        gpu_temp_c=settings.proactive_gpu_temp_c,
    )

    if hasattr(agent, "attach_screen_monitor"):
        agent.attach_screen_monitor(screen)

    if settings.screen_monitor_enabled:
        if screen.start():
            print("[JARVIS] Visione schermo: ON · frame volatile in RAM")
        else:
            print(f"[JARVIS] Visione schermo non disponibile: {screen.last_error}")
    if settings.proactive_enabled:
        proactive.start()

    def open_ui() -> None:
        time.sleep(0.65)
        try:
            webbrowser.open("http://127.0.0.1:8000")
        except Exception:
            pass

    threading.Thread(target=open_ui, daemon=True, name="jarvis-browser-open").start()

    print("[JARVIS] Browser realtime online.")
    print("[JARVIS] Voce realtime: browser-native · nessun secondo microfono PortAudio.")
    print("[JARVIS] UI voice-only: nessun pulsante microfono, nessuna casella testo.")
    print("[JARVIS] JARVIS-Core/memoria/tool/schermo: ON")
    print("[JARVIS] UI: http://127.0.0.1:8000")
    print("[JARVIS] Ctrl+C per uscire.")

    try:
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
    finally:
        proactive.stop()
        screen.stop()
        try:
            agent.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
