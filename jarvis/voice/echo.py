from __future__ import annotations

import threading
import time
from collections import deque


class EchoReference:
    """Short rolling copy of PCM that JARVIS is currently playing.

    Microphone speech that is highly correlated with this reference is probably
    loudspeaker echo and must not trigger a self-interruption. Only a few seconds
    are retained in memory and nothing is written to disk.
    """

    def __init__(self, max_seconds: float = 3.0) -> None:
        self.max_seconds = max(0.5, float(max_seconds))
        self._chunks: deque[tuple[float, int, bytes]] = deque()
        self._lock = threading.RLock()

    def push_pcm16(self, pcm: bytes, sample_rate: int) -> None:
        if not pcm or sample_rate <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._chunks.append((now, int(sample_rate), bytes(pcm)))
            cutoff = now - self.max_seconds
            while self._chunks and self._chunks[0][0] < cutoff:
                self._chunks.popleft()

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()

    def correlation(self, mic_audio, sample_rate: int) -> float:
        import numpy as np

        mic = np.asarray(mic_audio, dtype=np.float32).reshape(-1)
        if mic.size < 320:
            return 0.0
        with self._lock:
            chunks = [item for item in self._chunks if item[1] == int(sample_rate)]
        if not chunks:
            return 0.0
        raw = b"".join(item[2] for item in chunks)
        ref = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if ref.size < 320:
            return 0.0

        # Search recent alignments because speaker->microphone delay depends on
        # Windows/audio hardware. Downsample for a cheap correlation check.
        mic = mic[-min(mic.size, int(sample_rate * 0.8)):]
        ref = ref[-min(ref.size, int(sample_rate * 1.4)):]
        step = max(1, int(sample_rate / 4000))
        m = mic[::step]
        r = ref[::step]
        if m.size < 80 or r.size < m.size:
            return 0.0
        m = m - float(np.mean(m))
        m_norm = float(np.linalg.norm(m))
        if m_norm <= 1e-8:
            return 0.0

        best = 0.0
        search_step = max(8, m.size // 12)
        start = max(0, r.size - m.size - int(sample_rate * 0.6 / step))
        end = max(start + 1, r.size - m.size + 1)
        for offset in range(start, end, search_step):
            segment = r[offset:offset + m.size]
            if segment.size != m.size:
                continue
            segment = segment - float(np.mean(segment))
            denom = m_norm * float(np.linalg.norm(segment))
            if denom <= 1e-8:
                continue
            score = abs(float(np.dot(m, segment) / denom))
            if score > best:
                best = score
        return min(1.0, max(0.0, best))


echo_reference = EchoReference()
