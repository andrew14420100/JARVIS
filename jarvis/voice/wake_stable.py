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
        standby_soft_activation: Callable[[Any], bool] | None = None,
        soft_activation_threshold: float = 0.18,
        soft_activation_consecutive: int = 2,
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
        soft_threshold = max(0.10, min(float(soft_activation_threshold), self.threshold - 0.01))
        soft_needed = max(2, int(soft_activation_consecutive))
        soft_hits = 0

        speech_frames: list[Any] = []
        speech_samples = 0
        required_samples = max(self.chunk_size * 3, int(self.sample_rate * max(0.25, barge_in_min_seconds)))
        speech_rms_gate = max(self.min_rms * 2.0, float(barge_in_min_rms))

        def launch_callback() -> bool:
            if callback_lock.locked():
                return False

            def invoke() -> None:
                with callback_lock:
                    callback()

            threading.Thread(
                target=invoke,
                daemon=True,
                name="jarvis-wake-callback",
            ).start()
            return True

        while not self._stop.is_set():
            if self._pause.is_set():
                self._stream_released.set()
                speech_frames.clear()
                speech_samples = 0
                soft_hits = 0
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
                        # authorized speech may interrupt JARVIS. No wake word is
                        # required once the session has been activated.
                        active = bool(conversation_active and conversation_active())
                        is_busy = bool(busy and busy())
                        if active and is_busy and speech_interrupt is not None and now >= speech_cooldown_until:
                            if rms >= speech_rms_gate:
                                speech_frames.append(pcm)
                                speech_samples += int(pcm.size)
                            elif speech_frames and speech_samples < required_samples:
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
                                f"soglia {self.threshold:.2f} · gate Jarvis {soft_threshold:.2f} · "
                                f"rms minimo {self.min_rms:.4f}"
                            )
                            prediction_key_reported = True

                        if score >= diagnostic_floor and now - last_candidate_log >= 0.6:
                            print(f"[WAKE] {prediction_key} score={score:.3f} rms={rms:.4f}")
                            last_candidate_log = now

                        # The official hey_jarvis model sometimes scores bare
                        # "Jarvis" below its full-phrase threshold. Allow a lower
                        # gate only in standby, only after two consecutive hits,
                        # and only when an already-enrolled speaker verifies it.
                        # This avoids restoring the old unrestricted soft trigger.
                        if (
                            not active
                            and standby_soft_activation is not None
                            and now >= cooldown_until
                            and rms >= self.min_rms
                            and soft_threshold <= score < self.threshold
                        ):
                            soft_hits += 1
                            if soft_hits >= soft_needed:
                                candidate = self.recent_audio(seconds=1.15, exclude_tail_seconds=0.0)
                                verified = False
                                try:
                                    verified = bool(standby_soft_activation(candidate))
                                except Exception as exc:
                                    print(f"[WAKE] gate voce Jarvis fallito: {exc}")
                                soft_hits = 0
                                if verified:
                                    model.reset()
                                    self.last_wake_rms = rms
                                    self._start_post_capture([])
                                    cooldown_until = now + 1.5
                                    print(
                                        f"[JARVIS] Attivazione 'Jarvis' autorizzata · "
                                        f"score={score:.3f} rms={rms:.4f} mode=voice-gated-soft"
                                    )
                                    launch_callback()
                                    continue
                        elif score < soft_threshold or active:
                            soft_hits = 0

                        if score < self.threshold or rms < self.min_rms:
                            continue

                        model.reset()
                        soft_hits = 0
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
                        elif now >= cooldown_until:
                            cooldown_until = now + 1.25

                        launch_callback()
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
