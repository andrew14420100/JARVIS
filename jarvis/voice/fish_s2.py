from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import io
import wave

import httpx


class FishS2Error(RuntimeError):
    """Raised when the public Fish Audio S2 Pro service cannot synthesize audio."""


@dataclass(slots=True)
class FishS2Audio:
    data: bytes
    media_type: str = "audio/wav"
    provider: str = "fish-audio-s2-pro-zero"


class FishS2CloudTTS:
    """Thin adapter around the public Fish Audio S2 Pro Hugging Face Space.

    The model runs on Hugging Face ZeroGPU, not on the JARVIS host.  The Space is
    public and can be called through Gradio's generated API.  A Hugging Face token
    is optional; if one is provided it is used only for the public Space request.
    """

    DEFAULT_SPACE = "artificialguybr/fish-s2-pro-zero"
    API_NAME = "/tts_inference"

    def __init__(
        self,
        *,
        space_id: str = DEFAULT_SPACE,
        hf_token: str = "",
        style_prompt: str = "[low voice] [calm professional tone]",
    ) -> None:
        self.space_id = space_id.strip() or self.DEFAULT_SPACE
        self.hf_token = hf_token.strip()
        self.style_prompt = style_prompt.strip()
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from gradio_client import Client
        except ImportError as exc:  # pragma: no cover - deployment configuration
            raise FishS2Error(
                "gradio_client non è installato. Installa le dipendenze backend aggiornate."
            ) from exc

        kwargs: dict[str, Any] = {"download_files": True}
        if self.hf_token:
            kwargs["token"] = self.hf_token
        try:
            self._client = Client(self.space_id, **kwargs)
        except Exception as exc:  # pragma: no cover - network/service dependent
            raise FishS2Error(f"Impossibile collegarsi a Fish Audio S2 Pro: {exc}") from exc
        return self._client

    def _styled_text(self, text: str) -> str:
        clean = " ".join(str(text or "").strip().split())
        if not clean:
            raise FishS2Error("Testo vuoto.")
        if len(clean) > 1800:
            clean = clean[:1800].rsplit(" ", 1)[0] + "…"
        if clean.startswith("[") or not self.style_prompt:
            return clean
        return f"{self.style_prompt} {clean}"

    @staticmethod
    def _bytes_from_url(url: str) -> bytes:
        try:
            response = httpx.get(url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            raise FishS2Error(f"Impossibile scaricare l'audio generato: {exc}") from exc

    @staticmethod
    def _wav_from_samples(sample_rate: int, samples: Any) -> bytes:
        """Best-effort support for clients returning (sample_rate, samples)."""
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - gradio usually returns a file
            raise FishS2Error("Output audio non compatibile e numpy non disponibile.") from exc

        arr = np.asarray(samples)
        if arr.ndim > 1:
            arr = arr.reshape(-1)
        if arr.dtype.kind == "f":
            arr = (arr.clip(-1.0, 1.0) * 32767.0).astype(np.int16)
        elif arr.dtype != np.int16:
            arr = arr.astype(np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(int(sample_rate))
            wav_file.writeframes(arr.tobytes())
        return buffer.getvalue()

    def _normalize_result(self, result: Any) -> FishS2Audio:
        if isinstance(result, (list, tuple)) and len(result) == 1:
            result = result[0]

        if isinstance(result, (list, tuple)) and len(result) == 2:
            first, second = result
            if isinstance(first, (int, float)) and not isinstance(second, (str, bytes, Path)):
                return FishS2Audio(self._wav_from_samples(int(first), second))

        if isinstance(result, bytes):
            return FishS2Audio(result)

        path_value: str | None = None
        url_value: str | None = None
        if isinstance(result, (str, Path)):
            path_value = str(result)
        elif isinstance(result, dict):
            path_value = result.get("path") or result.get("name")
            url_value = result.get("url")
        else:
            path_value = getattr(result, "path", None)
            url_value = getattr(result, "url", None)

        if path_value:
            path = Path(path_value)
            if path.is_file():
                media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
                return FishS2Audio(path.read_bytes(), media_type=media_type)
            if path_value.startswith(("http://", "https://")):
                return FishS2Audio(self._bytes_from_url(path_value))

        if url_value:
            return FishS2Audio(self._bytes_from_url(str(url_value)))

        raise FishS2Error(f"Formato audio Fish S2 non riconosciuto: {type(result).__name__}")

    def synthesize(self, text: str) -> FishS2Audio:
        client = self._get_client()
        styled = self._styled_text(text)
        arguments = (
            styled,
            None,   # reference audio: optional for the public preview
            "",     # reference transcript
            1024,   # max_new_tokens
            200,    # chunk_length
            0.70,   # top_p
            1.20,   # repetition_penalty
            0.70,   # temperature
        )

        errors: list[str] = []
        # Current Space exposes /tts_inference. Keep an fn_index fallback so a
        # harmless Gradio endpoint rename does not immediately break JARVIS.
        try:
            result = client.predict(*arguments, api_name=self.API_NAME)
            return self._normalize_result(result)
        except Exception as exc:  # pragma: no cover - network/service dependent
            errors.append(str(exc))

        try:
            api = client.view_api(return_format="dict") or {}
            named = api.get("named_endpoints") or {}
            for endpoint_name, info in named.items():
                parameters = info.get("parameters") or [] if isinstance(info, dict) else []
                if len(parameters) == 8:
                    result = client.predict(*arguments, api_name=endpoint_name)
                    return self._normalize_result(result)
        except Exception as exc:  # pragma: no cover - network/service dependent
            errors.append(str(exc))

        raise FishS2Error(
            "Fish Audio S2 Pro è temporaneamente non disponibile o in coda. "
            + " | ".join(error for error in errors if error)
        )

    def status(self) -> dict[str, object]:
        return {
            "provider": "fish-audio-s2-pro-zero",
            "space": self.space_id,
            "remote": True,
            "requires_local_gpu": False,
            "reference_voice_configured": False,
        }
