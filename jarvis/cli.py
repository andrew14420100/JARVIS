from __future__ import annotations

from jarvis.agent.orchestrator import JarvisOrchestrator
from jarvis.brain.lmstudio import LMStudioClient
from jarvis.config.settings import get_settings
from jarvis.tools.defaults import build_default_registry


def main() -> None:
    settings = get_settings()
    client = LMStudioClient(settings.lm_studio_base_url, settings.request_timeout_seconds)
    try:
        agent = JarvisOrchestrator(settings, client, build_default_registry())
        print(f"JARVIS 0.1 — modello: {agent.model}")
        print("Scrivi 'esci' per terminare.\n")
        while True:
            message = input("Tu > ").strip()
            if not message:
                continue
            if message.lower() in {"esci", "exit", "quit"}:
                break
            print(f"JARVIS > {agent.process_message(message)}\n")
    finally:
        client.close()


if __name__ == "__main__":
    main()
