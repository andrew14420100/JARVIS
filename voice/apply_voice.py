from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
PATCH_MARKER = "JARVIS_CUSTOM_CLONED_VOICE"


def _quote(value: str) -> str:
    return '"' + value.replace('"', "'") + '"'


def _rewrite_command(command: str, audio: Path, transcript: str) -> str:
    command = str(command or "").strip()
    if not command:
        return command

    flags_with_value = (
        "qwen3_tts_model_name",
        "qwen3_tts_speaker",
        "qwen3_tts_ref_audio",
        "qwen3_tts_ref_text",
        "qwen3_tts_ref_spk",
        "qwen3_tts_ref_rvq",
    )
    for flag in flags_with_value:
        pattern = re.compile(
            rf"(?<!\S)--{re.escape(flag)}(?:\s+|=)(?:\"[^\"]*\"|'[^']*'|\S+)",
            re.IGNORECASE,
        )
        command = pattern.sub("", command)

    command = re.sub(r"(?<!\S)--qwen3_tts_xvec_only(?=\s|$)", "", command, flags=re.IGNORECASE)
    command = " ".join(command.split())
    extra = (
        f" --qwen3_tts_model_name {MODEL}"
        f" --qwen3_tts_ref_audio {_quote(str(audio))}"
        f" --qwen3_tts_ref_text {_quote(transcript)}"
    )
    return command + extra


def _patch_install(repo: Path) -> bool:
    target = repo / "jarvis" / "realtime" / "local_server" / "install.py"
    text = target.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        return False

    old = '    tts_device = "cuda" if memory_source == "nvidia-smi" else "mps"\n    parts = [\n'
    new = (
        '    tts_device = "cuda" if memory_source == "nvidia-smi" else "mps"\n'
        '    # JARVIS_CUSTOM_CLONED_VOICE: root wrapper injects only the user voice.\n'
        '    voice_wav = os.environ.get("JARVIS_CUSTOM_VOICE_WAV", "").strip()\n'
        '    voice_text = os.environ.get("JARVIS_CUSTOM_VOICE_TEXT", "").strip()\n'
        '    parts = [\n'
    )
    if old not in text:
        raise RuntimeError("PersonalJarvis derive_launch_command layout changed; voice patch not applied.")
    text = text.replace(old, new, 1)

    old_speaker = '        "--qwen3_tts_speaker Aiden",\n'
    new_speaker = '        *([] if voice_wav else ["--qwen3_tts_speaker Aiden"]),\n'
    if old_speaker not in text:
        raise RuntimeError("PersonalJarvis Qwen3 speaker line changed; voice patch not applied.")
    text = text.replace(old_speaker, new_speaker, 1)

    anchor = '    ]\n    if brain.kind == "ollama":\n'
    inject = (
        '    ]\n'
        '    if voice_wav:\n'
        '        voice_path = Path(voice_wav).expanduser().resolve()\n'
        '        if not voice_path.is_file():\n'
        '            raise RuntimeError(f"JARVIS cloned voice file not found: {voice_path}")\n'
        '        if not voice_text:\n'
        '            raise RuntimeError("JARVIS_CUSTOM_VOICE_TEXT is empty")\n'
        '        safe_voice_text = voice_text.replace(chr(34), chr(39))\n'
        '        parts += [\n'
        f'            "--qwen3_tts_model_name {MODEL}",\n'
        '            f\'--qwen3_tts_ref_audio "{voice_path}"\',\n'
        '            f\'--qwen3_tts_ref_text "{safe_voice_text}"\',\n'
        '        ]\n'
        '    if brain.kind == "ollama":\n'
    )
    if anchor not in text:
        raise RuntimeError("PersonalJarvis launch-command anchor changed; voice patch not applied.")
    text = text.replace(anchor, inject, 1)
    target.write_text(text, encoding="utf-8")
    return True


def _sync_existing_config(repo: Path, audio: Path, transcript: str) -> bool:
    sys.path.insert(0, str(repo))
    try:
        from jarvis.core.config import load_config
        from jarvis.core.config_writer import set_local_realtime_launch_command
    except Exception:
        return False

    try:
        cfg = load_config()
        brain = getattr(cfg, "brain", None)
        providers = getattr(brain, "providers", {}) if brain is not None else {}
        provider = providers.get("local-realtime") if hasattr(providers, "get") else None
        command = str(getattr(provider, "launch_command", "") or "").strip()
        if not command:
            return False
        rewritten = _rewrite_command(command, audio, transcript)
        if rewritten == command:
            return False
        set_local_realtime_launch_command(rewritten)
        return True
    except Exception as exc:
        print(f"[VOICE] Existing config not rewritten: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--sync-config", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    audio = Path(args.audio).resolve()
    text_path = Path(args.text).resolve()
    if not audio.is_file():
        raise SystemExit(f"Voice audio not found: {audio}")
    if not text_path.is_file():
        raise SystemExit(f"Voice transcript not found: {text_path}")
    transcript = text_path.read_text(encoding="utf-8").strip()
    if not transcript:
        raise SystemExit("Voice transcript is empty")

    changed = _patch_install(repo)
    synced = _sync_existing_config(repo, audio, transcript) if args.sync_config else False
    print(
        "[VOICE] cloned voice ready · "
        f"source={'patched' if changed else 'already patched'} · "
        f"config={'updated' if synced else 'no existing command'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
