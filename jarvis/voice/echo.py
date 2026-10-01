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

    @staticmethod
    def _resample_linear(values, src_rate: int, dst_rate: int):
        import numpy as np

        if src_rate <= 0 or dst_rate <= 0 or src_rate == dst_rate:
            return values
        if values.size < 2:
            return values
        new_size = max(2, int(round(values.size * float(dst_rate) / float(src_rate))))
        old_x = np.linspace(0.0, 1.0, values.size, dtype=np.float32)
        new_x = np.linspace(0.0, 1.0, new_size, dtype=np.float32)
        return np.interp(new_x, old_x, values).astype(np.float32)

    def correlation(self, mic_audio, sample_rate: int) -> float:
        import numpy as np

        mic = np.asarray(mic_audio, dtype=np.float32).reshape(-1)
        if mic.size < 320:
            return 0.0
        with self._lock:
            chunks = list(self._chunks)
        if not chunks:
            return 0.0

        # Output is normally 24 kHz while the microphone path is 16 kHz.
        # Resample each contiguous group before correlation instead of silently
        # disabling the echo guard when sample rates differ.
        groups: list[tuple[int, bytearray]] = []
        for _ts, rate, raw in chunks:
            if not groups or groups[-1][0] != rate:
                groups.append((rate, bytearray()))
            groups[-1][1].extend(raw)
        refs = []
        for rate, raw in groups:
            arr = np.frombuffer(bytes(raw), dtype=np.int16).astype(np.float32) / 32768.0
            if arr.size:
                refs.append(self._resample_linear(arr, rate, int(sample_rate)))
        if not refs:
            return 0.0
        ref = np.concatenate(refs)
        if ref.size < 320:
            return 0.0

        mic = mic[-min(mic.size, int(sample_rate * 0.8)):]
        ref = ref[-min(ref.size, int(sample_rate * 1.6)):]
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
        search_step = max(8, m.size // 14)
        start = max(0, r.size - m.size - int(sample_rate * 0.8 / step))
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
