from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    speed: float = Field(default=1.0, ge=0.7, le=1.3)


def build_app(cosyvoice, prompt_text: str, prompt_speech_16k, model_name: str) -> FastAPI:
    app = FastAPI(title="JARVIS Local Voice", version="1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {
            "ok": True,
            "provider": "cosyvoice3-local",
            "model": model_name,
            "sample_rate": int(cosyvoice.sample_rate),
            "reference_voice_configured": True,
            "streaming": True,
        }

    @app.post("/tts")
    def tts(request: TTSRequest):
        clean = " ".join(request.text.strip().split())
        if not clean:
            raise HTTPException(status_code=400, detail="Testo vuoto")

        def generate():
            try:
                output = cosyvoice.inference_zero_shot(
                    clean,
                    prompt_text,
                    prompt_speech_16k,
                    stream=True,
                    speed=request.speed,
                )
                for item in output:
                    audio = item.get("tts_speech")
                    if audio is None:
                        continue
                    arr = audio.detach().cpu().numpy().reshape(-1)
                    arr = np.clip(arr, -1.0, 1.0)
                    yield (arr * 32767.0).astype(np.int16).tobytes()
            except Exception as exc:
                print(f"[COSYVOICE] synthesis error: {exc}", file=sys.stderr)
                raise

        return StreamingResponse(
            generate(),
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Sample-Rate": str(int(cosyvoice.sample_rate)),
                "X-Audio-Format": "pcm_s16le_mono",
                "X-JARVIS-TTS-Provider": "cosyvoice3-local",
            },
        )

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cosyvoice-repo", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--reference-audio", required=True)
    parser.add_argument("--reference-text", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    repo = Path(args.cosyvoice_repo).resolve()
    model_dir = Path(args.model_dir).resolve()
    reference_audio = Path(args.reference_audio).resolve()
    reference_text_file = Path(args.reference_text).resolve()

    for path, label in (
        (repo, "repository CosyVoice"),
        (model_dir, "modello CosyVoice"),
        (reference_audio, "audio di riferimento"),
        (reference_text_file, "trascrizione della voce"),
    ):
        if not path.exists():
            raise SystemExit(f"Manca {label}: {path}")

    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "third_party" / "Matcha-TTS"))

    from cosyvoice.cli.cosyvoice import AutoModel
    from cosyvoice.utils.file_utils import load_wav

    prompt_transcript = reference_text_file.read_text(encoding="utf-8").strip()
    if not prompt_transcript:
        raise SystemExit("La trascrizione della voce di riferimento è vuota.")

    # CosyVoice 3 uses the prompt prefix below in its official zero-shot examples.
    prompt_text = f"You are a helpful assistant.<|endofprompt|>{prompt_transcript}"
    prompt_speech_16k = load_wav(str(reference_audio), 16000)

    print("[COSYVOICE] Carico Fun-CosyVoice3-0.5B-2512...")
    cosyvoice = AutoModel(model_dir=str(model_dir))
    print(f"[COSYVOICE] Pronto · sample rate {cosyvoice.sample_rate} Hz")

    app = build_app(
        cosyvoice,
        prompt_text,
        prompt_speech_16k,
        "Fun-CosyVoice3-0.5B-2512",
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
