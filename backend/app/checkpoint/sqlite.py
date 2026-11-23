"""SQLite checkpoint wiring for LangGraph runs."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def new_thread_id() -> str:
    """Server-side thread identity; clients never supply it."""
    return uuid.uuid4().hex


def thread_config(thread_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


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


__all__ = ["new_thread_id", "open_checkpointer", "thread_config"]
