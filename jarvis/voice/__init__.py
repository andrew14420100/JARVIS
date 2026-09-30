"""Local voice subsystem for JARVIS.

Heavy optional dependencies are imported lazily so the cloud/web build can run
without the desktop voice stack installed.
"""

from .stt import LocalSTT
from .tts import LocalTTS
from .wake import WakeWordListener

__all__ = ["LocalSTT", "LocalTTS", "WakeWordListener"]
