import sqlite3
from pathlib import Path

import pytest

from app.db import SCHEMA_VERSION, connect, init_db

_NOW = "2026-01-01T00:00:00+00:00"


def _tables(db_path: Path) -> set[str]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger')"
        ).fetchall()
    return {row["name"] for row in rows}


def test_init_db_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite3"
    info = init_db(db_path)
    assert info.version == SCHEMA_VERSION
    names = _tables(db_path)
    assert {
        "user_memories",
        "user_memory_settings",
        "session_memory_meta",
        "ux_user_memories_hash",
        "ix_user_memories_list",
        "ix_user_memories_expiry",
        "ix_session_memory_meta_user",
    } <= names


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite3"
    first = init_db(db_path)
    second = init_db(db_path)
    assert first.version == second.version == SCHEMA_VERSION
    assert first.fts5_enabled == second.fts5_enabled


def test_memory_row_accepts_ttl_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite3"
    init_db(db_path)
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO user_memories (
                id, user_id, kind, content, content_hash,
                confidence, status, expires_at, archived_reason,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "m1",
                "u1",
                "fact",
                "目标岗位偏数据方向",
                "hash-1",
                0.9,
                "archived",
                "2026-06-01T00:00:00+00:00",
                "ttl",
                _NOW,
                _NOW,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT expires_at, archived_reason FROM user_memories").fetchone()
    assert row["expires_at"] == "2026-06-01T00:00:00+00:00"
    assert row["archived_reason"] == "ttl"


def test_duplicate_hash_rejected_only_for_live_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite3"
    init_db(db_path)
    insert = """
        INSERT INTO user_memories (
            id, user_id, kind, content, content_hash, created_at, updated_at
        ) VALUES (?, 'u1', 'fact', ?, 'same-hash', ?, ?)
    """
    with connect(db_path) as connection:
        connection.execute(insert, ("m1", "内容一", _NOW, _NOW))
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, ("m2", "内容二", _NOW, _NOW))
        connection.rollback()

        connection.execute(
            "UPDATE user_memories SET deleted_at = ? WHERE id = 'm1'",
            (_NOW,),
        )
        connection.execute(insert, ("m3", "内容三", _NOW, _NOW))
        connection.commit()


def test_fts5_status_is_boolean(tmp_path: Path) -> None:
    info = init_db(tmp_path / "checkpoints.sqlite3")
    assert isinstance(info.fts5_enabled, bool)
