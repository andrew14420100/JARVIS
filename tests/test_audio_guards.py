import numpy as np

from jarvis.voice.echo import EchoReference
from jarvis.voice.identity import SpeakerAuthenticator
from jarvis.voice.prosody import analyze_prosody


def sine(rate: int, hz: float, seconds: float = 1.2, amplitude: float = 0.22):
    t = np.arange(int(rate * seconds), dtype=np.float32) / float(rate)
    return (amplitude * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)


def test_speaker_profile_roundtrip(tmp_path):
    auth = SpeakerAuthenticator(str(tmp_path / "profiles"), threshold=0.96)
    sample = sine(16000, 180.0) + 0.35 * sine(16000, 360.0)
    assert auth.enroll("Andrea", "owner", sample, 16000) is True
    match = auth.identify(sample.copy(), 16000)
    assert match.authorized is True
    assert match.name == "Andrea"
    assert match.role == "owner"
    assert match.score > 0.99


def test_different_spectral_voice_is_not_perfect_match(tmp_path):
    auth = SpeakerAuthenticator(str(tmp_path / "profiles"), threshold=0.995)
    sample_a = sine(16000, 170.0) + 0.4 * sine(16000, 340.0)
    sample_b = sine(16000, 760.0) + 0.2 * sine(16000, 1520.0)
    assert auth.enroll("A", "owner", sample_a, 16000) is True
    match = auth.identify(sample_b, 16000)
    assert match.score < 0.995
    assert match.authorized is False


def test_echo_reference_correlates_after_24k_to_16k_resample():
    reference = EchoReference(max_seconds=3.0)
    output = sine(24000, 440.0, seconds=1.0, amplitude=0.25)
    pcm = np.clip(output * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    reference.push_pcm16(pcm, 24000)
    mic = sine(16000, 440.0, seconds=0.65, amplitude=0.18)
    assert reference.correlation(mic, 16000) > 0.80


def test_echo_reference_rejects_unrelated_signal():
    reference = EchoReference(max_seconds=3.0)
    output = sine(24000, 330.0, seconds=1.0, amplitude=0.25)
    pcm = np.clip(output * 32767.0, -32768, 32767).astype(np.int16).tobytes()
    reference.push_pcm16(pcm, 24000)
    mic = sine(16000, 997.0, seconds=0.65, amplitude=0.18)
    assert reference.correlation(mic, 16000) < 0.45


def test_prosody_analysis_is_finite_and_context_safe():
    audio = sine(16000, 220.0, seconds=1.0, amplitude=0.08)
    snapshot = analyze_prosody(audio)
    assert snapshot.label
    assert np.isfinite(snapshot.rms)
    context = snapshot.as_context()
    assert "diagnosi" in context
    assert "Tono acustico stimato" in context
