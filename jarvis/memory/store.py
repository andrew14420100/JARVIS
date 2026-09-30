from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


_TOKEN_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9_'-]{3,}")


@dataclass(slots=True)
class MemoryItem:
    id: int
    content: str
    created_at: str


class LocalMemory:
    """Small privacy-aware local memory store.

    It intentionally avoids automatically storing obvious secrets or highly
    sensitive identifiers. Facts are persisted only on the user's machine.
    """

    _explicit_triggers = (
        "ricorda che",
        "ricordati che",
        "ricorda questo",
        "preferisco",
        "voglio che jarvis",
        "il mio progetto",
        "uso sempre",
        "non dimenticare",
        "remember that",
        "remember this",
        "i prefer",
        "my project",
    )

    _blocked_terms = (
        "password",
        "passphrase",
        "pin ",
        "codice pin",
        "codice fiscale",
        "carta di credito",
        "credit card",
        "cvv",
        "iban",
        "private key",
        "secret key",
        "api key",
        "token segreto",
        "access token",
        "numero di telefono",
        "phone number",
        "indirizzo di casa",
        "home address",
    )

    def __init__(self, db_path: str = "data/jarvis_memory.sqlite3", top_k: int = 4) -> None:
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.top_k = top_k
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _setup(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.commit()

    @classmethod
    def safe_to_store(cls, text: str) -> bool:
        normalized = " ".join(text.lower().split())
        if len(normalized) < 8 or len(normalized) > 1500:
            return False
        return not any(term in normalized for term in cls._blocked_terms)

    @classmethod
    def should_remember(cls, text: str) -> bool:
        normalized = " ".join(text.lower().split())
        return cls.safe_to_store(text) and any(trigger in normalized for trigger in cls._explicit_triggers)

    def remember(self, text: str) -> bool:
        cleaned = " ".join(text.strip().split())
        if not self.safe_to_store(cleaned):
            return False
        with self._connect() as con:
            con.execute("INSERT OR IGNORE INTO facts(content) VALUES (?)", (cleaned,))
            changed = con.total_changes > 0
            con.commit()
        return changed

    def remember_if_requested(self, text: str) -> bool:
        if not self.should_remember(text):
            return False
        return self.remember(text)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.lower() for token in _TOKEN_RE.findall(text)}

    def search(self, query: str, top_k: int | None = None) -> list[str]:
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, content, created_at FROM facts ORDER BY id DESC LIMIT 300"
            ).fetchall()

        scored: list[tuple[float, int, str]] = []
        for row in rows:
            tokens = self._tokens(row["content"])
            if not tokens:
                continue
            overlap = len(query_tokens & tokens)
            if overlap == 0:
                continue
            score = overlap / max(1, len(query_tokens | tokens))
            scored.append((score, int(row["id"]), str(row["content"])))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        limit = top_k or self.top_k
        return [content for _score, _id, content in scored[:limit]]

    def recent(self, limit: int = 20) -> list[MemoryItem]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, content, created_at FROM facts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [MemoryItem(int(r["id"]), str(r["content"]), str(r["created_at"])) for r in rows]

    def forget(self, memory_id: int) -> bool:
        with self._connect() as con:
            cursor = con.execute("DELETE FROM facts WHERE id = ?", (memory_id,))
            con.commit()
            return cursor.rowcount > 0
