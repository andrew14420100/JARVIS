from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .echo import echo_reference
from .wake import WakeWordListener as _BaseWakeWordListener


class WakeWordListener(_BaseWakeWordListener):
    """Hardened wake listener plus natural in-session speech barge-in."""

    def __init__(self, *args, min_rms: float = 0.004, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.min_rms = max(0.0, float(min_rms))

    def _start_post_capture(self, pcm_chunks) -> None:
        with self._audio_lock:
            self._post_wake_pcm.clear()
            for chunk in pcm_chunks:
                if getattr(chunk, "size", 0):
                    self._post_wake_pcm.append(chunk.copy())
            self._capture_post_wake = True

    def run(
        self,
        callback: Callable[[], None],
        busy: Callable[[], bool] | None = None,
        interrupt: Callable[[], None] | None = None,
        *,
        conversation_active: Callable[[], bool] | None = None,
        speech_interrupt: Callable[[Any], bool] | None = None,
        barge_in_min_rms: float = 0.010,
        barge_in_min_seconds: float = 0.45,
        echo_guard_enabled: bool = True,
        echo_guard_max_correlation: float = 0.82,
    ) -> None:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model

        self.reset()
        model = Model(wakeword_models=[self.model_name], inference_framework="onnx")
        cooldown_until = 0.0
        speech_cooldown_until = 0.0
        callback_lock = threading.Lock()
        prediction_key_reported = False
        last_candidate_log = 0.0
        diagnostic_floor = max(0.10, min(self.threshold * 0.55, self.threshold - 0.05))
        selected_device = self._select_working_input_device(sd)

        speech_frames: list[Any] = []
        speech_samples = 0
        required_samples = max(self.chunk_size * 3, int(self.sample_rate * max(0.25, barge_in_min_seconds)))
        speech_rms_gate = max(self.min_rms * 2.0, float(barge_in_min_rms))

        while not self._stop.is_set():
            if self._pause.is_set():
                self._stream_released.set()
                speech_frames.clear()
                speech_samples = 0
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

                        pcm_float = pcm.astype(np.float32) / 32768.0
                        rms = float(np.sqrt(np.mean(np.square(pcm_float)))) if pcm_float.size else 0.0
                        now = time.monotonic()

                        # During an already-open session, any clear non-echo
                        # speech may interrupt JARVIS. This is intentionally
                        # separate from wake-word detection.
                        active = bool(conversation_active and conversation_active())
                        is_busy = bool(busy and busy())
                        if active and is_busy and speech_interrupt is not None and now >= speech_cooldown_until:
                            if rms >= speech_rms_gate:
                                speech_frames.append(pcm)
                                speech_samples += int(pcm.size)
                            elif speech_frames:
                                # Permit tiny gaps but reset a weak/noisy attempt.
                                if speech_samples < required_samples:
                                    speech_frames.clear()
                                    speech_samples = 0
                            if speech_samples >= required_samples:
                                candidate_i16 = np.concatenate(speech_frames)
                                candidate = candidate_i16.astype(np.float32) / 32768.0
                                correlation = (
                                    echo_reference.correlation(candidate, self.sample_rate)
                                    if echo_guard_enabled else 0.0
                                )
                                accepted = False
                                if correlation < float(echo_guard_max_correlation):
                                    try:
                                        accepted = bool(speech_interrupt(candidate))
                                    except Exception as exc:
                                        print(f"[BARGE] verifica voce fallita: {exc}")
                                if accepted:
                                    self._start_post_capture(speech_frames)
                                    speech_cooldown_until = now + 1.0
                                    if interrupt:
                                        interrupt()
                                    print(
                                        "[JARVIS] Barge-in naturale: voce autorizzata · "
                                        f"rms={rms:.4f} echo={correlation:.2f}"
                                    )
                                elif correlation >= float(echo_guard_max_correlation):
                                    print(f"[BARGE] eco ignorato · corr={correlation:.2f}")
                                speech_frames.clear()
                                speech_samples = 0
                        else:
                            speech_frames.clear()
                            speech_samples = 0

                        predictions = model.predict(pcm)
                        prediction_key, score = self._prediction_score(predictions)
                        if not prediction_key_reported:
                            print(
                                f"[JARVIS] Wake detector: {prediction_key} · "
                                f"soglia {self.threshold:.2f} · rms minimo {self.min_rms:.4f}"
                            )
                            prediction_key_reported = True

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
                        self.last_wake_rms = rms
                        self._start_post_capture([])

                        was_busy = bool(busy and busy())
                        if was_busy:
                            cooldown_until = now + 1.0
                            if interrupt:
                                interrupt()
                            print("[JARVIS] Barge-in wake: risposta corrente interrotta.")

                        if callback_lock.locked():
                            continue
                        if not was_busy:
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
