from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.paths import DB_PATH, ensure_app_dirs


@dataclass(slots=True)
class CaptureRecord:
    id: int
    created_at: str
    image_path: str
    source_text: str
    translation: str
    explanation: str
    app_name: str
    tags: list[str]


@dataclass(slots=True)
class TermRecord:
    id: int
    term: str
    chinese_name: str
    beginner_explanation: str
    examples: list[str]
    first_seen_at: str
    review_count: int


@dataclass(slots=True)
class ConversationMessage:
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str
    mode: str


class HistoryStore:
    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        ensure_app_dirs()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available = False
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    source_text TEXT NOT NULL DEFAULT '',
                    translation TEXT NOT NULL DEFAULT '',
                    explanation TEXT NOT NULL DEFAULT '',
                    app_name TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL UNIQUE,
                    chinese_name TEXT NOT NULL DEFAULT '',
                    beginner_explanation TEXT NOT NULL DEFAULT '',
                    examples TEXT NOT NULL DEFAULT '[]',
                    first_seen_at TEXT NOT NULL,
                    review_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(capture_id) REFERENCES captures(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
                """
            )
            self._try_initialize_fts(conn)

    def save_capture(
        self,
        image_path: str | Path,
        source_text: str,
        translation: str,
        explanation: str,
        app_name: str = "",
        tags: list[str] | None = None,
    ) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO captures
                    (created_at, image_path, source_text, translation, explanation, app_name, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    str(image_path),
                    source_text,
                    translation,
                    explanation,
                    app_name,
                    json.dumps(tags or [], ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def search_captures(self, query: str = "", limit: int = 100) -> list[CaptureRecord]:
        query = query.strip()
        if query and self._fts_available:
            try:
                return self._search_captures_fts(query, limit)
            except sqlite3.Error:
                pass

        with self._connect() as conn:
            if query:
                like = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT * FROM captures
                    WHERE source_text LIKE ?
                       OR translation LIKE ?
                       OR explanation LIKE ?
                       OR tags LIKE ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (like, like, like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM captures
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [_capture_from_row(row) for row in rows]

    def get_capture(self, capture_id: int) -> CaptureRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        return _capture_from_row(row) if row else None

    def upsert_terms(self, terms: list[dict[str, Any]]) -> None:
        if not terms:
            return
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            for term in terms:
                name = str(term.get("term") or "").strip()
                if not name:
                    continue
                conn.execute(
                    """
                    INSERT INTO terms
                        (term, chinese_name, beginner_explanation, examples, first_seen_at, review_count)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT(term) DO UPDATE SET
                        chinese_name = excluded.chinese_name,
                        beginner_explanation = excluded.beginner_explanation,
                        examples = excluded.examples,
                        review_count = terms.review_count + 1
                    """,
                    (
                        name,
                        str(term.get("chinese_name") or ""),
                        str(term.get("beginner_explanation") or ""),
                        json.dumps(term.get("examples") or [], ensure_ascii=False),
                        now,
                    ),
                )

    def save_term(
        self,
        term: str,
        chinese_name: str = "",
        beginner_explanation: str = "",
        examples: list[str] | None = None,
        term_id: int | None = None,
    ) -> int:
        name = term.strip()
        if not name:
            raise ValueError("术语不能为空")
        payload = json.dumps(examples or [], ensure_ascii=False)
        with self._connect() as conn:
            if term_id is not None:
                conn.execute(
                    """
                    UPDATE terms
                    SET term = ?, chinese_name = ?, beginner_explanation = ?, examples = ?
                    WHERE id = ?
                    """,
                    (name, chinese_name, beginner_explanation, payload, term_id),
                )
                return term_id
            cursor = conn.execute(
                """
                INSERT INTO terms
                    (term, chinese_name, beginner_explanation, examples, first_seen_at, review_count)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(term) DO UPDATE SET
                    chinese_name = excluded.chinese_name,
                    beginner_explanation = excluded.beginner_explanation,
                    examples = excluded.examples
                """,
                (
                    name,
                    chinese_name,
                    beginner_explanation,
                    payload,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            return int(cursor.lastrowid or 0)

    def delete_term(self, term_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM terms WHERE id = ?", (term_id,))

    def create_conversation(self, capture_id: int, title: str = "") -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM conversations WHERE capture_id = ? ORDER BY id ASC LIMIT 1",
                (capture_id,),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = conn.execute(
                """
                INSERT INTO conversations(capture_id, created_at, title)
                VALUES (?, ?, ?)
                """,
                (capture_id, created_at, title),
            )
            return int(cursor.lastrowid)

    def get_conversation_id_for_capture(self, capture_id: int) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE capture_id = ? ORDER BY id ASC LIMIT 1",
                (capture_id,),
            ).fetchone()
        return int(row["id"]) if row else None

    def add_message(self, conversation_id: int, role: str, content: str, mode: str = "") -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages(conversation_id, role, content, created_at, mode)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, role, content, created_at, mode),
            )
            return int(cursor.lastrowid)

    def list_messages(self, conversation_id: int, limit: int = 20) -> list[ConversationMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def list_terms(self, query: str = "", limit: int = 200) -> list[TermRecord]:
        query = query.strip()
        with self._connect() as conn:
            if query:
                like = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT * FROM terms
                    WHERE term LIKE ?
                       OR chinese_name LIKE ?
                       OR beginner_explanation LIKE ?
                    ORDER BY review_count DESC, first_seen_at DESC
                    LIMIT ?
                    """,
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM terms
                    ORDER BY review_count DESC, first_seen_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [_term_from_row(row) for row in rows]

    def get_settings(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def _search_captures_fts(self, query: str, limit: int) -> list[CaptureRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*
                FROM captures_fts f
                JOIN captures c ON c.id = f.rowid
                WHERE captures_fts MATCH ?
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [_capture_from_row(row) for row in rows]

    def _try_initialize_fts(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts
                USING fts5(source_text, translation, explanation, tags, content='captures', content_rowid='id')
                """
            )
            conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS captures_ai AFTER INSERT ON captures BEGIN
                    INSERT INTO captures_fts(rowid, source_text, translation, explanation, tags)
                    VALUES (new.id, new.source_text, new.translation, new.explanation, new.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS captures_ad AFTER DELETE ON captures BEGIN
                    INSERT INTO captures_fts(captures_fts, rowid, source_text, translation, explanation, tags)
                    VALUES ('delete', old.id, old.source_text, old.translation, old.explanation, old.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS captures_au AFTER UPDATE ON captures BEGIN
                    INSERT INTO captures_fts(captures_fts, rowid, source_text, translation, explanation, tags)
                    VALUES ('delete', old.id, old.source_text, old.translation, old.explanation, old.tags);
                    INSERT INTO captures_fts(rowid, source_text, translation, explanation, tags)
                    VALUES (new.id, new.source_text, new.translation, new.explanation, new.tags);
                END;
                """
            )
            self._fts_available = True
        except sqlite3.Error:
            self._fts_available = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _capture_from_row(row: sqlite3.Row) -> CaptureRecord:
    return CaptureRecord(
        id=int(row["id"]),
        created_at=str(row["created_at"]),
        image_path=str(row["image_path"]),
        source_text=str(row["source_text"]),
        translation=str(row["translation"]),
        explanation=str(row["explanation"]),
        app_name=str(row["app_name"]),
        tags=_loads_list(row["tags"]),
    )


def _term_from_row(row: sqlite3.Row) -> TermRecord:
    return TermRecord(
        id=int(row["id"]),
        term=str(row["term"]),
        chinese_name=str(row["chinese_name"]),
        beginner_explanation=str(row["beginner_explanation"]),
        examples=_loads_list(row["examples"]),
        first_seen_at=str(row["first_seen_at"]),
        review_count=int(row["review_count"]),
    )


def _message_from_row(row: sqlite3.Row) -> ConversationMessage:
    return ConversationMessage(
        id=int(row["id"]),
        conversation_id=int(row["conversation_id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        created_at=str(row["created_at"]),
        mode=str(row["mode"]),
    )


def _loads_list(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]
