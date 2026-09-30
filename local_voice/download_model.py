from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


MODEL_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    print(f"[COSYVOICE] Download modello {MODEL_ID} -> {output}")
    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(output),
    )
    print("[COSYVOICE] Modello pronto.")


if __name__ == "__main__":
    main()
