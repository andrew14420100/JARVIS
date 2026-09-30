from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import uvicorn


JARVIS_SPEAKER_ID = "jarvis_cloned_voice"


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    speed: float = Field(default=1.0, ge=0.7, le=1.3)


def build_app(
    cosyvoice,
    speaker_id: str,
    model_name: str,
    device: str,
    precision: str,
) -> FastAPI:
    app = FastAPI(title="JARVIS Emergent Voice", version="1.4")
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
            "device": device,
            "precision": precision,
            "sample_rate": int(cosyvoice.sample_rate),
            "reference_voice_configured": True,
            "speaker_cached": True,
            "model_warm": True,
            "streaming": True,
        }

    @app.post("/tts")
    def tts(request: TTSRequest):
        clean = " ".join(request.text.strip().split())
        if not clean:
            raise HTTPException(status_code=400, detail="Testo vuoto")

        def generate():
            request_started = time.perf_counter()
            first_chunk_logged = False
            chunks = 0
            samples = 0
            try:
                output = cosyvoice.inference_zero_shot(
                    clean,
                    "",
                    "",
                    zero_shot_spk_id=speaker_id,
                    stream=True,
                    speed=request.speed,
                )
                for item in output:
                    audio = item.get("tts_speech")
                    if audio is None:
                        continue
                    arr = audio.detach().float().cpu().numpy().reshape(-1)
                    if not np.isfinite(arr).all():
                        raise RuntimeError("CosyVoice ha prodotto campioni audio non finiti")
                    arr = np.clip(arr, -1.0, 1.0)
                    chunks += 1
                    samples += int(arr.size)
                    if not first_chunk_logged:
                        first_chunk_logged = True
                        first_packet = time.perf_counter() - request_started
                        audio_seconds = arr.size / float(max(1, cosyvoice.sample_rate))
                        print(
                            f"[COSYVOICE] first-packet={first_packet:.2f}s · "
                            f"chunk_audio={audio_seconds:.2f}s · chars={len(clean)} · "
                            f"precision={precision}"
                        )
                    yield (arr * 32767.0).astype(np.int16).tobytes()
            except Exception as exc:
                print(f"[COSYVOICE] synthesis error: {exc}", file=sys.stderr)
                raise
            finally:
                if first_chunk_logged:
                    elapsed = time.perf_counter() - request_started
                    audio_seconds = samples / float(max(1, cosyvoice.sample_rate))
                    print(
                        f"[COSYVOICE] complete={elapsed:.2f}s · audio={audio_seconds:.2f}s · "
                        f"chunks={chunks}"
                    )

        return StreamingResponse(
            generate(),
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Sample-Rate": str(int(cosyvoice.sample_rate)),
                "X-Audio-Format": "pcm_s16le_mono",
                "X-JARVIS-TTS-Provider": "cosyvoice3-local",
                "X-JARVIS-TTS-Device": device,
                "X-JARVIS-TTS-Precision": precision,
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

    import torch
    from cosyvoice.cli.cosyvoice import AutoModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    use_fp16 = device == "cuda"
    precision = "fp16" if use_fp16 else "fp32"

    if device == "cuda":
        try:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass
        try:
            device_name = torch.cuda.get_device_name(0)
            capability = torch.cuda.get_device_capability(0)
            print(
                f"[COSYVOICE] Device: cuda · {device_name} · "
                f"sm_{capability[0]}{capability[1]} · torch {torch.__version__} · {precision}"
            )
        except Exception:
            device_name = "CUDA"
            print(f"[COSYVOICE] Device: cuda · {device_name} · torch {torch.__version__} · {precision}")
    else:
        print("[COSYVOICE] Device: CPU · fp32 · latenza più elevata")

    prompt_transcript = reference_text_file.read_text(encoding="utf-8").strip()
    if not prompt_transcript:
        raise SystemExit("La trascrizione della voce di riferimento è vuota.")

    prompt_text = f"You are a helpful assistant.<|endofprompt|>{prompt_transcript}"

    print(f"[COSYVOICE] Carico Fun-CosyVoice3-0.5B · precisione {precision}...")
    cosyvoice = AutoModel(
        model_dir=str(model_dir),
        load_trt=False,
        load_vllm=False,
        fp16=use_fp16,
    )

    print("[COSYVOICE] Precalcolo il profilo della voce JARVIS...")
    if not cosyvoice.add_zero_shot_spk(prompt_text, str(reference_audio), JARVIS_SPEAKER_ID):
        raise SystemExit("CosyVoice non è riuscito a registrare la voce di riferimento.")

    warm_started = time.perf_counter()
    first_warm_chunk = None
    try:
        for item in cosyvoice.inference_zero_shot(
            "Pronto.",
            "",
            "",
            zero_shot_spk_id=JARVIS_SPEAKER_ID,
            stream=True,
            speed=1.0,
        ):
            if first_warm_chunk is None and item.get("tts_speech") is not None:
                first_warm_chunk = time.perf_counter() - warm_started
        warm_elapsed = time.perf_counter() - warm_started
        first_label = f" · first-packet {first_warm_chunk:.2f}s" if first_warm_chunk is not None else ""
        print(f"[COSYVOICE] Warm-up completato in {warm_elapsed:.2f}s{first_label}")
    except Exception as exc:
        print(f"[COSYVOICE] Warm-up non riuscito, continuo comunque: {exc}", file=sys.stderr)

    print(
        f"[COSYVOICE] Pronto · speaker in memoria · "
        f"sample rate {cosyvoice.sample_rate} Hz · {precision}"
    )
    app = build_app(
        cosyvoice,
        JARVIS_SPEAKER_ID,
        "Fun-CosyVoice3-0.5B",
        device,
        precision,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
