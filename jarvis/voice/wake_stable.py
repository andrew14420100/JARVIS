from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .wake import WakeWordListener as _BaseWakeWordListener


class WakeWordListener(_BaseWakeWordListener):
    """Hardened wake listener.

    The original listener accepted a second very low score threshold. That was
    useful while tuning microphones but it also made normal speech capable of
    waking JARVIS. This runtime uses the model threshold as the activation gate,
    adds a small RMS floor, and keeps lower scores diagnostic-only.
    """

    def __init__(self, *args, min_rms: float = 0.004, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.min_rms = max(0.0, float(min_rms))

    def run(
        self,
        callback: Callable[[], None],
        busy: Callable[[], bool] | None = None,
        interrupt: Callable[[], None] | None = None,
    ) -> None:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model

        self.reset()
        model = Model(wakeword_models=[self.model_name], inference_framework="onnx")
        cooldown_until = 0.0
        callback_lock = threading.Lock()
        prediction_key_reported = False
        last_candidate_log = 0.0
        diagnostic_floor = max(0.10, min(self.threshold * 0.55, self.threshold - 0.05))

        selected_device = self._select_working_input_device(sd)

        while not self._stop.is_set():
            if self._pause.is_set():
                self._stream_released.set()
                time.sleep(0.02)
                continue

            self._stream_released.clear()
            stream_kwargs: dict[str, Any] = {
                "device": selected_device,
                "samplerate": self.sample_rate,
                "blocksize": self.chunk_size,
                "channels": 1,
                "dtype": "int16",
            }
            try:
                with sd.RawInputStream(**stream_kwargs) as stream:
                    while not self._stop.is_set() and not self._pause.is_set():
                        data, overflowed = stream.read(self.chunk_size)
                        if overflowed:
                            continue
                        pcm = np.frombuffer(data, dtype=np.int16).copy()
                        with self._audio_lock:
                            self._recent_pcm.append(pcm)
                            if self._capture_post_wake:
                                self._post_wake_pcm.append(pcm)

                        predictions = model.predict(pcm)
                        prediction_key, score = self._prediction_score(predictions)
                        pcm_float = pcm.astype(np.float32) / 32768.0
                        rms = float(np.sqrt(np.mean(np.square(pcm_float)))) if pcm_float.size else 0.0

                        if not prediction_key_reported:
                            print(
                                f"[JARVIS] Wake detector: {prediction_key} · "
                                f"soglia {self.threshold:.2f} · rms minimo {self.min_rms:.4f}"
                            )
                            prediction_key_reported = True

                        now = time.monotonic()
                        if score >= diagnostic_floor and now - last_candidate_log >= 0.6:
                            print(f"[WAKE] {prediction_key} score={score:.3f} rms={rms:.4f}")
                            last_candidate_log = now

                        if score < self.threshold or rms < self.min_rms:
                            continue

                        model.reset()
                        if now < cooldown_until:
                            continue

                        print(
                            f"[JARVIS] Wake word rilevata · {prediction_key} "
                            f"score={score:.3f} rms={rms:.4f} mode=verified"
                        )

                        # Start collecting post-wake audio before handling an
                        # interrupt too. This lets the active conversation reuse
                        # the words immediately following "Hey Jarvis".
                        self.last_wake_rms = rms
                        with self._audio_lock:
                            self._post_wake_pcm.clear()
                            self._capture_post_wake = True

                        if busy and busy():
                            cooldown_until = now + 1.0
                            if interrupt:
                                interrupt()
                            continue

                        if callback_lock.locked():
                            continue
                        cooldown_until = now + 1.25

                        def invoke() -> None:
                            with callback_lock:
                                callback()

                        threading.Thread(
                            target=invoke,
                            daemon=True,
                            name="jarvis-wake-callback",
                        ).start()
            except Exception as exc:
                if self._stop.is_set() or self._pause.is_set():
                    continue
                print(f"[AUDIO] Il microfono [{selected_device}] non e' piu' disponibile: {exc}")
                selected_device = self._select_working_input_device(sd, exclude={selected_device})
            finally:
                self._stream_released.set()

            if self._pause.is_set():
                while self._pause.is_set() and not self._stop.is_set():
                    time.sleep(0.02)
