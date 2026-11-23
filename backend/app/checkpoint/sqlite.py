"""SQLite checkpoint wiring for LangGraph runs."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

CHECKPOINT_TABLES = ("writes", "checkpoints")


def new_thread_id() -> str:
    """Server-side thread identity; clients never supply it."""
    return uuid.uuid4().hex


def thread_config(thread_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def delete_thread(connection: sqlite3.Connection, thread_id: str) -> None:
    """Delete all checkpoint rows for a thread; idempotent when absent."""
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    for table in CHECKPOINT_TABLES:
        if table in existing:
            connection.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))


def list_thread_ids(connection: sqlite3.Connection) -> list[str]:
    """Return every thread_id present in the checkpoint store."""
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "checkpoints" not in existing:
        return []
    rows = connection.execute(
        "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
    ).fetchall()
    return [row[0] for row in rows]


@asynccontextmanager
async def open_checkpointer(db_path: Path | str) -> AsyncIterator[AsyncSqliteSaver]:
    """Open the async SQLite saver with WAL and a busy timeout."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        await saver.conn.execute("PRAGMA journal_mode=WAL")
        await saver.conn.execute("PRAGMA busy_timeout=5000")
        await saver.conn.commit()
        yield saver


__all__ = [
    "CHECKPOINT_TABLES",
    "delete_thread",
    "list_thread_ids",
    "new_thread_id",
    "open_checkpointer",
    "thread_config",
]
