from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.paths import DB_PATH, ensure_app_dirs
from app.services.context_detector import detect_domain


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
    category: str = ""
    domain: str = "通用"


@dataclass(slots=True)
class TermRecord:
    id: int
    term: str
    chinese_name: str
    beginner_explanation: str
    examples: list[str]
    first_seen_at: str
    review_count: int
    domain: str = "通用"
    favorite: bool = False


@dataclass(slots=True)
class ConversationMessage:
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str
    mode: str


@dataclass(slots=True)
class ContextRecord:
    id: int
    name: str
    domain: str
    scene: str
    summary: str
    instruction: str
    builtin: bool
    created_at: str
    updated_at: str


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
                    tags TEXT NOT NULL DEFAULT '[]',
                    category TEXT NOT NULL DEFAULT '',
                    domain TEXT NOT NULL DEFAULT '通用'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '通用',
                    chinese_name TEXT NOT NULL DEFAULT '',
                    beginner_explanation TEXT NOT NULL DEFAULT '',
                    examples TEXT NOT NULL DEFAULT '[]',
                    first_seen_at TEXT NOT NULL,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(term, domain)
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capture_embeddings (
                    capture_id INTEGER PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(capture_id) REFERENCES captures(id) ON DELETE CASCADE
                )
                """
            )
            self._initialize_contexts_table(conn)
            self._migrate_schema(conn)
            self._try_initialize_fts(conn)

    def _initialize_contexts_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contexts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT '通用',
                scene TEXT NOT NULL DEFAULT '通用',
                summary TEXT NOT NULL DEFAULT '',
                instruction TEXT NOT NULL DEFAULT '',
                builtin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        now = datetime.now().isoformat(timespec="seconds")
        existing = conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0]
        if existing == 0:
            conn.execute(
                """
                INSERT INTO contexts (name, domain, scene, summary, instruction, builtin, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("通用", "通用", "通用", "", "", 1, now, now),
            )

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        try:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(captures)")}
            if "category" not in cols:
                conn.execute("ALTER TABLE captures ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        except sqlite3.Error:
            pass
        try:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(captures)")}
            if "domain" not in cols:
                conn.execute("DROP TRIGGER IF EXISTS captures_ai")
                conn.execute("DROP TRIGGER IF EXISTS captures_ad")
                conn.execute("DROP TRIGGER IF EXISTS captures_au")
                conn.execute("ALTER TABLE captures ADD COLUMN domain TEXT NOT NULL DEFAULT '通用'")
                rows = conn.execute(
                    "SELECT id, source_text, translation, explanation, tags, category FROM captures"
                ).fetchall()
                for row in rows:
                    text = " ".join(
                        str(row[key] or "")
                        for key in ("source_text", "translation", "explanation", "tags", "category")
                    )
                    inferred = detect_domain(text)
                    conn.execute(
                        "UPDATE captures SET domain = ? WHERE id = ?",
                        ("通用" if inferred == "其他" else inferred, int(row["id"])),
                    )
        except sqlite3.Error:
            pass
        try:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(terms)")}
            if "favorite" not in cols:
                conn.execute("ALTER TABLE terms ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        except sqlite3.Error:
            pass
        try:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(terms)")}
            if "domain" not in cols:
                conn.execute("ALTER TABLE terms RENAME TO terms_old")
                conn.execute(
                    """
                    CREATE TABLE terms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        term TEXT NOT NULL,
                        domain TEXT NOT NULL DEFAULT '通用',
                        chinese_name TEXT NOT NULL DEFAULT '',
                        beginner_explanation TEXT NOT NULL DEFAULT '',
                        examples TEXT NOT NULL DEFAULT '[]',
                        first_seen_at TEXT NOT NULL,
                        review_count INTEGER NOT NULL DEFAULT 0,
                        favorite INTEGER NOT NULL DEFAULT 0,
                        UNIQUE(term, domain)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO terms
                        (id, term, domain, chinese_name, beginner_explanation, examples, first_seen_at, review_count, favorite)
                    SELECT id, term, '通用', chinese_name, beginner_explanation, examples, first_seen_at, review_count, favorite
                    FROM terms_old
                    """
                )
                conn.execute("DROP TABLE terms_old")
        except sqlite3.Error:
            pass

    def save_capture(
        self,
        image_path: str | Path,
        source_text: str,
        translation: str,
        explanation: str,
        app_name: str = "",
        tags: list[str] | None = None,
        category: str = "",
        domain: str = "通用",
    ) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO captures
                    (created_at, image_path, source_text, translation, explanation, app_name, tags, category, domain)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    str(image_path),
                    source_text,
                    translation,
                    explanation,
                    app_name,
                    json.dumps(tags or [], ensure_ascii=False),
                    category,
                    domain or "通用",
                ),
            )
            return int(cursor.lastrowid)

    def update_capture(
        self,
        capture_id: int,
        *,
        translation: str,
        explanation: str,
        tags: list[str] | None = None,
        category: str = "",
        domain: str | None = None,
    ) -> bool:
        """Update an existing capture's AI result fields, keeping created_at/image_path."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE captures
                SET translation = ?, explanation = ?, tags = ?, category = ?,
                    domain = COALESCE(?, domain)
                WHERE id = ?
                """,
                (
                    translation,
                    explanation,
                    json.dumps(tags or [], ensure_ascii=False),
                    category,
                    domain,
                    capture_id,
                ),
            )
            return cursor.rowcount > 0

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

    def search_captures_advanced(
        self,
        query: str = "",
        date_from: str = "",
        date_to: str = "",
        category: str = "",
        domain: str = "",
        has_followup: bool = False,
        has_category: bool = False,
        limit: int = 200,
    ) -> list[CaptureRecord]:
        conditions: list[str] = []
        params: list = []

        if query.strip():
            like = f"%{query.strip()}%"
            conditions.append("(source_text LIKE ? OR translation LIKE ? OR explanation LIKE ? OR tags LIKE ?)")
            params.extend([like, like, like, like])

        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to)

        if category:
            conditions.append("category = ?")
            params.append(category)

        if domain:
            conditions.append("domain = ?")
            params.append(domain)

        if has_category:
            conditions.append("category != ''")

        if has_followup:
            conditions.append(
                "EXISTS ("
                "SELECT 1 FROM messages "
                "JOIN conversations ON conversations.id = messages.conversation_id "
                "WHERE conversations.capture_id = captures.id "
                "AND messages.role = 'user' "
                "AND messages.mode != 'capture'"
                ")"
            )

        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM captures
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [_capture_from_row(row) for row in rows]

    def capture_domain_counts(self) -> list[tuple[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT domain, COUNT(*) AS n
                FROM captures
                GROUP BY domain
                ORDER BY n DESC, domain
                """
            ).fetchall()
        return [(str(row["domain"] or "通用"), int(row["n"])) for row in rows]

    def get_capture(self, capture_id: int) -> CaptureRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        return _capture_from_row(row) if row else None

    def upsert_terms(self, terms: list[dict[str, Any]], domain: str = "通用") -> None:
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
                        (term, domain, chinese_name, beginner_explanation, examples, first_seen_at, review_count)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(term, domain) DO UPDATE SET
                        chinese_name = excluded.chinese_name,
                        beginner_explanation = excluded.beginner_explanation,
                        examples = excluded.examples,
                        review_count = terms.review_count + 1
                    """,
                    (
                        name,
                        domain,
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
        domain: str = "通用",
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
                    SET term = ?, domain = ?, chinese_name = ?, beginner_explanation = ?, examples = ?
                    WHERE id = ?
                    """,
                    (name, domain, chinese_name, beginner_explanation, payload, term_id),
                )
                return term_id
            cursor = conn.execute(
                """
                INSERT INTO terms
                    (term, domain, chinese_name, beginner_explanation, examples, first_seen_at, review_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(term, domain) DO UPDATE SET
                    chinese_name = excluded.chinese_name,
                    beginner_explanation = excluded.beginner_explanation,
                    examples = excluded.examples
                """,
                (
                    name,
                    domain,
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

    def toggle_term_favorite(self, term_id: int) -> bool:
        with self._connect() as conn:
            conn.execute(
                "UPDATE terms SET favorite = 1 - favorite WHERE id = ?",
                (term_id,),
            )
            row = conn.execute("SELECT favorite FROM terms WHERE id = ?", (term_id,)).fetchone()
        return bool(row["favorite"]) if row else False

    def delete_capture(self, capture_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))

    def delete_captures_before(self, before_date: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM captures WHERE created_at < ?",
                (before_date,),
            )
            return int(cursor.rowcount)

    def vacuum(self) -> None:
        with self._connect() as conn:
            conn.execute("VACUUM")

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

    def list_terms(
        self,
        query: str = "",
        domain: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> list[TermRecord]:
        query = query.strip()
        where: list[str] = []
        params: list = []
        if query:
            like = f"%{query}%"
            where.append("(term LIKE ? OR chinese_name LIKE ? OR beginner_explanation LIKE ?)")
            params.extend([like, like, like])
        if domain:
            where.append("domain = ?")
            params.append(domain)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM terms
                {where_sql}
                ORDER BY review_count DESC, first_seen_at DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        return [_term_from_row(row) for row in rows]

    def count_favorite_terms(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM terms WHERE favorite = 1"
            ).fetchone()
        return int(row[0]) if row else 0

    def count_terms(self, query: str = "", domain: str = "") -> int:
        query = query.strip()
        where: list[str] = []
        params: list = []
        if query:
            like = f"%{query}%"
            where.append("(term LIKE ? OR chinese_name LIKE ? OR beginner_explanation LIKE ?)")
            params.extend([like, like, like])
        if domain:
            where.append("domain = ?")
            params.append(domain)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM terms {where_sql}", params
            ).fetchone()
        return int(row[0]) if row else 0

    def term_domain_counts(self, query: str = "") -> list[tuple[str, int]]:
        """Count terms per domain (optional search query scoping)."""
        query = query.strip()
        where: list[str] = []
        params: list = []
        if query:
            like = f"%{query}%"
            where.append("(term LIKE ? OR chinese_name LIKE ? OR beginner_explanation LIKE ?)")
            params.extend([like, like, like])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT domain, COUNT(*) AS n FROM terms
                {where_sql}
                GROUP BY domain ORDER BY n DESC, domain
                """,
                params,
            ).fetchall()
        return [(str(row[0]), int(row[1])) for row in rows]

    def get_statistics(self) -> dict[str, Any]:
        with self._connect() as conn:
            total_captures = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
            total_terms = conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
            favorite_terms = conn.execute("SELECT COUNT(*) FROM terms WHERE favorite = 1").fetchone()[0]
            total_conversations = conn.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0]

            today = datetime.now().strftime("%Y-%m-%d")
            today_captures = conn.execute(
                "SELECT COUNT(*) FROM captures WHERE created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()[0]

            week_start = datetime.now()
            from datetime import timedelta
            week_start = (week_start - timedelta(days=week_start.weekday())).strftime("%Y-%m-%d")
            week_captures = conn.execute(
                "SELECT COUNT(*) FROM captures WHERE created_at >= ?",
                (week_start,),
            ).fetchone()[0]

            month_start = datetime.now().strftime("%Y-%m")
            month_captures = conn.execute(
                "SELECT COUNT(*) FROM captures WHERE created_at LIKE ?",
                (f"{month_start}%",),
            ).fetchone()[0]

            tag_distribution: dict[str, int] = {}
            rows = conn.execute("SELECT tags FROM captures WHERE tags != '[]'").fetchall()
            for row in rows:
                for tag in _loads_list(str(row[0])):
                    tag_distribution[tag] = tag_distribution.get(tag, 0) + 1
            tag_distribution = dict(sorted(tag_distribution.items(), key=lambda x: x[1], reverse=True)[:20])

            category_distribution: dict[str, int] = {}
            rows = conn.execute("SELECT category FROM captures WHERE category != ''").fetchall()
            for row in rows:
                cat = str(row[0])
                category_distribution[cat] = category_distribution.get(cat, 0) + 1
            category_distribution = dict(sorted(category_distribution.items(), key=lambda x: x[1], reverse=True))

            daily_activity: dict[str, int] = {}
            rows = conn.execute(
                "SELECT substr(created_at, 1, 10) AS day, COUNT(*) FROM captures GROUP BY day ORDER BY day DESC LIMIT 90",
            ).fetchall()
            for row in rows:
                daily_activity[str(row[0])] = int(row[1])

            avg_explanation_length = conn.execute(
                "SELECT AVG(LENGTH(explanation)) FROM captures WHERE explanation != ''",
            ).fetchone()[0]

            last_capture = conn.execute(
                "SELECT created_at FROM captures ORDER BY created_at DESC LIMIT 1",
            ).fetchone()
            last_capture_at = str(last_capture[0]) if last_capture else ""

        return {
            "total_captures": total_captures,
            "total_terms": total_terms,
            "favorite_terms": favorite_terms,
            "total_conversations": total_conversations,
            "today_captures": today_captures,
            "week_captures": week_captures,
            "month_captures": month_captures,
            "tag_distribution": tag_distribution,
            "category_distribution": category_distribution,
            "daily_activity": daily_activity,
            "avg_explanation_length": round(avg_explanation_length) if avg_explanation_length else 0,
            "last_capture_at": last_capture_at,
        }

    def save_embedding(self, capture_id: int, embedding: bytes, model: str = "") -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO capture_embeddings(capture_id, embedding, model, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    embedding = excluded.embedding,
                    model = excluded.model,
                    created_at = excluded.created_at
                """,
                (capture_id, embedding, model, created_at),
            )

    def get_embedding(self, capture_id: int) -> bytes | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT embedding FROM capture_embeddings WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        return bytes(row[0]) if row else None

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

    def list_contexts(self) -> list[ContextRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM contexts ORDER BY builtin DESC, id ASC"
            ).fetchall()
        return [_context_from_row(row) for row in rows]

    def get_context(self, context_id: int) -> ContextRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM contexts WHERE id = ?", (context_id,)
            ).fetchone()
        return _context_from_row(row) if row else None

    def save_context(
        self,
        name: str,
        domain: str = "通用",
        scene: str = "通用",
        summary: str = "",
        instruction: str = "",
        context_id: int | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            if context_id is not None:
                existing = conn.execute(
                    "SELECT builtin FROM contexts WHERE id = ?", (context_id,)
                ).fetchone()
                if existing is None:
                    raise ValueError(f"上下文不存在: {context_id}")
                if existing["builtin"]:
                    raise ValueError("内置上下文不可修改")
                conn.execute(
                    """
                    UPDATE contexts
                    SET name = ?, domain = ?, scene = ?, summary = ?,
                        instruction = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name, domain, scene, summary, instruction, now, context_id),
                )
                return context_id
            cursor = conn.execute(
                """
                INSERT INTO contexts (name, domain, scene, summary, instruction, builtin, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (name, domain, scene, summary, instruction, now, now),
            )
            return int(cursor.lastrowid)

    def delete_context(self, context_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM contexts WHERE id = ? AND builtin = 0", (context_id,)
            )
            return cursor.rowcount > 0

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
        category=str(row["category"]) if "category" in row.keys() else "",
        domain=str(row["domain"]) if "domain" in row.keys() else "通用",
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
        domain=str(row["domain"]) if "domain" in row.keys() else "通用",
        favorite=bool(row["favorite"]) if "favorite" in row.keys() else False,
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


def _context_from_row(row: sqlite3.Row) -> ContextRecord:
    return ContextRecord(
        id=int(row["id"]),
        name=str(row["name"]),
        domain=str(row["domain"]),
        scene=str(row["scene"]),
        summary=str(row["summary"]),
        instruction=str(row["instruction"]),
        builtin=bool(row["builtin"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _loads_list(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]
