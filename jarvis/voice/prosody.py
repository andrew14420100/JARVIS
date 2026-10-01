from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ProsodySnapshot:
    label: str
    rms: float
    zero_crossing_rate: float
    dynamic_range: float

    def as_context(self) -> str:
        if not self.label:
            return ""
        return (
            f"Tono acustico stimato dell'ultima frase: {self.label}. "
            "Usalo solo per calibrare ritmo e brevità della risposta; non dedurre stati mentali o diagnosi."
        )


def analyze_prosody(audio) -> ProsodySnapshot:
    """Estimate coarse speaking style without a second neural model."""
    import numpy as np

    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    x = x[np.isfinite(x)]
    if x.size < 800:
        return ProsodySnapshot("", 0.0, 0.0, 0.0)

    rms = float(np.sqrt(np.mean(x * x)))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(x)).astype(np.float32)))) if x.size > 1 else 0.0
    frame = max(320, min(1600, x.size // 8))
    frame_rms: list[float] = []
    for start in range(0, x.size - frame + 1, max(160, frame // 2)):
        chunk = x[start:start + frame]
        frame_rms.append(float(np.sqrt(np.mean(chunk * chunk))))
    dynamic = (max(frame_rms) - min(frame_rms)) if frame_rms else 0.0

    if rms >= 0.085 and dynamic >= 0.045:
        label = "energico e deciso"
    elif rms >= 0.055:
        label = "deciso"
    elif rms <= 0.018:
        label = "molto quieto"
    elif dynamic >= 0.055:
        label = "espressivo"
    elif zcr >= 0.13:
        label = "rapido o articolato"
    else:
        label = "calmo"
    return ProsodySnapshot(label, rms, zcr, dynamic)
