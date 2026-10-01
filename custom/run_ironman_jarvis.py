from __future__ import annotations

import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSONA_SOURCE = ROOT / "custom" / "jarvis_video_persona.md"
VOICE_SOURCE = ROOT / "custom" / "jarvis_reference.mp3"

VOICE_REFERENCE_TEXT = (
    "Ciao, che fai? Buongiorno signore, ho terminato il controllo dei sistemi. "
    "Per il momento non risulta nulla di urgente. Direi che possiamo riprendere "
    "con calma da dove avevamo lasciato. Naturalmente, se preferisce occuparsi "
    "prima di qualcos'altro, mi adeguo. Ah, e questa volta cercherò di evitare "
    "sorprese. Almeno quelle evitabili."
)

_VALUE_FLAGS = (
    "--qwen3_tts_model_name",
    "--qwen3_tts_speaker",
    "--qwen3_tts_ref_audio",
    "--qwen3_tts_ref_text",
    "--qwen3_tts_language",
)


def _value_flag_pattern(flag: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<!\S){re.escape(flag)}(?:\s+|=)(?:\"[^\"]*\"|'[^']*'|\S+)",
        re.IGNORECASE,
    )


def _remove_value_flag(command: str, flag: str) -> str:
    return _value_flag_pattern(flag).sub("", command)


def _set_value_flag(command: str, flag: str, value: str) -> str:
    replacement = f"{flag} {value}"
    pattern = _value_flag_pattern(flag)
    if pattern.search(command):
        return pattern.sub(replacement, command, count=1)
    return f"{command.rstrip()} {replacement}"


def _remove_bool_flag(command: str, flag: str) -> str:
    return re.sub(
        rf"(?<!\S){re.escape(flag)}(?=\s|$)",
        "",
        command,
        flags=re.IGNORECASE,
    )


def _quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def _rewrite_voice_command(command: str, voice_path: Path) -> str:
    """Force the managed Qwen3-TTS lane to use the user's JARVIS voice clone."""
    command = (command or "").strip()
    if not command:
        return command

    command = _set_value_flag(command, "--tts", "qwen3")
    for flag in _VALUE_FLAGS:
        command = _remove_value_flag(command, flag)
    command = _remove_bool_flag(command, "--qwen3_tts_xvec_only")

    additions = (
        "--qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        f"--qwen3_tts_ref_audio {_quote(str(voice_path))}",
        f"--qwen3_tts_ref_text {_quote(VOICE_REFERENCE_TEXT)}",
        "--qwen3_tts_language auto",
        "--qwen3_tts_xvec_only",
    )
    cleaned = re.sub(r"\s{2,}", " ", command).strip()
    return cleaned + " " + " ".join(additions)


def _install_profile_files() -> Path:
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

    voice_dir = data_dir / "voices"
    voice_dir.mkdir(parents=True, exist_ok=True)
    voice_target = voice_dir / "jarvis_reference.mp3"
    if not voice_target.exists() or voice_target.stat().st_size != VOICE_SOURCE.stat().st_size:
        shutil.copy2(VOICE_SOURCE, voice_target)

    return voice_target.resolve()


def _rewrite_existing_managed_command(voice_path: Path) -> None:
    """Upgrade an already-installed local realtime server without reinstalling it."""
    from jarvis.core import config as core_config
    from jarvis.core.config_writer import set_local_realtime_launch_command

    config_path = core_config.resolve_config_path()
    if not config_path.is_file():
        return

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        return

    brain = raw.get("brain")
    if not isinstance(brain, dict):
        return
    providers = brain.get("providers")
    if not isinstance(providers, dict):
        return
    local = providers.get("local-realtime")
    if not isinstance(local, dict):
        return
    command = str(local.get("launch_command") or "").strip()
    if not command or "speech-to-speech" not in command.lower():
        return

    rewritten = _rewrite_voice_command(command, voice_path)
    if rewritten != command:
        set_local_realtime_launch_command(rewritten, path=config_path)


def _patch_future_managed_installs(voice_path: Path) -> None:
    """Keep PersonalJarvis' installer intact while changing only its TTS voice flags."""
    from jarvis.realtime.local_server import install

    original = install.derive_launch_command
    if getattr(original, "_jarvis_video_profile", False):
        return

    def derive_launch_command(brain, *, memory_source: str):
        command = original(brain, memory_source=memory_source)
        return _rewrite_voice_command(command, voice_path)

    derive_launch_command._jarvis_video_profile = True  # type: ignore[attr-defined]
    install.derive_launch_command = derive_launch_command


def apply_profile() -> None:
    if not PERSONA_SOURCE.is_file():
        raise FileNotFoundError(f"Profilo JARVIS mancante: {PERSONA_SOURCE}")
    if not VOICE_SOURCE.is_file():
        raise FileNotFoundError(f"Voce JARVIS mancante: {VOICE_SOURCE}")

    voice_path = _install_profile_files()
    _rewrite_existing_managed_command(voice_path)
    _patch_future_managed_installs(voice_path)
    print("[JARVIS] Profilo video attivo: personalita' JARVIS + voce clonata locale.")


def main() -> int:
    apply_profile()
    from jarvis.__main__ import main as jarvis_main

    return int(jarvis_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
