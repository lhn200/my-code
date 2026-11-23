"""SQLite repository for user-level long-term memories and memory settings."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.connection import connect

from .content import (
    KINDS,
    MemoryContentError,
    SensitiveContentError,
    content_hash,
    detect_sensitive,
    expires_at_for,
    normalize_content,
    status_for_confidence,
)

CONFLICT_DELTA = 0.1
_ARCHIVE_INTERVAL_SECONDS = 3600
_archive_lock = threading.Lock()
_last_archive_at: dict[str, float] = {}


class MemoryNotFound(LookupError):
    """The memory does not exist for this user."""


class MemoryConflict(RuntimeError):
    """The write violates the dedupe or ownership invariant."""


def _now(now: datetime | None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _iso(now: datetime | None) -> str:
    return _now(now).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_settings(
    connection: sqlite3.Connection, user_id: str, *, default_enabled: bool = False
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT enabled, updated_at FROM user_memory_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return {"enabled": default_enabled, "updated_at": None}
    return {"enabled": bool(row["enabled"]), "updated_at": row["updated_at"]}


def set_enabled(
    connection: sqlite3.Connection,
    user_id: str,
    enabled: bool,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = _iso(now)
    connection.execute(
        """
        INSERT INTO user_memory_settings (user_id, enabled, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET enabled = excluded.enabled,
            updated_at = excluded.updated_at
        """,
        (user_id, 1 if enabled else 0, moment),
    )
    connection.commit()
    return {"enabled": bool(enabled), "updated_at": moment}


def is_enabled(
    connection: sqlite3.Connection, user_id: str, *, default_enabled: bool = False
) -> bool:
    return bool(get_settings(connection, user_id, default_enabled=default_enabled)["enabled"])


def get_memory(
    connection: sqlite3.Connection,
    user_id: str,
    memory_id: str,
    *,
    include_deleted: bool = False,
) -> dict[str, Any] | None:
    clause = "id = ? AND user_id = ?"
    if not include_deleted:
        clause += " AND deleted_at IS NULL"
    row = connection.execute(
        f"SELECT * FROM user_memories WHERE {clause}", (memory_id, user_id)
    ).fetchone()
    return _row(row)


def list_memories(
    connection: sqlite3.Connection,
    user_id: str,
    *,
    kind: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    clauses = ["user_id = ?", "deleted_at IS NULL"]
    params: list[Any] = [user_id]
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status == "archived":
        clauses.append("status = 'archived'")
    elif status:
        clauses.append("status = ?")
        params.append(status)
        clauses.append("(expires_at IS NULL OR expires_at > ?)")
        params.append(_iso(now))
    else:
        clauses.append("status != 'archived'")
        clauses.append("(expires_at IS NULL OR expires_at > ?)")
        params.append(_iso(now))
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("content LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
    params.append(max(1, int(limit)))
    rows = connection.execute(
        f"""
        SELECT * FROM user_memories
        WHERE {' AND '.join(clauses)}
        ORDER BY updated_at DESC, id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _insert(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    kind: str,
    content: str,
    digest: str,
    confidence: float,
    status: str,
    source_type: str,
    source_thread_id: str | None,
    settings: Settings,
    now: datetime | None,
) -> str:
    memory_id = uuid.uuid4().hex
    moment = _iso(now)
    expires_at = expires_at_for(kind, _now(now), settings)
    connection.execute(
        """
        INSERT INTO user_memories (
            id, user_id, kind, content, content_hash, source_thread_id, source_type,
            confidence, status, created_at, updated_at, expires_at, archived_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            memory_id,
            user_id,
            kind,
            content,
            digest,
            source_thread_id,
            source_type,
            float(confidence),
            status,
            moment,
            moment,
            expires_at,
        ),
    )
    return memory_id


def _find_by_hash(
    connection: sqlite3.Connection, user_id: str, kind: str, digest: str
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM user_memories
        WHERE user_id = ? AND kind = ? AND content_hash = ? AND deleted_at IS NULL
        """,
        (user_id, kind, digest),
    ).fetchone()
    return _row(row)


def upsert_memory(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    kind: str,
    content: str,
    confidence: float,
    source_type: str = "run",
    source_thread_id: str | None = None,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dedupe-aware write: identical content updates the existing row instead of adding."""
    if kind not in KINDS:
        raise MemoryContentError(f"unknown memory kind: {kind}")
    normalized = normalize_content(content, settings.memory_max_content_chars)
    category = detect_sensitive(normalized)
    if category is not None:
        raise SensitiveContentError(category)
    confidence = float(confidence)
    status = status_for_confidence(confidence, settings)
    if status is None:
        return {"id": None, "action": "discarded", "reason": "low_confidence"}

    digest = content_hash(user_id, kind, normalized)
    existing = _find_by_hash(connection, user_id, kind, digest)
    moment = _iso(now)
    if existing is not None:
        if existing["status"] == "archived":
            return {"id": existing["id"], "action": "skipped", "reason": "archived"}
        merged = max(float(existing["confidence"]), confidence)
        next_status = existing["status"]
        if next_status == "pending_confirmation" and merged >= settings.memory_min_confidence:
            next_status = "active"
        connection.execute(
            """
            UPDATE user_memories
            SET updated_at = ?, confidence = ?, status = ?, expires_at = ?
            WHERE id = ?
            """,
            (
                moment,
                merged,
                next_status,
                expires_at_for(kind, _now(now), settings),
                existing["id"],
            ),
        )
        connection.commit()
        return {"id": existing["id"], "action": "updated", "status": next_status}

    memory_id = _insert(
        connection,
        user_id=user_id,
        kind=kind,
        content=normalized,
        digest=digest,
        confidence=confidence,
        status=status,
        source_type=source_type,
        source_thread_id=source_thread_id,
        settings=settings,
        now=now,
    )
    connection.commit()
    return {"id": memory_id, "action": "created", "status": status}


def apply_operation(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    candidate: dict[str, Any],
    settings: Settings,
    source_type: str = "run",
    source_thread_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply an extracted candidate: add / update(target_id) / skip."""
    operation = str(candidate.get("op") or "skip").lower()
    if operation == "skip":
        return {"id": None, "action": "skipped", "reason": "model_skip"}
    if operation not in {"add", "update"}:
        return {"id": None, "action": "skipped", "reason": "unknown_op"}

    kind = str(candidate.get("kind") or "")
    confidence = float(candidate.get("confidence") or 0)
    content = str(candidate.get("content") or "")

    if operation == "update":
        target_id = str(candidate.get("target_id") or "")
        target = get_memory(connection, user_id, target_id) if target_id else None
        if target is None:
            return {"id": None, "action": "skipped", "reason": "missing_target"}
        if target["status"] == "archived":
            return {"id": target_id, "action": "skipped", "reason": "archived"}

        normalized = normalize_content(content, settings.memory_max_content_chars)
        category = detect_sensitive(normalized)
        if category is not None:
            raise SensitiveContentError(category)
        if confidence < float(target["confidence"]) + CONFLICT_DELTA:
            return {"id": target_id, "action": "skipped", "reason": "conflict"}

        digest = content_hash(user_id, target["kind"], normalized)
        next_status = target["status"]
        if next_status == "pending_confirmation" and confidence >= settings.memory_min_confidence:
            next_status = "active"
        try:
            connection.execute(
                """
                UPDATE user_memories
                SET content = ?, content_hash = ?, confidence = ?, status = ?,
                    updated_at = ?, expires_at = ?
                WHERE id = ?
                """,
                (
                    normalized,
                    digest,
                    confidence,
                    next_status,
                    _iso(now),
                    expires_at_for(target["kind"], _now(now), settings),
                    target_id,
                ),
            )
        except sqlite3.IntegrityError as exc:  # duplicate hash in another row
            connection.rollback()
            raise MemoryConflict(str(exc)) from exc
        connection.commit()
        return {"id": target_id, "action": "updated", "status": next_status}

    return upsert_memory(
        connection,
        user_id=user_id,
        kind=kind,
        content=content,
        confidence=confidence,
        source_type=source_type,
        source_thread_id=source_thread_id,
        settings=settings,
        now=now,
    )


def update_memory(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    memory_id: str,
    settings: Settings,
    content: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    row = get_memory(connection, user_id, memory_id)
    if row is None:
        raise MemoryNotFound(memory_id)
    if content is None and kind is None and status is None:
        raise MemoryContentError("at least one field must be provided")

    next_kind = kind or row["kind"]
    if next_kind not in KINDS:
        raise MemoryContentError(f"unknown memory kind: {next_kind}")
    next_content = row["content"]
    if content is not None:
        next_content = normalize_content(content, settings.memory_max_content_chars, strict=True)
        category = detect_sensitive(next_content)
        if category is not None:
            raise SensitiveContentError(category)

    next_status = row["status"]
    next_confidence = float(row["confidence"])
    archived_reason = row["archived_reason"]
    if status is not None:
        if status not in {"active", "archived"}:
            raise MemoryContentError("status must be active or archived")
        if status == "archived":
            next_status = "archived"
            archived_reason = "user"
        else:
            next_status = "active"
            archived_reason = None
            next_confidence = max(next_confidence, settings.memory_min_confidence)

    digest = content_hash(user_id, next_kind, next_content)
    try:
        connection.execute(
            """
            UPDATE user_memories
            SET kind = ?, content = ?, content_hash = ?, confidence = ?, status = ?,
                updated_at = ?, expires_at = ?, archived_reason = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                next_kind,
                next_content,
                digest,
                next_confidence,
                next_status,
                _iso(now),
                expires_at_for(next_kind, _now(now), settings),
                archived_reason,
                memory_id,
                user_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise MemoryConflict(str(exc)) from exc
    connection.commit()
    return get_memory(connection, user_id, memory_id) or {}


def delete_memory(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    memory_id: str,
    now: datetime | None = None,
) -> int:
    """Tombstone a memory; repeated deletes are idempotent, foreign rows are 404."""
    row = get_memory(connection, user_id, memory_id, include_deleted=True)
    if row is None:
        raise MemoryNotFound(memory_id)
    if row["deleted_at"]:
        return 0
    moment = _iso(now)
    connection.execute(
        """
        UPDATE user_memories
        SET content = '', content_hash = '', deleted_at = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (moment, moment, memory_id, user_id),
    )
    connection.commit()
    return 1


def clear_memories(
    connection: sqlite3.Connection, *, user_id: str, now: datetime | None = None
) -> int:
    moment = _iso(now)
    cursor = connection.execute(
        """
        UPDATE user_memories
        SET content = '', content_hash = '', deleted_at = ?, updated_at = ?
        WHERE user_id = ? AND deleted_at IS NULL
        """,
        (moment, moment, user_id),
    )
    connection.commit()
    return int(cursor.rowcount or 0)


def recent_by_kind(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    kind: str,
    limit: int = 5,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM user_memories
        WHERE user_id = ? AND kind = ? AND status = 'active' AND deleted_at IS NULL
          AND (expires_at IS NULL OR expires_at > ?)
        ORDER BY updated_at DESC, id ASC
        LIMIT ?
        """,
        (user_id, kind, _iso(now), max(0, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def detach_source_thread(
    connection: sqlite3.Connection, *, thread_id: str
) -> int:
    """Drop the provenance link when a session is purged; memories are kept."""
    cursor = connection.execute(
        "UPDATE user_memories SET source_thread_id = NULL WHERE source_thread_id = ?",
        (thread_id,),
    )
    connection.commit()
    return int(cursor.rowcount or 0)


def archive_expired(
    connection: sqlite3.Connection, *, now: datetime | None = None
) -> int:
    moment = _iso(now)
    cursor = connection.execute(
        """
        UPDATE user_memories
        SET status = 'archived', archived_reason = 'ttl', updated_at = ?
        WHERE status IN ('active', 'pending_confirmation')
          AND deleted_at IS NULL
          AND expires_at IS NOT NULL
          AND expires_at <= ?
        """,
        (moment, moment),
    )
    connection.commit()
    return int(cursor.rowcount or 0)


def archive_expired_memories(db_path: Path | str, *, now: datetime | None = None) -> int:
    with connect(db_path) as connection:
        return archive_expired(connection, now=now)


def maybe_archive_expired(
    db_path: Path | str,
    *,
    now: datetime | None = None,
    interval_seconds: float = _ARCHIVE_INTERVAL_SECONDS,
) -> int:
    """Lazily archive at most once per interval per process/database."""
    key = str(Path(db_path).resolve())
    current = time.monotonic()
    with _archive_lock:
        last = _last_archive_at.get(key)
        if last is not None and current - last < interval_seconds:
            return 0
        _last_archive_at[key] = current
    return archive_expired_memories(db_path, now=now)


def reset_archive_throttle() -> None:
    with _archive_lock:
        _last_archive_at.clear()


__all__ = [
    "CONFLICT_DELTA",
    "MemoryConflict",
    "MemoryNotFound",
    "apply_operation",
    "archive_expired",
    "archive_expired_memories",
    "clear_memories",
    "delete_memory",
    "detach_source_thread",
    "get_memory",
    "get_settings",
    "is_enabled",
    "list_memories",
    "maybe_archive_expired",
    "recent_by_kind",
    "reset_archive_throttle",
    "set_enabled",
    "update_memory",
    "upsert_memory",
]
