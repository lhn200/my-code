"""Idempotent SQLite schema bootstrap and migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .connection import connect

SCHEMA_VERSION = 2

_CORE_DDL = """
CREATE TABLE IF NOT EXISTS user_memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('preference', 'goal', 'fact', 'constraint')),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_thread_id TEXT,
    source_type TEXT NOT NULL DEFAULT 'extracted',
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'pending_confirmation', 'archived')),
    expires_at TEXT,
    archived_reason TEXT
        CHECK (archived_reason IS NULL OR archived_reason IN ('user', 'ttl')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_user_memories_hash
    ON user_memories (user_id, kind, content_hash)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_user_memories_list
    ON user_memories (user_id, status, updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_user_memories_expiry
    ON user_memories (status, expires_at)
    WHERE expires_at IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS user_memory_settings (
    user_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_memory_meta (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    summarized INTEGER NOT NULL DEFAULT 0,
    summary_version INTEGER NOT NULL DEFAULT 0,
    summarized_through_turn INTEGER NOT NULL DEFAULT 0,
    summary_status TEXT NOT NULL DEFAULT 'idle',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_session_memory_meta_user
    ON session_memory_meta (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_lower
    ON users (lower(email));

CREATE TABLE IF NOT EXISTS runs (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id),
    title TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
"""

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS user_memories_fts
    USING fts5(memory_id UNINDEXED, content, tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS user_memories_ai
AFTER INSERT ON user_memories BEGIN
    INSERT INTO user_memories_fts (memory_id, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS user_memories_au
AFTER UPDATE OF content ON user_memories BEGIN
    DELETE FROM user_memories_fts WHERE memory_id = old.id;
    INSERT INTO user_memories_fts (memory_id, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS user_memories_ad
AFTER DELETE ON user_memories BEGIN
    DELETE FROM user_memories_fts WHERE memory_id = old.id;
END;
"""


@dataclass(frozen=True)
class SchemaInfo:
    version: int
    fts5_enabled: bool


def init_db(db_path: Path) -> SchemaInfo:
    """Create tables and indexes idempotently, falling back without FTS5."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(db_path) as connection:
        connection.executescript(_CORE_DDL)
        _ensure_runs_columns(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_runs_user_active "
            "ON runs (user_id, deleted_at, updated_at DESC)"
        )
        fts5_enabled = _try_create_fts(connection)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.commit()
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    return SchemaInfo(version=int(version), fts5_enabled=fts5_enabled)


def _ensure_runs_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
    if columns and "deleted_at" not in columns:
        connection.execute("ALTER TABLE runs ADD COLUMN deleted_at TEXT")


def _try_create_fts(connection: sqlite3.Connection) -> bool:
    try:
        connection.executescript(_FTS_DDL)
        return True
    except sqlite3.Error:
        connection.executescript(
            """
            DROP TRIGGER IF EXISTS user_memories_ai;
            DROP TRIGGER IF EXISTS user_memories_au;
            DROP TRIGGER IF EXISTS user_memories_ad;
            DROP TABLE IF EXISTS user_memories_fts;
            """
        )
        return False


__all__ = ["SCHEMA_VERSION", "SchemaInfo", "init_db"]
