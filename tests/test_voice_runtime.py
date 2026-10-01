from __future__ import annotations

from jarvis.core.router import JarvisRouter
from jarvis.voice.cosyvoice_proxy import CosyVoiceProxyTTS


def test_router_system_intent():
    assert JarvisRouter().classify("controlla la GPU") == "system"


def test_tts_strips_markdown_before_speech():
    cleaned = CosyVoiceProxyTTS._clean_for_speech(
        "**Controllo completato.**\n\n- GPU: `RTX`"
    )
    assert "*" not in cleaned
    assert "_" not in cleaned
    assert "`" not in cleaned
    assert "Controllo completato." in cleaned
    assert "GPU: RTX" in cleaned
