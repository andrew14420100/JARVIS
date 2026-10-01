from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


_TOKEN_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9_'-]{3,}")
_SECRET_RES = (
    re.compile(r"(?i)\b(api[-_ ]?key|access[-_ ]?token|secret|password|passphrase|cvv)\b\s*[:=]?\s*\S+"),
    re.compile(r"\b\d{13,19}\b"),
)
_CORRECTION_HINTS = (
    "era sbagliato", "era sbagliata", "non è più vero", "non e più vero",
    "non è piu vero", "non e piu vero", "correggi quello", "rettifico",
    "mi correggo", "quello che ti ho detto", "non vale più", "non vale piu",
)


@dataclass(slots=True)
class MemoryItem:
    id: int
    content: str
    created_at: str


class LocalMemory:
    """Durable local memory with full transcript and searchable semantic notes.

    Long-term storage is deliberately separate from the live LLM history: every
    turn can be retained without letting a multi-hour voice session grow the
    prompt forever. Obvious secrets are redacted before persistence.
    """

    _explicit_triggers = (
        "ricorda che", "ricordati che", "ricorda questo", "preferisco",
        "voglio che jarvis", "il mio progetto", "uso sempre", "non dimenticare",
        "remember that", "remember this", "i prefer", "my project",
    )

    _blocked_terms = (
        "password", "passphrase", "pin ", "codice pin", "codice fiscale",
        "carta di credito", "credit card", "cvv", "iban", "private key",
        "secret key", "api key", "token segreto", "access token",
    )

    def __init__(self, db_path: str = "data/jarvis_memory.sqlite3", top_k: int = 8) -> None:
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.top_k = max(1, int(top_k))
        self._lock = threading.RLock()
        self.session_id = uuid.uuid4().hex
        self._setup()
        self.start_session("runtime")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=8.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=8000")
        return connection

    def _ensure_column(self, con: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        columns = {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _setup(self) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_column(con, "facts", "status", "TEXT NOT NULL DEFAULT 'active'")
            self._ensure_column(con, "facts", "superseded_by", "INTEGER")
            self._ensure_column(con, "facts", "source_message_id", "INTEGER")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    trigger TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_session ON conversation_messages(session_id, id)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status, id)"
            )
            con.commit()

    @staticmethod
    def _redact(text: str) -> str:
        value = str(text or "")
        for pattern in _SECRET_RES:
            value = pattern.sub("[REDACTED]", value)
        return value

    @classmethod
    def safe_to_store(cls, text: str) -> bool:
        normalized = " ".join(str(text or "").lower().split())
        if len(normalized) < 4 or len(normalized) > 12000:
            return False
        return not any(term in normalized for term in cls._blocked_terms)

    @classmethod
    def should_remember(cls, text: str) -> bool:
        normalized = " ".join(str(text or "").lower().split())
        return cls.safe_to_store(text) and any(trigger in normalized for trigger in cls._explicit_triggers)

    def start_session(self, trigger: str = "") -> str:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO sessions(id, trigger) VALUES (?, ?)",
                (self.session_id, str(trigger or "")[:120]),
            )
            con.commit()
        return self.session_id

    def end_session(self) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "UPDATE sessions SET ended_at=CURRENT_TIMESTAMP WHERE id=? AND ended_at IS NULL",
                (self.session_id,),
            )
            con.commit()

    def record_message(self, speaker: str, content: str, metadata: dict | None = None) -> int:
        cleaned = " ".join(str(content or "").strip().split())
        if not cleaned:
            return 0
        cleaned = self._redact(cleaned)
        payload = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as con:
            cursor = con.execute(
                "INSERT INTO conversation_messages(session_id, speaker, content, metadata_json) VALUES (?, ?, ?, ?)",
                (self.session_id, str(speaker or "unknown")[:80], cleaned, payload),
            )
            con.commit()
            return int(cursor.lastrowid or 0)

    def record_turn(
        self,
        user_text: str,
        assistant_text: str,
        *,
        speaker: str = "utente",
        metadata: dict | None = None,
        auto_semantic: bool = True,
    ) -> None:
        user_id = self.record_message(speaker, user_text, metadata)
        if assistant_text:
            self.record_message("Jarvis", assistant_text, {})
        if auto_semantic and self.safe_to_store(user_text):
            self._remember_semantic(user_text, source_message_id=user_id)

    def remember(self, text: str, *, source_message_id: int | None = None) -> bool:
        cleaned = " ".join(str(text or "").strip().split())
        if not self.safe_to_store(cleaned):
            return False
        cleaned = self._redact(cleaned)
        with self._lock, self._connect() as con:
            before = con.total_changes
            con.execute(
                "INSERT OR IGNORE INTO facts(content, status, source_message_id) VALUES (?, 'active', ?)",
                (cleaned, source_message_id),
            )
            changed = con.total_changes > before
            con.commit()
        return changed

    def remember_if_requested(self, text: str) -> bool:
        if not self.should_remember(text):
            return False
        return self.remember(text)

    def _remember_semantic(self, text: str, *, source_message_id: int | None = None) -> bool:
        normalized = " ".join(text.strip().split())
        if len(normalized) < 18:
            return False
        lower = normalized.casefold()
        correction = any(hint in lower for hint in _CORRECTION_HINTS)
        should_store = self.should_remember(normalized) or correction or len(normalized) >= 48
        if not should_store:
            return False
        changed = self.remember(normalized, source_message_id=source_message_id)
        if correction:
            self._supersede_related(normalized)
        return changed

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.lower() for token in _TOKEN_RE.findall(str(text or ""))}

    def _supersede_related(self, correction: str) -> None:
        tokens = self._tokens(correction)
        if not tokens:
            return
        with self._lock, self._connect() as con:
            rows = con.execute(
                "SELECT id, content FROM facts WHERE status='active' ORDER BY id DESC LIMIT 80"
            ).fetchall()
            if not rows:
                return
            newest_id = int(rows[0]["id"])
            for row in rows[1:]:
                other = self._tokens(row["content"])
                overlap = len(tokens & other)
                if overlap >= 3 and overlap / max(1, min(len(tokens), len(other))) >= 0.28:
                    con.execute(
                        "UPDATE facts SET status='superseded', superseded_by=? WHERE id=?",
                        (newest_id, int(row["id"])),
                    )
                    break
            con.commit()

    def search(self, query: str, top_k: int | None = None) -> list[str]:
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []
        limit = max(1, int(top_k or self.top_k))
        candidates: list[tuple[float, int, str]] = []
        with self._lock, self._connect() as con:
            facts = con.execute(
                "SELECT id, content FROM facts WHERE status='active' ORDER BY id DESC LIMIT 600"
            ).fetchall()
            messages = con.execute(
                "SELECT id, content FROM conversation_messages ORDER BY id DESC LIMIT 1200"
            ).fetchall()

        for bonus, rows in ((0.22, facts), (0.0, messages)):
            for row in rows:
                content = str(row["content"])
                tokens = self._tokens(content)
                if not tokens:
                    continue
                overlap = len(query_tokens & tokens)
                if overlap == 0:
                    continue
                score = overlap / max(1, len(query_tokens | tokens)) + bonus
                candidates.append((score, int(row["id"]), content))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        output: list[str] = []
        seen: set[str] = set()
        for _score, _id, content in candidates:
            if content in seen:
                continue
            output.append(content)
            seen.add(content)
            if len(output) >= limit:
                break
        return output

    def recent(self, limit: int = 20) -> list[MemoryItem]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                "SELECT id, content, created_at FROM facts WHERE status='active' ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [MemoryItem(int(r["id"]), str(r["content"]), str(r["created_at"])) for r in rows]

    def recent_transcript(self, limit: int = 50) -> list[MemoryItem]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                "SELECT id, speaker || ': ' || content AS content, created_at FROM conversation_messages ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [MemoryItem(int(r["id"]), str(r["content"]), str(r["created_at"])) for r in reversed(rows)]

    def forget(self, memory_id: int) -> bool:
        with self._lock, self._connect() as con:
            cursor = con.execute("DELETE FROM facts WHERE id = ?", (int(memory_id),))
            con.commit()
            return cursor.rowcount > 0

    def close(self) -> None:
        try:
            self.end_session()
        except Exception:
            pass
