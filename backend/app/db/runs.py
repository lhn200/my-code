"""Session directory persisted in the `runs` table."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .connection import connect, transaction
from .utils import utc_now_iso

RUN_STATUSES = ("running", "completed", "partial", "failed")

_SELECT = (
    "SELECT thread_id, user_id, title, status, created_at, updated_at, deleted_at "
    "FROM runs"
)


def default_title(goal: str, limit: int = 100) -> str:
    title = " ".join(goal.split())
    return title[:limit] if title else "Untitled run"


def map_run_status(run_status: str) -> str:
    if run_status == "succeeded":
        return "completed"
    if run_status == "partial":
        return "partial"
    return "failed"


def create_run(
    connection: sqlite3.Connection,
    thread_id: str,
    user_id: str,
    title: str,
    status: str = "running",
) -> None:
    now = utc_now_iso()
    connection.execute(
        "INSERT INTO runs (thread_id, user_id, title, status, created_at, updated_at, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (thread_id, user_id, title, status, now, now),
    )
    connection.commit()


def get_run(
    connection: sqlite3.Connection,
    thread_id: str,
    user_id: str,
    include_trashed: bool = False,
) -> sqlite3.Row | None:
    query = _SELECT + " WHERE thread_id = ? AND user_id = ?"
    if not include_trashed:
        query += " AND deleted_at IS NULL"
    return connection.execute(query, (thread_id, user_id)).fetchone()


def list_runs(
    connection: sqlite3.Connection,
    user_id: str,
    page: int,
    page_size: int,
    q: str | None = None,
    trashed: bool = False,
) -> tuple[list[sqlite3.Row], int]:
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if trashed:
        clauses.append("deleted_at IS NOT NULL")
    else:
        clauses.append("deleted_at IS NULL")
    if q:
        clauses.append("lower(title) LIKE lower(?) ESCAPE '\\'")
        params.append(f"%{_escape_like(q)}%")
    where = " WHERE " + " AND ".join(clauses)
    total = connection.execute(
        f"SELECT COUNT(*) AS total FROM runs{where}", params
    ).fetchone()["total"]
    order = "deleted_at DESC" if trashed else "updated_at DESC"
    rows = connection.execute(
        f"{_SELECT}{where} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return rows, int(total)


def rename_run(
    connection: sqlite3.Connection, thread_id: str, user_id: str, title: str
) -> bool:
    cursor = connection.execute(
        "UPDATE runs SET title = ?, updated_at = ? "
        "WHERE thread_id = ? AND user_id = ? AND deleted_at IS NULL",
        (title, utc_now_iso(), thread_id, user_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def soft_delete_run(
    connection: sqlite3.Connection, thread_id: str, user_id: str
) -> bool:
    cursor = connection.execute(
        "UPDATE runs SET deleted_at = ? "
        "WHERE thread_id = ? AND user_id = ? AND deleted_at IS NULL",
        (utc_now_iso(), thread_id, user_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def restore_run(
    connection: sqlite3.Connection, thread_id: str, user_id: str
) -> bool:
    cursor = connection.execute(
        "UPDATE runs SET deleted_at = NULL, updated_at = ? "
        "WHERE thread_id = ? AND user_id = ? AND deleted_at IS NOT NULL",
        (utc_now_iso(), thread_id, user_id),
    )
    connection.commit()
    return cursor.rowcount > 0


def touch_run(
    connection: sqlite3.Connection, thread_id: str, status: str | None = None
) -> None:
    now = utc_now_iso()
    if status is None:
        connection.execute(
            "UPDATE runs SET updated_at = ? WHERE thread_id = ?", (now, thread_id)
        )
    else:
        connection.execute(
            "UPDATE runs SET updated_at = ?, status = ? WHERE thread_id = ?",
            (now, status, thread_id),
        )
    connection.commit()


def purge_thread(db_path: Path, thread_id: str) -> None:
    """Delete checkpoint rows and the session row in one SQLite transaction."""
    from ..checkpoint.sqlite import delete_thread

    with transaction(db_path) as connection:
        delete_thread(connection, thread_id)
        connection.execute("DELETE FROM runs WHERE thread_id = ?", (thread_id,))


def expired_trash(
    connection: sqlite3.Connection, cutoff: str
) -> list[str]:
    rows = connection.execute(
        "SELECT thread_id FROM runs WHERE deleted_at IS NOT NULL AND deleted_at < ?",
        (cutoff,),
    ).fetchall()
    return [row["thread_id"] for row in rows]


def delete_expired_trash(
    db_path: Path, cutoff: str, batch_size: int = 500
) -> int:
    """Physically delete trashed sessions older than cutoff; returns deleted count."""
    with connect(db_path) as connection:
        thread_ids = expired_trash(connection, cutoff)
    deleted = 0
    for index in range(0, len(thread_ids), batch_size):
        for thread_id in thread_ids[index : index + batch_size]:
            purge_thread(db_path, thread_id)
            deleted += 1
    return deleted


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "RUN_STATUSES",
    "create_run",
    "default_title",
    "delete_expired_trash",
    "expired_trash",
    "get_run",
    "list_runs",
    "map_run_status",
    "purge_thread",
    "rename_run",
    "restore_run",
    "soft_delete_run",
    "touch_run",
]
