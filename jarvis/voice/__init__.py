"""Voice subsystem for JARVIS.

Heavy optional dependencies are imported lazily so the cloud/web build can run
without the desktop voice stack installed.
"""

from .cosyvoice_proxy import CosyVoiceProxyTTS
from .stt import LocalSTT
from .tts import LocalTTS
from .wake_stable import WakeWordListener

__all__ = ["CosyVoiceProxyTTS", "LocalSTT", "LocalTTS", "WakeWordListener"]
