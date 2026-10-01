from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class SpeakerMatch:
    name: str
    role: str
    score: float
    authorized: bool


class SpeakerAuthenticator:
    """Small local speaker-profile matcher for conversational authorization.

    The feature extractor is intentionally lightweight so it can run on CPU
    without loading another neural model. It is useful as an identity signal,
    not as a banking-grade biometric; destructive actions still require the
    existing explicit confirmation layer.
    """

    def __init__(self, profiles_dir: str, threshold: float = 0.78) -> None:
        self.root = Path(profiles_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.threshold = max(0.4, min(0.99, float(threshold)))
        self._lock = threading.RLock()

    @staticmethod
    def _vector(audio, sample_rate: int = 16000) -> list[float]:
        import numpy as np

        x = np.asarray(audio, dtype=np.float32).reshape(-1)
        if x.size < max(1600, sample_rate // 4):
            return []
        x = x[np.isfinite(x)]
        if x.size < sample_rate // 4:
            return []
        peak = float(np.max(np.abs(x))) or 1.0
        x = x / peak
        x = x - float(np.mean(x))

        frame = max(256, int(sample_rate * 0.032))
        hop = max(128, frame // 2)
        window = np.hanning(frame).astype(np.float32)
        nfft = 1
        while nfft < frame:
            nfft *= 2
        spectra: list[np.ndarray] = []
        zcr: list[float] = []
        for start in range(0, max(1, x.size - frame + 1), hop):
            chunk = x[start:start + frame]
            if chunk.size != frame:
                continue
            rms = float(np.sqrt(np.mean(chunk * chunk)))
            if rms < 0.015:
                continue
            mag = np.abs(np.fft.rfft(chunk * window, n=nfft)).astype(np.float32)
            mag = np.log1p(mag)
            # Compress the spectrum to fixed-width bands. This mostly captures
            # vocal-tract shape while discarding exact words.
            bands = np.array_split(mag[2:], 32)
            spectra.append(np.asarray([float(np.mean(b)) for b in bands], dtype=np.float32))
            zcr.append(float(np.mean(np.abs(np.diff(np.signbit(chunk)).astype(np.float32)))))
        if len(spectra) < 3:
            return []
        matrix = np.vstack(spectra)
        mean = np.mean(matrix, axis=0)
        std = np.std(matrix, axis=0)
        features = np.concatenate([
            mean,
            std,
            np.asarray([
                float(np.mean(zcr)),
                float(np.std(zcr)),
                float(np.sqrt(np.mean(x * x))),
            ], dtype=np.float32),
        ])
        norm = float(np.linalg.norm(features))
        if not math.isfinite(norm) or norm <= 1e-8:
            return []
        return (features / norm).astype(float).tolist()

    @staticmethod
    def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
        aa = list(a)
        bb = list(b)
        if not aa or len(aa) != len(bb):
            return 0.0
        dot = sum(x * y for x, y in zip(aa, bb))
        na = math.sqrt(sum(x * x for x in aa))
        nb = math.sqrt(sum(y * y for y in bb))
        if na <= 1e-9 or nb <= 1e-9:
            return 0.0
        return float(dot / (na * nb))

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = "".join(ch for ch in str(name or "") if ch.isalnum() or ch in "-_ ").strip()
        return cleaned[:64] or "speaker"

    def profile_names(self) -> list[str]:
        with self._lock:
            return sorted(path.stem for path in self.root.glob("*.json"))

    def has_profiles(self) -> bool:
        return bool(self.profile_names())

    def enroll(self, name: str, role: str, audio, sample_rate: int = 16000) -> bool:
        vector = self._vector(audio, sample_rate)
        if not vector:
            return False
        safe_name = self._safe_name(name)
        path = self.root / f"{safe_name}.json"
        with self._lock:
            vectors: list[list[float]] = []
            if path.is_file():
                try:
                    old = json.loads(path.read_text(encoding="utf-8"))
                    vectors = [list(map(float, item)) for item in old.get("samples", [])][-7:]
                except Exception:
                    vectors = []
            vectors.append(vector)
            payload = {
                "name": safe_name,
                "role": str(role or "guest")[:32],
                "samples": vectors[-8:],
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def identify(self, audio, sample_rate: int = 16000) -> SpeakerMatch:
        vector = self._vector(audio, sample_rate)
        if not vector:
            return SpeakerMatch("", "unknown", 0.0, False)
        best = SpeakerMatch("", "unknown", 0.0, False)
        with self._lock:
            paths = list(self.root.glob("*.json"))
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                scores = [self._cosine(vector, sample) for sample in payload.get("samples", [])]
                if not scores:
                    continue
                # Multiple enrollment clips improve stability; use the strongest
                # match and a small reward for agreement across samples.
                score = max(scores)
                if len(scores) > 1:
                    score = 0.8 * score + 0.2 * (sum(scores) / len(scores))
                if score > best.score:
                    best = SpeakerMatch(
                        str(payload.get("name") or path.stem),
                        str(payload.get("role") or "guest"),
                        float(score),
                        bool(score >= self.threshold),
                    )
            except Exception:
                continue
        return best
