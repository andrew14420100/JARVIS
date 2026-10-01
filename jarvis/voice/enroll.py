from __future__ import annotations

import argparse

from jarvis.config.settings import get_settings
from jarvis.voice.identity import SpeakerAuthenticator


def record_sample(seconds: float, device: str | int | None = None, sample_rate: int = 16000):
    import numpy as np
    import sounddevice as sd

    frames = int(sample_rate * max(4.0, float(seconds)))
    print("Parli normalmente per alcuni secondi. Registrazione in corso...")
    audio = sd.rec(
        frames,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Registra una voce autorizzata per JARVIS")
    parser.add_argument("name", help="Nome del profilo")
    parser.add_argument("--role", default="family", choices=["owner", "family", "trusted", "guest"])
    parser.add_argument("--seconds", type=float, default=12.0)
    args = parser.parse_args()

    settings = get_settings()
    authenticator = SpeakerAuthenticator(settings.speaker_profiles_dir, settings.speaker_match_threshold)
    device = settings.audio_input_device.strip() or None
    audio = record_sample(args.seconds, device=device)
    if not authenticator.enroll(args.name, args.role, audio, 16000):
        raise SystemExit("Campione troppo corto o non utilizzabile. Riprova parlando più vicino al microfono.")
    print(f"Profilo '{args.name}' registrato con ruolo '{args.role}'.")


if __name__ == "__main__":
    main()
