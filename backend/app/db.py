"""SQLite storage for session history. Uses only the standard library."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    metadata    TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id, id);

-- One row per session: stores the session's system prompt override (NULL = default).
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    system_prompt: str | None


class Database:
    """Thin wrapper around one SQLite connection.

    SQLite calls are fast and short, so one connection guarded by a lock is enough
    for this app. FastAPI handlers call these methods through a worker thread.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)

    def ping(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- reads -------------------------------------------------------------

    def get_session(self, session_id: str) -> SessionRow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id, system_prompt FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return SessionRow(row["session_id"], row["system_prompt"]) if row else None

    def get_recent_history(self, session_id: str, limit: int) -> list[dict[str, str]]:
        """Last `limit` user/assistant turns, oldest first, in LLM message format."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM ("
                "  SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC",
                (session_id, max(limit, 0)),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, metadata, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            item: dict[str, Any] = {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            if r["role"] == "assistant" and r["metadata"]:
                item["metadata"] = json.loads(r["metadata"])
            out.append(item)
        return out

    # ---- writes ------------------------------------------------------------

    def save_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any],
        system_prompt: str | None,
    ) -> None:
        """Store the user message and the assistant reply atomically.

        Called only after the LLM call succeeded, so failed requests (422/503)
        never leave half a turn in the history.
        """
        user_ts = utc_now_iso()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO sessions (session_id, system_prompt, created_at, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET "
                    "  system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt), "
                    "  updated_at = excluded.updated_at",
                    (session_id, system_prompt, user_ts, user_ts),
                )
                self._conn.execute(
                    "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
                    (session_id, user_message, user_ts),
                )
                self._conn.execute(
                    "INSERT INTO messages (session_id, role, content, metadata, created_at) "
                    "VALUES (?, 'assistant', ?, ?, ?)",
                    (session_id, assistant_message, json.dumps(metadata), utc_now_iso()),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
