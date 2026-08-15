"""P1 术语查询基准（验收用，不进 pytest 收集）。

用法：
    python tests/bench_term_query.py             # 默认 1000 术语 / 10000 来源链接
    python tests/bench_term_query.py 5000 50000  # 自定义规模

验收红线：普通开发机单页查询 < 100 ms
（docs/personal_knowledge_base_plan.md §6.11）。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from app.services.history_store import HistoryStore
from app.services.knowledge_base import KnowledgeBase, TermQuery

RED_LINE_MS = 100.0

_TERM_INSERT = (
    "INSERT INTO terms (term, domain, chinese_name, beginner_explanation, examples, "
    "first_seen_at, review_count, favorite, difficulty, status, notes, last_review_at, "
    "due_at, interval_days, ease, lapses, views, occurrences, user_edited) "
    "VALUES (?, ?, '', '', '[]', ?, 1, 0, '', 'new', '', '', '', 0, 2.5, 0, 0, 1, 0)"
)

_CAPTURE_INSERT = (
    "INSERT INTO captures (created_at, image_path, source_text, translation, explanation, "
    "app_name, tags, category, domain, context_id) "
    "VALUES (?, '', '', '', '', '', '[]', '', ?, NULL)"
)


def build_fixture(db_path: Path, term_count: int, link_count: int) -> HistoryStore:
    store = HistoryStore(db_path=db_path)
    now = datetime.now().isoformat(timespec="seconds")
    capture_count = max(1, link_count // 10)
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            _CAPTURE_INSERT,
            [(now, f"领域{i % 8}") for i in range(capture_count)],
        )
        conn.executemany(
            _TERM_INSERT,
            [(f"term{i}", f"领域{i % 8}", now) for i in range(term_count)],
        )
        term_ids = [row[0] for row in conn.execute("SELECT id FROM terms ORDER BY id")]
        capture_ids = [row[0] for row in conn.execute("SELECT id FROM captures ORDER BY id")]
        conn.executemany(
            "INSERT OR IGNORE INTO term_captures (term_id, capture_id, created_at) "
            "VALUES (?, ?, ?)",
            [
                (term_ids[i % term_count], capture_ids[i % capture_count], now)
                for i in range(link_count)
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return store


def run_bench(term_count: int, link_count: int) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        store = build_fixture(Path(tmpdir) / "bench.db", term_count, link_count)
        kb = KnowledgeBase(store)
        results: list[tuple[str, float, int]] = []
        for view in ("focus", "current_direction", "all"):
            query = TermQuery(
                view=view,
                limit=20,
                current_context_id=1,
                effective_domain="领域0",
            )
            start = time.perf_counter()
            page = kb.query_terms(query)
            elapsed = (time.perf_counter() - start) * 1000
            results.append((view, elapsed, page.total))

    print(f"terms={term_count}  links={link_count}  (单页 limit=20)")
    all_ok = True
    for view, elapsed, total in results:
        ok = elapsed < RED_LINE_MS
        all_ok = all_ok and ok
        print(
            f"  {view:18s} total={total:5d}  {elapsed:7.1f} ms  "
            f"[{'OK' if ok else 'OVER RED LINE'}]"
        )
    print("PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    term_count = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    link_count = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    run_bench(term_count, link_count)
