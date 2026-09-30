from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone


_SENSITIVE_PATTERNS = [
    re.compile(r"\b(password|passcode|pin|cvv|iban|api[-_ ]?key|secret|token)\b", re.I),
    re.compile(r"\b\d{13,19}\b"),
]


@dataclass(slots=True)
class PresenceUtterance:
    speaker: str
    text: str
    created_at: str


class PresenceContext:
    """Short-lived local conversation context inspired by room-presence assistants.

    The buffer is intentionally ephemeral: it is not written to SQLite and is
    cleared on process exit. Obvious sensitive strings are excluded.
    """

    def __init__(self, max_items: int = 12, max_chars: int = 5000) -> None:
        self.max_items = max(1, max_items)
        self.max_chars = max(500, max_chars)
        self._items: deque[PresenceUtterance] = deque(maxlen=self.max_items)
        self._lock = threading.RLock()

    @staticmethod
    def _safe(text: str) -> bool:
        value = text.strip()
        return bool(value) and not any(pattern.search(value) for pattern in _SENSITIVE_PATTERNS)

    def add(self, text: str, *, speaker: str = "ambiente") -> bool:
        value = " ".join(text.strip().split())
        if not self._safe(value):
            return False
        with self._lock:
            self._items.append(
                PresenceUtterance(
                    speaker=speaker,
                    text=value,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        return True

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def snapshot(self) -> list[PresenceUtterance]:
        with self._lock:
            return list(self._items)

    def as_context(self) -> str:
        with self._lock:
            items = list(self._items)
        if not items:
            return ""

        lines = [f"{item.speaker}: {item.text}" for item in items]
        output = "\n".join(lines)
        if len(output) > self.max_chars:
            output = output[-self.max_chars :]
        return output
