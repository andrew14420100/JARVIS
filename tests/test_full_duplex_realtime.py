from __future__ import annotations

import sys
import time
import types

import numpy as np

from jarvis.voice.full_duplex import FullDuplexMicrophone


def _install_fake_sounddevice(monkeypatch, frames, *, read_delay=0.001):
    state = {"opens": 0, "closes": 0}

    class FakeDefault:
        device = (0, 1)

    class FakeRawInputStream:
        def __init__(self, **kwargs):
            state["opens"] += 1
            self.blocksize = int(kwargs["blocksize"])
            self.frames = iter(frames)

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            state["closes"] += 1

        def read(self, chunk):
            time.sleep(read_delay)
            try:
                frame = next(self.frames)
            except StopIteration:
                frame = np.zeros(chunk, dtype=np.int16)
            if frame.size != chunk:
                frame = np.resize(frame, chunk).astype(np.int16)
            return frame.astype(np.int16).tobytes(), False

    devices = [
        {"name": "Microfono (SB Katana V2X)", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Altoparlanti (SB Katana V2X)", "max_input_channels": 0, "max_output_channels": 2},
    ]

    def query_devices(index=None, kind=None):
        if index is None:
            return devices
        return devices[int(index)]

    fake = types.SimpleNamespace(
        RawInputStream=FakeRawInputStream,
        query_devices=query_devices,
        default=FakeDefault(),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return state


def test_full_duplex_uses_one_persistent_stream_for_multiple_turns(monkeypatch):
    frame = 640
    quiet = np.zeros(frame, dtype=np.int16)
    speech_a = np.full(frame, 2200, dtype=np.int16)
    speech_b = np.full(frame, 2600, dtype=np.int16)
    frames = (
        [quiet] * 5
        + [speech_a] * 8
        + [quiet] * 9
        + [quiet] * 3
        + [speech_b] * 7
        + [quiet] * 9
    )
    state = _install_fake_sounddevice(monkeypatch, frames)
    mic = FullDuplexMicrophone(endpoint_silence_seconds=0.24, frame_ms=40)
    assert mic.start(timeout=1.0)
    first = mic.get_utterance(timeout=1.0)
    second = mic.get_utterance(timeout=1.0)
    mic.stop()

    assert first is not None and first.size > 0
    assert second is not None and second.size > 0
    assert state["opens"] == 1
    assert state["closes"] == 1


def test_full_duplex_barge_in_fires_while_assistant_active(monkeypatch):
    frame = 640
    quiet = np.zeros(frame, dtype=np.int16)
    speech = np.full(frame, 2400, dtype=np.int16)
    frames = [quiet] * 3 + [speech] * 10 + [quiet] * 9
    _install_fake_sounddevice(monkeypatch, frames)

    calls = {"verify": 0, "interrupt": 0}

    def verify(_audio):
        calls["verify"] += 1
        return True

    def interrupt():
        calls["interrupt"] += 1

    mic = FullDuplexMicrophone(
        endpoint_silence_seconds=0.24,
        frame_ms=40,
        assistant_active=lambda: True,
        assistant_speaking=lambda: False,
        verify_barge_speaker=verify,
        on_barge_in=interrupt,
        barge_in_min_seconds=0.20,
    )
    assert mic.start(timeout=1.0)
    utterance = mic.get_utterance(timeout=1.0)
    mic.stop()

    assert utterance is not None and utterance.size > 0
    assert calls["verify"] >= 1
    assert calls["interrupt"] == 1


def test_full_duplex_queue_is_bounded_and_flushable():
    mic = FullDuplexMicrophone()
    sample = np.ones(3200, dtype=np.float32)
    for _ in range(20):
        mic._put_utterance(sample)
    assert mic._queue.qsize() <= 6
    mic.flush()
    assert mic._queue.qsize() == 0
