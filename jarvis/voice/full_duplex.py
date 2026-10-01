from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from .echo import echo_reference


class FullDuplexMicrophone:
    """One persistent microphone stream for human-style conversation.

    The old desktop loop repeatedly closed the wake stream, opened an STT stream,
    closed it again, then opened the wake stream. On Windows/USB audio this adds
    visible gaps and can race with the output device. This engine owns one input
    stream for the lifetime of JARVIS, performs lightweight adaptive endpointing,
    and keeps listening while CosyVoice is speaking so a verified user can barge
    in naturally.

    It does *not* run Whisper in the audio thread. Complete utterances are queued
    as float32 mono PCM and decoded by the conversation loop. That keeps PortAudio
    deterministic and avoids GPU work inside the realtime capture path.
    """

    def __init__(
        self,
        *,
        input_device: str | int | None = None,
        sample_rate: int = 16000,
        frame_ms: int = 40,
        endpoint_silence_seconds: float = 0.30,
        min_speech_rms: float = 0.00090,
        max_utterance_seconds: float = 45.0,
        assistant_active: Callable[[], bool] | None = None,
        assistant_speaking: Callable[[], bool] | None = None,
        verify_barge_speaker: Callable[[Any], bool] | None = None,
        on_barge_in: Callable[[], None] | None = None,
        echo_guard_enabled: bool = True,
        echo_guard_max_correlation: float = 0.82,
        barge_in_min_seconds: float = 0.30,
    ) -> None:
        self.input_device = input_device
        self.sample_rate = int(sample_rate)
        self.frame_ms = max(20, min(80, int(frame_ms)))
        self.frame_size = max(160, int(self.sample_rate * self.frame_ms / 1000.0))
        self.endpoint_silence_seconds = max(0.22, min(1.2, float(endpoint_silence_seconds)))
        self.min_speech_rms = max(0.00005, float(min_speech_rms))
        self.max_utterance_seconds = max(5.0, float(max_utterance_seconds))
        self.assistant_active = assistant_active or (lambda: False)
        self.assistant_speaking = assistant_speaking or (lambda: False)
        self.verify_barge_speaker = verify_barge_speaker
        self.on_barge_in = on_barge_in
        self.echo_guard_enabled = bool(echo_guard_enabled)
        self.echo_guard_max_correlation = max(0.1, min(0.99, float(echo_guard_max_correlation)))
        self.barge_in_min_seconds = max(0.18, min(1.0, float(barge_in_min_seconds)))

        self.selected_device: int | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=6)
        self._last_error = ""
        self._last_rms = 0.0
        self._noise_floor = 0.0

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_rms(self) -> float:
        return self._last_rms

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    @staticmethod
    def dependency_status() -> dict[str, bool]:
        status: dict[str, bool] = {}
        for module in ("sounddevice", "numpy"):
            try:
                __import__(module)
                status[module] = True
            except Exception:
                status[module] = False
        return status

    def available(self) -> bool:
        return all(self.dependency_status().values())

    @staticmethod
    def _looks_like_microphone(name: str) -> bool:
        value = str(name or "").casefold()
        return any(token in value for token in ("microfono", "microphone", "headset", "mic ", " mic", "katana"))

    def _candidate_devices(self, sd) -> list[int]:
        devices = list(sd.query_devices())
        inputs = [
            idx for idx, info in enumerate(devices)
            if int(info.get("max_input_channels", 0) or 0) > 0
        ]
        ordered: list[int] = []

        def add(index: int | None) -> None:
            if index is not None and index in inputs and index not in ordered:
                ordered.append(index)

        configured = self.input_device
        if configured not in (None, ""):
            if isinstance(configured, int) or str(configured).strip().isdigit():
                add(int(configured))
            else:
                wanted = str(configured).casefold().strip()
                for idx in inputs:
                    if wanted and wanted in str(devices[idx].get("name", "")).casefold():
                        add(idx)

        # Prefer the user's real USB/headset microphone before generic mappers.
        for idx in inputs:
            if self._looks_like_microphone(str(devices[idx].get("name", ""))):
                add(idx)

        try:
            default = sd.default.device
            default_input = int(default[0] if isinstance(default, (tuple, list)) else default)
            if default_input >= 0:
                add(default_input)
        except Exception:
            pass

        for idx in inputs:
            add(idx)
        return ordered

    def _open_working_stream(self, sd):
        last_error: Exception | None = None
        for idx in self._candidate_devices(sd):
            try:
                info = sd.query_devices(idx, "input")
                stream = sd.RawInputStream(
                    device=idx,
                    samplerate=self.sample_rate,
                    blocksize=self.frame_size,
                    channels=1,
                    dtype="int16",
                    latency="low",
                )
                stream.start()
                self.selected_device = idx
                print(
                    f"[JARVIS] Microfono full-duplex: [{idx}] "
                    f"{info.get('name', f'device {idx}')} · {self.sample_rate} Hz · "
                    f"frame={self.frame_ms}ms"
                )
                return stream
            except Exception as exc:
                last_error = exc
                try:
                    name = str(sd.query_devices(idx).get("name", f"device {idx}"))
                except Exception:
                    name = f"device {idx}"
                print(f"[AUDIO] Scarto input full-duplex [{idx}] {name}: {exc}")
        raise RuntimeError(f"Nessun microfono full-duplex disponibile: {last_error}")

    def start(self, timeout: float = 8.0) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        if not self.available():
            self._last_error = f"Dipendenze mancanti: {self.dependency_status()}"
            return False
        self._stop.clear()
        self._ready.clear()
        self._last_error = ""
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-full-duplex-mic")
        self._thread.start()
        self._ready.wait(timeout=max(0.5, float(timeout)))
        return self._ready.is_set() and not self._last_error

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def flush(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def get_utterance(self, timeout: float = 0.25):
        try:
            return self._queue.get(timeout=max(0.01, float(timeout)))
        except queue.Empty:
            return None

    def _put_utterance(self, audio) -> None:
        try:
            self._queue.put_nowait(audio)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(audio)
            except queue.Full:
                pass

    def _run(self) -> None:
        import numpy as np
        import sounddevice as sd

        stream = None
        try:
            stream = self._open_working_stream(sd)
            self._ready.set()

            pre_roll_frames = max(2, int(0.16 / (self.frame_ms / 1000.0)))
            pre_roll: deque[Any] = deque(maxlen=pre_roll_frames)
            noise_values: deque[float] = deque(maxlen=max(20, int(2.5 / (self.frame_ms / 1000.0))))

            active = False
            frames: list[Any] = []
            speech_started_at = 0.0
            silence_seconds = 0.0
            overlapped_assistant = False
            barge_checked = False
            barge_accepted = False

            def reset_turn() -> None:
                nonlocal active, frames, speech_started_at, silence_seconds
                nonlocal overlapped_assistant, barge_checked, barge_accepted
                active = False
                frames = []
                speech_started_at = 0.0
                silence_seconds = 0.0
                overlapped_assistant = False
                barge_checked = False
                barge_accepted = False

            while not self._stop.is_set():
                try:
                    raw, overflowed = stream.read(self.frame_size)
                except Exception as exc:
                    self._last_error = str(exc)
                    print(f"[AUDIO] Stream microfono full-duplex interrotto: {exc}")
                    break
                if overflowed:
                    continue

                pcm_i16 = np.frombuffer(raw, dtype=np.int16).copy()
                pcm = pcm_i16.astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(np.square(pcm)))) if pcm.size else 0.0
                self._last_rms = rms

                assistant_active = bool(self.assistant_active())
                assistant_speaking = bool(self.assistant_speaking())

                if not active:
                    pre_roll.append(pcm)
                    if not assistant_speaking:
                        noise_values.append(rms)
                    noise = float(np.percentile(np.asarray(noise_values, dtype=np.float32), 45)) if noise_values else 0.0
                    self._noise_floor = noise
                    speech_gate = max(self.min_speech_rms, noise * 2.25)
                    if rms >= speech_gate:
                        active = True
                        speech_started_at = time.monotonic()
                        frames = [item.copy() for item in pre_roll]
                        frames.append(pcm)
                        overlapped_assistant = assistant_active
                        silence_seconds = 0.0
                    continue

                frames.append(pcm)
                overlapped_assistant = overlapped_assistant or assistant_active

                noise = self._noise_floor
                speech_gate = max(self.min_speech_rms, noise * 2.25)
                release_gate = max(self.min_speech_rms * 0.55, noise * 1.55, speech_gate * 0.46)
                if rms >= speech_gate:
                    silence_seconds = 0.0
                elif rms <= release_gate:
                    silence_seconds += self.frame_ms / 1000.0
                else:
                    silence_seconds += (self.frame_ms / 1000.0) * 0.45

                elapsed = time.monotonic() - speech_started_at

                # While JARVIS is thinking/speaking, a verified human voice can
                # cancel the current response. If audio is actually loudspeaker
                # echo, correlation with the rolling TTS reference suppresses it.
                if assistant_active and not barge_checked and elapsed >= self.barge_in_min_seconds:
                    candidate = np.concatenate(frames).astype(np.float32, copy=False)
                    correlation = (
                        echo_reference.correlation(candidate, self.sample_rate)
                        if assistant_speaking and self.echo_guard_enabled
                        else 0.0
                    )
                    if correlation < self.echo_guard_max_correlation:
                        accepted = True
                        if self.verify_barge_speaker is not None:
                            try:
                                accepted = bool(self.verify_barge_speaker(candidate))
                            except Exception as exc:
                                accepted = False
                                print(f"[BARGE] verifica parlante fallita: {exc}")
                        if accepted:
                            barge_accepted = True
                            barge_checked = True
                            if self.on_barge_in is not None:
                                try:
                                    self.on_barge_in()
                                except Exception as exc:
                                    print(f"[BARGE] callback interruzione fallita: {exc}")
                            print(
                                f"[JARVIS] Interruzione naturale · rms={rms:.4f} "
                                f"echo={correlation:.2f}"
                            )
                    elif elapsed >= 0.75:
                        # Enough evidence that this is likely JARVIS hearing its
                        # own loudspeaker. Mark checked to avoid CPU-heavy repeated
                        # correlations on every following frame.
                        barge_checked = True

                should_finish = silence_seconds >= self.endpoint_silence_seconds
                should_force = elapsed >= self.max_utterance_seconds
                if not should_finish and not should_force:
                    continue

                audio = np.concatenate(frames).astype(np.float32, copy=False) if frames else np.zeros(0, dtype=np.float32)
                if audio.size:
                    keep = True
                    if overlapped_assistant and not barge_accepted:
                        correlation = (
                            echo_reference.correlation(audio, self.sample_rate)
                            if self.echo_guard_enabled else 0.0
                        )
                        if correlation >= self.echo_guard_max_correlation:
                            keep = False
                        elif self.verify_barge_speaker is not None:
                            try:
                                keep = bool(self.verify_barge_speaker(audio))
                            except Exception:
                                keep = False
                        if keep and self.on_barge_in is not None:
                            try:
                                self.on_barge_in()
                                barge_accepted = True
                            except Exception:
                                pass
                    if keep:
                        self._put_utterance(audio)
                reset_turn()

        except Exception as exc:
            self._last_error = str(exc)
            self._ready.set()
            print(f"[AUDIO] Full-duplex non disponibile: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            self._ready.set()
