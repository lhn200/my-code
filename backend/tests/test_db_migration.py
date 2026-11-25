from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import SCHEMA_VERSION, init_db


def test_init_db_is_idempotent_and_preserves_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "old.sqlite3"
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO user_memories "
            "(id, user_id, kind, content, content_hash, confidence, status, created_at, updated_at) "
            "VALUES ('m1', 'u1', 'fact', 'hello', 'h1', 0.9, 'active', '2020-01-01', '2020-01-01')"
        )
        connection.commit()

    info = init_db(db_path)
    assert info.version == SCHEMA_VERSION
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM user_memories").fetchone()[0]
    assert rows == 1


def test_init_db_adds_missing_deleted_at_column(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-runs.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE runs ("
            "thread_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, "
            "status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO runs VALUES ('t1', 'u1', 'legacy', 'completed', '2020-01-01', '2020-01-01')"
        )
        connection.commit()

    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
        }
        deleted_at = connection.execute(
            "SELECT deleted_at FROM runs WHERE thread_id = 't1'"
        ).fetchone()[0]
    assert "deleted_at" in columns
    assert deleted_at is None
