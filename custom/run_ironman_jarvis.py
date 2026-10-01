from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSONA_SOURCE = ROOT / "custom" / "jarvis_video_persona.md"


def apply_profile() -> None:
    """Apply the JARVIS-from-video persona without changing the underlying engine."""
    if not PERSONA_SOURCE.is_file():
        raise FileNotFoundError(f"Profilo JARVIS mancante: {PERSONA_SOURCE}")

    from jarvis.core import config as core_config

    data_dir = core_config.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    prompt_target = data_dir / "custom_system_prompt.md"

    persona = PERSONA_SOURCE.read_text(encoding="utf-8").strip() + "\n"
    current = ""
    try:
        current = prompt_target.read_text(encoding="utf-8")
    except FileNotFoundError:
        pass

    if current != persona:
        prompt_target.write_text(persona, encoding="utf-8", newline="\n")

    print("[JARVIS] Profilo video attivo: personalita' JARVIS, tono naturale e 'signore'.")


def main() -> int:
    apply_profile()
    from jarvis.__main__ import main as jarvis_main

    return int(jarvis_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
