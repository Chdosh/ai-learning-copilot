from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from app.paths import DB_PATH, ensure_app_dirs
from app.services.context_detector import detect_domain
from app.services.term_quality import classify_difficulty, is_pure_stopword


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
    difficulty: str = ""
    status: str = "new"
    notes: str = ""
    last_review_at: str = ""
    due_at: str = ""
    interval_days: int = 0
    ease: float = 2.5
    lapses: int = 0
    views: int = 0
    occurrences: int = 0
    user_edited: bool = False


@dataclass(slots=True)
class LearningTip:
    id: int
    capture_id: int
    content: str
    tip_type: str = "followup"
    status: str = "pending"
    domain: str = ""
    context_id: int | None = None
    created_at: str = ""
    done_at: str = ""


@dataclass(slots=True)
class ConversationMessage:
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str
    mode: str


@dataclass(slots=True)
class TermAggregate:
    """术语视图的原始聚合事实：SQLite adapter 输出，规则判断留在 KnowledgeBase。"""

    term: TermRecord
    source_count: int
    latest_source_at: str
    exact_count: int
    other_count: int
    null_count: int


@dataclass(slots=True)
class AccumulationAggregate:
    """学习页积累的原始来源事实；展示理由由 KnowledgeBase 生成。"""

    term: TermRecord
    latest_capture_id: int
    latest_capture_at: str
    latest_capture_title: str
    source_count: int
    exact_count: int
    other_count: int
    null_count: int


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
                    domain TEXT NOT NULL DEFAULT '通用',
                    context_id INTEGER
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS term_captures (
                    term_id INTEGER NOT NULL,
                    capture_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (term_id, capture_id),
                    FOREIGN KEY(term_id) REFERENCES terms(id) ON DELETE CASCADE,
                    FOREIGN KEY(capture_id) REFERENCES captures(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_tips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id INTEGER NOT NULL,
                    context_id INTEGER,
                    domain TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    tip_type TEXT NOT NULL DEFAULT 'followup',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    done_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(capture_id) REFERENCES captures(id) ON DELETE CASCADE
                )
                """
            )
            self._initialize_contexts_table(conn)
            self._migrate_schema(conn)
            self._try_initialize_fts(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_term_captures_capture
                ON term_captures(capture_id, term_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_captures_context
                ON captures(context_id, created_at, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term_id INTEGER NOT NULL,
                    grade INTEGER NOT NULL CHECK (grade IN (0, 1, 2)),
                    reviewed_at TEXT NOT NULL,
                    interval_days INTEGER NOT NULL,
                    ease REAL NOT NULL,
                    lapses INTEGER NOT NULL,
                    term_domain TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(term_id) REFERENCES terms(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_events_term_time
                ON review_events(term_id, reviewed_at, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_events_time
                ON review_events(reviewed_at, id)
                """
            )

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
        # 个人知识库（0.7）：间隔重复 / 行为信号 / 治理字段，全部 ALTER TABLE 平滑升级
        term_columns: dict[str, str] = {
            "difficulty": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'new'",
            "notes": "TEXT NOT NULL DEFAULT ''",
            "last_review_at": "TEXT NOT NULL DEFAULT ''",
            "due_at": "TEXT NOT NULL DEFAULT ''",
            "interval_days": "INTEGER NOT NULL DEFAULT 0",
            "ease": "REAL NOT NULL DEFAULT 2.5",
            "lapses": "INTEGER NOT NULL DEFAULT 0",
            "views": "INTEGER NOT NULL DEFAULT 0",
            "occurrences": "INTEGER NOT NULL DEFAULT 0",
            "user_edited": "INTEGER NOT NULL DEFAULT 0",
        }
        try:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(terms)")}
            for name, ddl in term_columns.items():
                if name not in cols:
                    conn.execute(f"ALTER TABLE terms ADD COLUMN {name} {ddl}")
            conn.execute(
                "UPDATE terms SET occurrences = review_count "
                "WHERE occurrences = 0 AND review_count > 0"
            )
        except sqlite3.Error:
            pass
        # 知识脊柱：capture 发生时的真实学习方向（旧数据保持 NULL，不猜测回填）
        try:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(captures)")}
            if "context_id" not in cols:
                conn.execute("ALTER TABLE captures ADD COLUMN context_id INTEGER")
        except sqlite3.Error:
            pass
        # 可靠性修复：清理旧版本删除 capture 遗留的 conversation/message 孤儿
        # （幂等：新删除路径已级联清理，此处只兜底历史残留）
        try:
            conn.execute(
                "DELETE FROM conversations WHERE capture_id NOT IN (SELECT id FROM captures)"
            )
            conn.execute(
                "DELETE FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)"
            )
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
        context_id: int | None = None,
    ) -> int:
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO captures
                    (created_at, image_path, source_text, translation, explanation,
                     app_name, tags, category, domain, context_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    context_id,
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
        context_id: int | None = None,
        replace_context: bool = False,
    ) -> bool:
        """Update an existing capture's AI result fields, keeping created_at/image_path.

        replace_context is explicit because ordinary metadata updates must
        preserve the direction fact, while a user-initiated retry runs under
        the direction that is active for the replacement AI result.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE captures
                SET translation = ?, explanation = ?, tags = ?, category = ?,
                    domain = COALESCE(?, domain),
                    context_id = CASE WHEN ? THEN ? ELSE context_id END
                WHERE id = ?
                """,
                (
                    translation,
                    explanation,
                    json.dumps(tags or [], ensure_ascii=False),
                    category,
                    domain,
                    1 if replace_context else 0,
                    context_id,
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

    def _upsert_terms(
        self,
        terms: list[dict[str, Any]],
        domain: str = "通用",
        capture_id: int | None = None,
    ) -> list[int]:
        """Upsert AI-extracted terms with a quality-first merge strategy.

        - Pure stopwords are skipped (never meaningful terms).
        - Difficulty is classified locally (rule-based, zero API cost).
        - Fill-blanks-first: a new explanation only fills empty fields of the
          existing row; user-edited rows are never overwritten by AI output.
        - Occurrence facts: when ``capture_id`` is given, ``occurrences`` counts
          distinct captures (a retry of the same capture never inflates it);
          without a capture the legacy per-call counting is kept.
        - When ``capture_id`` is given, the term↔capture backlink is written
          so each term keeps its origin context.
        """
        ids, _ = self._ingest_terms(terms, domain=domain, capture_id=capture_id)
        return ids

    def _ingest_terms(
        self,
        terms: list[dict[str, Any]],
        domain: str = "通用",
        capture_id: int | None = None,
    ) -> tuple[list[int], int]:
        """Shared knowledge ingest core; returns ``(term_ids, new_source_links)``.

        Internal seam used by :class:`app.services.knowledge_base.KnowledgeBase`;
        see ``_upsert_terms`` for the merge semantics.
        """
        if not terms:
            return [], 0
        now = datetime.now().isoformat(timespec="seconds")
        ids: list[int] = []
        new_source_links = 0
        with self._connect() as conn:
            for term in terms:
                name = str(term.get("term") or "").strip()
                if not name or is_pure_stopword(name):
                    continue
                term_domain = str(term.get("domain") or "").strip() or domain or "通用"
                existing = conn.execute(
                    "SELECT id FROM terms WHERE term = ? AND domain = ?",
                    (name, term_domain),
                ).fetchone()
                if existing is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO terms
                            (term, domain, chinese_name, beginner_explanation, examples,
                             first_seen_at, review_count, occurrences, difficulty)
                        VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)
                        """,
                        (
                            name,
                            term_domain,
                            str(term.get("chinese_name") or ""),
                            str(term.get("beginner_explanation") or ""),
                            json.dumps(term.get("examples") or [], ensure_ascii=False),
                            now,
                            classify_difficulty(name),
                        ),
                    )
                    term_id = int(cursor.lastrowid or 0)
                else:
                    term_id = int(existing["id"])
                    conn.execute(
                        """
                        UPDATE terms SET
                            chinese_name = CASE
                                WHEN user_edited = 1 THEN chinese_name
                                WHEN chinese_name != '' THEN chinese_name
                                ELSE ? END,
                            beginner_explanation = CASE
                                WHEN user_edited = 1 THEN beginner_explanation
                                WHEN beginner_explanation != '' THEN beginner_explanation
                                ELSE ? END,
                            examples = CASE
                                WHEN user_edited = 1 THEN examples
                                WHEN examples != '[]' THEN examples
                                ELSE ? END,
                            difficulty = CASE
                                WHEN difficulty != '' THEN difficulty
                                ELSE ? END
                        WHERE id = ?
                        """,
                        (
                            str(term.get("chinese_name") or ""),
                            str(term.get("beginner_explanation") or ""),
                            json.dumps(term.get("examples") or [], ensure_ascii=False),
                            classify_difficulty(name),
                            term_id,
                        ),
                    )
                if not term_id:
                    continue
                if capture_id:
                    link = conn.execute(
                        """
                        INSERT OR IGNORE INTO term_captures(term_id, capture_id, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (term_id, capture_id, now),
                    )
                    if link.rowcount > 0 and existing is not None:
                        # 新来源链接：初次插入的 occurrences=1 已计入首个来源，
                        # 只有既有术语在别的 capture 再次出现时才累计。
                        new_source_links += 1
                        conn.execute(
                            """
                            UPDATE terms
                            SET occurrences = occurrences + 1, review_count = review_count + 1
                            WHERE id = ?
                            """,
                            (term_id,),
                        )
                    elif link.rowcount > 0:
                        new_source_links += 1
                else:
                    if existing is not None:
                        conn.execute(
                            """
                            UPDATE terms
                            SET occurrences = occurrences + 1, review_count = review_count + 1
                            WHERE id = ?
                            """,
                            (term_id,),
                        )
                ids.append(term_id)
        return ids, new_source_links

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
                    SET term = ?, domain = ?, chinese_name = ?, beginner_explanation = ?,
                        examples = ?, user_edited = 1
                    WHERE id = ?
                    """,
                    (name, domain, chinese_name, beginner_explanation, payload, term_id),
                )
                return term_id
            existing = conn.execute(
                "SELECT id FROM terms WHERE term = ? AND domain = ?",
                (name, domain),
            ).fetchone()
            if existing is not None:
                term_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE terms
                    SET chinese_name = ?, beginner_explanation = ?, examples = ?, user_edited = 1
                    WHERE id = ?
                    """,
                    (chinese_name, beginner_explanation, payload, term_id),
                )
                return term_id
            cursor = conn.execute(
                """
                INSERT INTO terms
                    (term, domain, chinese_name, beginner_explanation, examples,
                     first_seen_at, review_count, occurrences, user_edited)
                VALUES (?, ?, ?, ?, ?, ?, 1, 1, 1)
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

    def get_term(self, term_id: int) -> TermRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM terms WHERE id = ?", (term_id,)).fetchone()
        return _term_from_row(row) if row else None

    def delete_term(self, term_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM review_events WHERE term_id = ?", (term_id,))
            conn.execute("DELETE FROM term_captures WHERE term_id = ?", (term_id,))
            conn.execute("DELETE FROM terms WHERE id = ?", (term_id,))

    def _toggle_term_favorite(self, term_id: int) -> bool:
        """Flip favorite; favoriting schedules the term into the review queue."""
        row = self.get_term(term_id)
        if row is None:
            return False
        self._set_term_favorite(term_id, not row.favorite)
        return not row.favorite

    def _set_term_favorite(self, term_id: int, favorite: bool) -> None:
        """Set favorite explicitly; the single write point for favorite semantics."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            if favorite:
                conn.execute(
                    "UPDATE terms SET favorite = 1, due_at = ?, status = 'review' WHERE id = ?",
                    (now, term_id),
                )
            else:
                conn.execute(
                    "UPDATE terms SET favorite = 0, due_at = '', status = 'new' WHERE id = ?",
                    (term_id,),
                )

    def _record_term_view(self, term_id: int) -> None:
        """Bump the view counter — a behavior signal used to un-fold basic terms."""
        with self._connect() as conn:
            conn.execute("UPDATE terms SET views = views + 1 WHERE id = ?", (term_id,))

    def _review_term(self, term_id: int, grade: int) -> dict[str, object] | None:
        """Apply a simplified SM-2 update (0 = forgot, 1 = fuzzy, 2 = remembered)."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM terms WHERE id = ?", (term_id,)).fetchone()
            if row is None:
                return None
            ease = float(row["ease"] if row["ease"] else 2.5)
            interval = int(row["interval_days"] or 0)
            lapses = int(row["lapses"] or 0)
            if grade <= 0:
                interval = 1
                lapses += 1
                ease = max(1.3, ease - 0.2)
            elif grade == 1:
                interval = max(1, interval)
                ease = max(1.3, ease - 0.1)
            else:
                if interval <= 0:
                    interval = 1
                elif interval == 1:
                    interval = 6
                else:
                    interval = max(2, round(interval * ease))
                ease = min(2.5, ease + 0.1)
            now = datetime.now()
            due_at = (now + timedelta(days=interval)).isoformat(timespec="seconds")
            last_review_at = now.isoformat(timespec="seconds")
            conn.execute(
                """
                UPDATE terms SET ease = ?, interval_days = ?, lapses = ?,
                    due_at = ?, last_review_at = ?, status = 'review'
                WHERE id = ?
                """,
                (ease, interval, lapses, due_at, last_review_at, term_id),
            )
            conn.execute(
                """
                INSERT INTO review_events
                    (term_id, grade, reviewed_at, interval_days, ease, lapses, term_domain)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    term_id,
                    grade,
                    last_review_at,
                    interval,
                    ease,
                    lapses,
                    str(row["domain"] or ""),
                ),
            )
        return {
            "interval_days": interval,
            "due_at": due_at,
            "ease": round(ease, 2),
            "lapses": lapses,
        }

    def _list_due_terms(self, limit: int = 50) -> list[TermRecord]:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM terms
                WHERE favorite = 1 AND due_at != '' AND due_at <= ?
                ORDER BY due_at ASC, occurrences DESC, id ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [_term_from_row(row) for row in rows]

    def _count_due_terms(self) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM terms
                WHERE favorite = 1 AND due_at != '' AND due_at <= ?
                """,
                (now,),
            ).fetchone()
        return int(row[0]) if row else 0

    def _list_term_captures(self, term_id: int, limit: int = 30) -> list[CaptureRecord]:
        """Captures where this term appeared — the term's origin contexts."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.* FROM captures c
                JOIN term_captures tc ON tc.capture_id = c.id
                WHERE tc.term_id = ?
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT ?
                """,
                (term_id, limit),
            ).fetchall()
        return [_capture_from_row(row) for row in rows]

    def _save_learning_tip(
        self,
        capture_id: int,
        content: str,
        tip_type: str = "followup",
        domain: str = "",
        context_id: int | None = None,
    ) -> int:
        content = (content or "").strip()
        if not content:
            return 0
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO learning_tips(capture_id, context_id, domain, content, tip_type, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (capture_id, context_id, domain or "", content, tip_type or "followup", created_at),
            )
            return int(cursor.lastrowid or 0)

    def _save_tip_if_absent(
        self,
        capture_id: int,
        content: str,
        tip_type: str = "followup",
        domain: str = "",
        context_id: int | None = None,
    ) -> int:
        """Insert a learning tip unless the same capture already has one with
        identical content/type/domain — then reuse the existing row id."""
        content = (content or "").strip()
        if not content:
            return 0
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM learning_tips
                WHERE capture_id = ? AND content = ? AND tip_type = ? AND domain = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (capture_id, content, tip_type or "followup", domain or ""),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
            created_at = datetime.now().isoformat(timespec="seconds")
            cursor = conn.execute(
                """
                INSERT INTO learning_tips(capture_id, context_id, domain, content, tip_type, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (capture_id, context_id, domain or "", content, tip_type or "followup", created_at),
            )
            return int(cursor.lastrowid or 0)

    def _list_learning_tips(
        self,
        status: str = "pending",
        domain: str = "",
        limit: int = 100,
    ) -> list[LearningTip]:
        where: list[str] = []
        params: list = []
        if status:
            where.append("status = ?")
            params.append(status)
        if domain:
            where.append("domain = ?")
            params.append(domain)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM learning_tips
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [_tip_from_row(row) for row in rows]

    def _set_learning_tip_status(self, tip_id: int, status: str) -> bool:
        done_at = (
            datetime.now().isoformat(timespec="seconds")
            if status in ("done", "ignored")
            else ""
        )
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE learning_tips SET status = ?, done_at = ? WHERE id = ?",
                (status, done_at, tip_id),
            )
            return cursor.rowcount > 0

    def _get_learning_tip(self, tip_id: int) -> LearningTip | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM learning_tips WHERE id = ?", (tip_id,)).fetchone()
        return _tip_from_row(row) if row else None

    def _count_learning_tips(self, status: str = "pending") -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM learning_tips WHERE status = ?",
                (status,),
            ).fetchone()
        return int(row[0]) if row else 0

    def delete_capture(self, capture_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM term_captures WHERE capture_id = ?", (capture_id,))
            conn.execute("DELETE FROM learning_tips WHERE capture_id = ?", (capture_id,))
            conn.execute(
                """
                DELETE FROM messages
                WHERE conversation_id IN (SELECT id FROM conversations WHERE capture_id = ?)
                """,
                (capture_id,),
            )
            conn.execute("DELETE FROM conversations WHERE capture_id = ?", (capture_id,))
            conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))

    def delete_captures_before(self, before_date: str) -> int:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM term_captures
                WHERE capture_id IN (SELECT id FROM captures WHERE created_at < ?)
                """,
                (before_date,),
            )
            conn.execute(
                """
                DELETE FROM learning_tips
                WHERE capture_id IN (SELECT id FROM captures WHERE created_at < ?)
                """,
                (before_date,),
            )
            conn.execute(
                """
                DELETE FROM messages
                WHERE conversation_id IN (
                    SELECT c.id FROM conversations c
                    JOIN captures cap ON cap.id = c.capture_id
                    WHERE cap.created_at < ?
                )
                """,
                (before_date,),
            )
            conn.execute(
                """
                DELETE FROM conversations
                WHERE capture_id IN (SELECT id FROM captures WHERE created_at < ?)
                """,
                (before_date,),
            )
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
        exclude_basic: bool = False,
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
        if exclude_basic and not query:
            # 折叠低价值词，但保留有任何行为信号（收藏/查看）的词
            where.append("NOT (difficulty = 'basic' AND favorite = 0 AND views = 0)")
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

    def count_terms(self, query: str = "", domain: str = "", exclude_basic: bool = False) -> int:
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
        if exclude_basic and not query:
            where.append("NOT (difficulty = 'basic' AND favorite = 0 AND views = 0)")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM terms {where_sql}", params
            ).fetchone()
        return int(row[0]) if row else 0

    def term_domain_counts(self, query: str = "", exclude_basic: bool = False) -> list[tuple[str, int]]:
        """Count terms per domain (optional search query scoping)."""
        query = query.strip()
        where: list[str] = []
        params: list = []
        if query:
            like = f"%{query}%"
            where.append("(term LIKE ? OR chinese_name LIKE ? OR beginner_explanation LIKE ?)")
            params.extend([like, like, like])
        if exclude_basic and not query:
            where.append("NOT (difficulty = 'basic' AND favorite = 0 AND views = 0)")
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

    # ------------------------------------------------------------------
    # 术语视图聚合查询（知识库 P1：SQLite adapter，规则由 KnowledgeBase 持有）
    # ------------------------------------------------------------------

    @staticmethod
    def _build_term_view_filter(
        search: str,
        domain: str,
        fold_basic: bool,
        scope_current_direction: bool,
        context_param: int,
        effective_domain: str,
    ) -> tuple[str, list]:
        where: list[str] = []
        params: list = []
        if search:
            like = f"%{search}%"
            where.append("(t.term LIKE ? OR t.chinese_name LIKE ? OR t.beginner_explanation LIKE ?)")
            params.extend([like, like, like])
        if domain:
            where.append("t.domain = ?")
            params.append(domain)
        if fold_basic:
            where.append(
                "NOT (t.difficulty = 'basic' AND t.favorite = 0 AND t.user_edited = 0 AND t.views = 0)"
            )
        if scope_current_direction:
            if context_param > 0:
                where.append(
                    "(COALESCE(s.exact_count, 0) > 0 "
                    "OR (COALESCE(s.other_count, 0) = 0 AND t.domain = ?))"
                )
                params.append(effective_domain)
            else:
                where.append("t.domain = ?")
                params.append(effective_domain)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return where_sql, params

    def _fetch_term_aggregates(
        self,
        *,
        search: str = "",
        domain: str = "",
        fold_basic: bool = False,
        scope_current_direction: bool = False,
        current_context_id: int | None = None,
        effective_domain: str = "通用",
    ) -> list[TermAggregate]:
        context_param = current_context_id if current_context_id is not None else -1
        where_sql, params = self._build_term_view_filter(
            search=search,
            domain=domain,
            fold_basic=fold_basic,
            scope_current_direction=scope_current_direction,
            context_param=context_param,
            effective_domain=effective_domain,
        )
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT t.*,
                       COALESCE(s.source_count, 0) AS source_count,
                       s.latest_source_at AS latest_source_at,
                       COALESCE(s.exact_count, 0) AS exact_count,
                       COALESCE(s.other_count, 0) AS other_count,
                       COALESCE(s.null_count, 0) AS null_count
                FROM terms t
                LEFT JOIN (
                    SELECT tc.term_id AS term_id,
                           COUNT(DISTINCT tc.capture_id) AS source_count,
                           MAX(c.created_at) AS latest_source_at,
                           SUM(CASE WHEN c.context_id = ? THEN 1 ELSE 0 END) AS exact_count,
                           SUM(CASE WHEN c.context_id IS NOT NULL AND c.context_id != ? THEN 1 ELSE 0 END) AS other_count,
                           SUM(CASE WHEN c.context_id IS NULL THEN 1 ELSE 0 END) AS null_count
                    FROM term_captures tc
                    JOIN captures c ON c.id = tc.capture_id
                    GROUP BY tc.term_id
                ) s ON s.term_id = t.id
                {where_sql}
                """,
                (context_param, context_param, *params),
            ).fetchall()
        return [
            TermAggregate(
                term=_term_from_row(row),
                source_count=int(row["source_count"]),
                latest_source_at=str(row["latest_source_at"] or ""),
                exact_count=int(row["exact_count"]),
                other_count=int(row["other_count"]),
                null_count=int(row["null_count"]),
            )
            for row in rows
        ]

    def _fetch_accumulation_aggregates(
        self,
        *,
        current_context_id: int | None,
        limit: int,
    ) -> list[AccumulationAggregate]:
        """一次 SQL 返回最近积累及其真实来源、方向事实。

        最新来源由 captures.created_at 决定，并用 capture id 作为同秒稳定键；
        没有仍然存在的 capture 来源的术语不会进入结果。
        """
        context_param = current_context_id if current_context_id is not None else -1
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH source_facts AS (
                    SELECT tc.term_id AS term_id,
                           COUNT(DISTINCT tc.capture_id) AS source_count,
                           SUM(CASE WHEN c.context_id = ? THEN 1 ELSE 0 END) AS exact_count,
                           SUM(
                               CASE
                                   WHEN c.context_id IS NOT NULL AND c.context_id != ?
                                   THEN 1 ELSE 0
                               END
                           ) AS other_count,
                           SUM(CASE WHEN c.context_id IS NULL THEN 1 ELSE 0 END) AS null_count
                    FROM term_captures tc
                    JOIN captures c ON c.id = tc.capture_id
                    GROUP BY tc.term_id
                ),
                ranked_sources AS (
                    SELECT tc.term_id AS term_id,
                           c.id AS latest_capture_id,
                           c.created_at AS latest_capture_at,
                           c.source_text AS latest_capture_title,
                           ROW_NUMBER() OVER (
                               PARTITION BY tc.term_id
                               ORDER BY c.created_at DESC, c.id DESC
                           ) AS source_rank
                    FROM term_captures tc
                    JOIN captures c ON c.id = tc.capture_id
                )
                SELECT t.*,
                       rs.latest_capture_id,
                       rs.latest_capture_at,
                       rs.latest_capture_title,
                       sf.source_count,
                       sf.exact_count,
                       sf.other_count,
                       sf.null_count
                FROM source_facts sf
                JOIN ranked_sources rs
                  ON rs.term_id = sf.term_id AND rs.source_rank = 1
                JOIN terms t ON t.id = sf.term_id
                ORDER BY rs.latest_capture_at DESC, rs.latest_capture_id DESC
                LIMIT ?
                """,
                (context_param, context_param, limit),
            ).fetchall()
        return [
            AccumulationAggregate(
                term=_term_from_row(row),
                latest_capture_id=int(row["latest_capture_id"]),
                latest_capture_at=str(row["latest_capture_at"]),
                latest_capture_title=str(row["latest_capture_title"] or ""),
                source_count=int(row["source_count"]),
                exact_count=int(row["exact_count"]),
                other_count=int(row["other_count"]),
                null_count=int(row["null_count"]),
            )
            for row in rows
        ]

    def _fetch_term_domain_counts(
        self,
        *,
        search: str = "",
        fold_basic: bool = False,
    ) -> list[tuple[str, int]]:
        """领域统计：应用视图折叠与搜索条件，但在领域筛选前统计。"""
        where: list[str] = []
        params: list = []
        if search:
            like = f"%{search}%"
            where.append("(term LIKE ? OR chinese_name LIKE ? OR beginner_explanation LIKE ?)")
            params.extend([like, like, like])
        if fold_basic:
            where.append(
                "NOT (difficulty = 'basic' AND favorite = 0 AND user_edited = 0 AND views = 0)"
            )
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
    keys = row.keys()
    occurrences = (
        int(row["occurrences"])
        if "occurrences" in keys and row["occurrences"]
        else int(row["review_count"])
    )
    return TermRecord(
        id=int(row["id"]),
        term=str(row["term"]),
        chinese_name=str(row["chinese_name"]),
        beginner_explanation=str(row["beginner_explanation"]),
        examples=_loads_list(row["examples"]),
        first_seen_at=str(row["first_seen_at"]),
        review_count=occurrences,
        domain=str(row["domain"]) if "domain" in row.keys() else "通用",
        favorite=bool(row["favorite"]) if "favorite" in row.keys() else False,
        difficulty=str(row["difficulty"]) if "difficulty" in keys else "",
        status=str(row["status"]) if "status" in keys else "new",
        notes=str(row["notes"]) if "notes" in keys else "",
        last_review_at=str(row["last_review_at"]) if "last_review_at" in keys else "",
        due_at=str(row["due_at"]) if "due_at" in keys else "",
        interval_days=int(row["interval_days"] or 0) if "interval_days" in keys else 0,
        ease=float(row["ease"] if row["ease"] else 2.5) if "ease" in keys else 2.5,
        lapses=int(row["lapses"] or 0) if "lapses" in keys else 0,
        views=int(row["views"] or 0) if "views" in keys else 0,
        occurrences=occurrences,
        user_edited=bool(row["user_edited"]) if "user_edited" in keys else False,
    )


def _tip_from_row(row: sqlite3.Row) -> LearningTip:
    return LearningTip(
        id=int(row["id"]),
        capture_id=int(row["capture_id"]),
        content=str(row["content"]),
        tip_type=str(row["tip_type"] or "followup"),
        status=str(row["status"] or "pending"),
        domain=str(row["domain"] or ""),
        context_id=int(row["context_id"]) if row["context_id"] else None,
        created_at=str(row["created_at"] or ""),
        done_at=str(row["done_at"] or ""),
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
