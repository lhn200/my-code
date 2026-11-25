"""AI coach chat sessions persisted for multi-turn conversations."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from .utils import utc_now_iso

_SESSION_SELECT = (
    "SELECT s.id, s.user_id, s.thread_id, s.title, s.created_at, s.updated_at, "
    "(SELECT COUNT(*) FROM coach_messages m WHERE m.session_id = s.id) AS message_count "
    "FROM coach_sessions s"
)

_MESSAGE_SELECT = (
    "SELECT id, session_id, seq, role, content, created_at FROM coach_messages"
)

_MUTABLE_FIELDS = frozenset({"title", "thread_id", "updated_at"})


def new_session_id() -> str:
    return uuid.uuid4().hex


def create_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    user_id: str,
    thread_id: str | None,
    title: str,
) -> None:
    now = utc_now_iso()
    connection.execute(
        "INSERT INTO coach_sessions (id, user_id, thread_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, user_id, thread_id, title, now, now),
    )
    connection.commit()


def get_session(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return connection.execute(
        _SESSION_SELECT + " WHERE s.id = ?", (session_id,)
    ).fetchone()


def list_sessions(
    connection: sqlite3.Connection,
    user_id: str,
    thread_id: str | None = None,
) -> list[sqlite3.Row]:
    if thread_id is None:
        return connection.execute(
            _SESSION_SELECT + " WHERE s.user_id = ? ORDER BY s.updated_at DESC",
            (user_id,),
        ).fetchall()
    return connection.execute(
        _SESSION_SELECT
        + " WHERE s.user_id = ? AND s.thread_id = ? ORDER BY s.updated_at DESC",
        (user_id, thread_id),
    ).fetchall()


def update_session(
    connection: sqlite3.Connection, session_id: str, **fields: Any
) -> None:
    unknown = sorted(set(fields) - _MUTABLE_FIELDS)
    if unknown:
        raise ValueError(f"unknown session field(s): {', '.join(unknown)}")
    payload = dict(fields)
    payload.setdefault("updated_at", utc_now_iso())
    assignments = ", ".join(f"{name} = ?" for name in payload)
    connection.execute(
        f"UPDATE coach_sessions SET {assignments} WHERE id = ?",
        (*payload.values(), session_id),
    )


def delete_session(connection: sqlite3.Connection, session_id: str) -> None:
    connection.execute("DELETE FROM coach_messages WHERE session_id = ?", (session_id,))
    connection.execute("DELETE FROM coach_sessions WHERE id = ?", (session_id,))


def next_seq(connection: sqlite3.Connection, session_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(seq), 0) AS seq FROM coach_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["seq"]) + 1


def append_message(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
) -> int:
    seq = next_seq(connection, session_id)
    connection.execute(
        "INSERT INTO coach_messages (id, session_id, seq, role, content, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, session_id, seq, role, content, utc_now_iso()),
    )
    return seq


def list_messages(
    connection: sqlite3.Connection, session_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        _MESSAGE_SELECT + " WHERE session_id = ? ORDER BY seq ASC", (session_id,)
    ).fetchall()


def session_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "title": row["title"],
        "message_count": int(row["message_count"]) if "message_count" in keys else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def message_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


__all__ = [
    "append_message",
    "create_session",
    "delete_session",
    "get_session",
    "list_messages",
    "list_sessions",
    "message_to_dict",
    "new_session_id",
    "next_seq",
    "session_to_dict",
    "update_session",
]
