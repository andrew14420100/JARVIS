from __future__ import annotations

import base64
import io
import threading
import time
from dataclasses import dataclass


_VISUAL_HINTS = (
    "schermo", "finestra", "guarda", "qui", "questo errore", "questa pagina",
    "quello che vedi", "cosa vedi", "monitor", "desktop", "browser", "immagine",
    "screenshot", "a sinistra", "a destra", "in alto", "in basso",
)


@dataclass(slots=True)
class ScreenFrame:
    jpeg: bytes
    captured_at: float
    width: int
    height: int
    fingerprint: str

    def data_uri(self) -> str:
        encoded = base64.b64encode(self.jpeg).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"


class ScreenMonitor:
    """Continuously sample the desktop while keeping only the latest frame.

    No screenshot is written to disk. Capturing is low-frequency and the image
    is only attached to a model request when the user's wording points to the
    screen, which prevents continuous multimodal inference from slowing JARVIS.
    """

    def __init__(
        self,
        *,
        interval_seconds: float = 2.0,
        max_width: int = 1280,
        jpeg_quality: int = 58,
    ) -> None:
        self.interval_seconds = max(0.5, float(interval_seconds))
        self.max_width = max(480, int(max_width))
        self.jpeg_quality = max(30, min(90, int(jpeg_quality)))
        self._latest: ScreenFrame | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error = ""

    @staticmethod
    def relevant_query(text: str) -> bool:
        value = " ".join(str(text or "").casefold().split())
        return bool(value) and any(hint in value for hint in _VISUAL_HINTS)

    def available(self) -> bool:
        try:
            from PIL import ImageGrab  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _fingerprint(image) -> str:
        import hashlib

        tiny = image.convert("L").resize((16, 9))
        return hashlib.sha1(tiny.tobytes()).hexdigest()[:16]

    def _capture(self) -> ScreenFrame | None:
        try:
            from PIL import ImageGrab

            image = ImageGrab.grab(all_screens=True)
            if image.width > self.max_width:
                scale = self.max_width / float(image.width)
                image = image.resize((self.max_width, max(1, int(image.height * scale))))
            fingerprint = self._fingerprint(image)
            buffer = io.BytesIO()
            image.convert("RGB").save(
                buffer,
                format="JPEG",
                quality=self.jpeg_quality,
                optimize=False,
            )
            return ScreenFrame(
                jpeg=buffer.getvalue(),
                captured_at=time.time(),
                width=int(image.width),
                height=int(image.height),
                fingerprint=fingerprint,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        if not self.available():
            self.last_error = "Pillow/ImageGrab non disponibile"
            return False
        self._stop.clear()

        def worker() -> None:
            while not self._stop.is_set():
                frame = self._capture()
                if frame is not None:
                    with self._lock:
                        self._latest = frame
                    self.last_error = ""
                self._stop.wait(self.interval_seconds)

        self._thread = threading.Thread(target=worker, daemon=True, name="jarvis-screen-monitor")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)

    def latest(self) -> ScreenFrame | None:
        with self._lock:
            return self._latest

    def message_content(self, query: str) -> list[dict] | None:
        if not self.relevant_query(query):
            return None
        frame = self.latest()
        if frame is None:
            return None
        return [
            {
                "type": "text",
                "text": (
                    f"{query}\n\nQuesta è l'immagine più recente dello schermo, "
                    f"acquisita {max(0.0, time.time() - frame.captured_at):.1f}s fa."
                ),
            },
            {"type": "image_url", "image_url": {"url": frame.data_uri()}},
        ]
