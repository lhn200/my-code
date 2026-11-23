"""Practice interview sessions persisted for the interactive drill."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable

from .utils import utc_now_iso

OPEN_STATUSES = ("active", "ready_to_finish")

_SESSION_SELECT = (
    "SELECT id, user_id, thread_id, job_id, job_title, goal, job_profile_json, "
    "resume_text, variant_version, status, planned_count, asked_count, "
    "current_question_no, followups_used, max_followups, report_json, "
    "created_at, updated_at, completed_at FROM interview_sessions"
)

_MESSAGE_SELECT = (
    "SELECT id, session_id, seq, role, kind, question_no, content, score, "
    "strengths_json, improvements_json, created_at FROM interview_messages"
)

_MUTABLE_FIELDS = frozenset(
    {
        "status",
        "asked_count",
        "current_question_no",
        "followups_used",
        "report_json",
        "completed_at",
        "updated_at",
    }
)


def new_session_id() -> str:
    return uuid.uuid4().hex


def _dump(value: Any, default: Any) -> str:
    return json.dumps(default if value is None else value, ensure_ascii=False)


def load_json(raw: Any, default: Any) -> Any:
    """Best-effort JSON decode for stored TEXT columns."""
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def create_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    user_id: str,
    thread_id: str,
    job_id: str,
    job_title: str,
    goal: str,
    job_profile: dict[str, Any],
    resume_text: str,
    variant_version: int,
    planned_count: int,
    max_followups: int,
) -> None:
    now = utc_now_iso()
    connection.execute(
        "INSERT INTO interview_sessions ("
        "id, user_id, thread_id, job_id, job_title, goal, job_profile_json, "
        "resume_text, variant_version, status, planned_count, asked_count, "
        "current_question_no, followups_used, max_followups, report_json, "
        "created_at, updated_at, completed_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 0, 0, 0, ?, NULL, ?, ?, NULL)",
        (
            session_id,
            user_id,
            thread_id,
            job_id,
            job_title,
            goal,
            _dump(job_profile, {}),
            resume_text,
            int(variant_version),
            int(planned_count),
            int(max_followups),
            now,
            now,
        ),
    )
    connection.commit()


def get_session(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return connection.execute(
        _SESSION_SELECT + " WHERE id = ?", (session_id,)
    ).fetchone()


def get_open_session(
    connection: sqlite3.Connection, user_id: str, thread_id: str, job_id: str
) -> sqlite3.Row | None:
    placeholders = ", ".join("?" for _ in OPEN_STATUSES)
    return connection.execute(
        _SESSION_SELECT
        + " WHERE user_id = ? AND thread_id = ? AND job_id = ?"
        + f" AND status IN ({placeholders})"
        + " ORDER BY updated_at DESC LIMIT 1",
        (user_id, thread_id, job_id, *OPEN_STATUSES),
    ).fetchone()


def list_sessions(
    connection: sqlite3.Connection, user_id: str, thread_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        _SESSION_SELECT + " WHERE user_id = ? AND thread_id = ? ORDER BY created_at ASC",
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
        f"UPDATE interview_sessions SET {assignments} WHERE id = ?",
        (*payload.values(), session_id),
    )


def next_seq(connection: sqlite3.Connection, session_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(seq), 0) AS seq FROM interview_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["seq"]) + 1


def append_message(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    kind: str,
    question_no: int,
    content: str,
    score: int | None = None,
    strengths: Iterable[str] | None = None,
    improvements: Iterable[str] | None = None,
) -> int:
    seq = next_seq(connection, session_id)
    connection.execute(
        "INSERT INTO interview_messages ("
        "id, session_id, seq, role, kind, question_no, content, score, "
        "strengths_json, improvements_json, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            session_id,
            seq,
            role,
            kind,
            int(question_no),
            content,
            None if score is None else int(score),
            _dump(list(strengths or []), []),
            _dump(list(improvements or []), []),
            utc_now_iso(),
        ),
    )
    return seq


def list_messages(
    connection: sqlite3.Connection, session_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        _MESSAGE_SELECT + " WHERE session_id = ? ORDER BY seq ASC", (session_id,)
    ).fetchall()


def session_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "job_id": row["job_id"],
        "job_title": row["job_title"],
        "status": row["status"],
        "planned_count": int(row["planned_count"]),
        "asked_count": int(row["asked_count"]),
        "current_question_no": int(row["current_question_no"]),
        "followups_used": int(row["followups_used"]),
        "max_followups": int(row["max_followups"]),
        "variant_version": int(row["variant_version"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def message_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "kind": row["kind"],
        "question_no": int(row["question_no"]),
        "content": row["content"],
        "score": row["score"],
        "strengths": load_json(row["strengths_json"], []),
        "improvements": load_json(row["improvements_json"], []),
        "created_at": row["created_at"],
    }


__all__ = [
    "OPEN_STATUSES",
    "append_message",
    "create_session",
    "get_open_session",
    "get_session",
    "list_messages",
    "list_sessions",
    "load_json",
    "message_to_dict",
    "new_session_id",
    "next_seq",
    "session_to_dict",
    "update_session",
]
