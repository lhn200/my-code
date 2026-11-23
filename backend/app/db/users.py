"""User records and lookups."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from .utils import utc_now_iso


@dataclass(frozen=True)
class User:
    id: str
    email: str
    created_at: str


class EmailTakenError(Exception):
    """Raised when the normalized email already belongs to an account."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(
    connection: sqlite3.Connection, email: str, password_hash: str
) -> User:
    user = User(
        id=uuid.uuid4().hex,
        email=normalize_email(email),
        created_at=utc_now_iso(),
    )
    try:
        connection.execute(
            "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user.id, user.email, password_hash, user.created_at),
        )
    except sqlite3.IntegrityError as exc:
        raise EmailTakenError(user.email) from exc
    connection.commit()
    return user


def get_user_by_email(
    connection: sqlite3.Connection, email: str
) -> tuple[User, str] | None:
    row = connection.execute(
        "SELECT id, email, password_hash, created_at FROM users WHERE lower(email) = ?",
        (normalize_email(email),),
    ).fetchone()
    if row is None:
        return None
    return _to_user(row), row["password_hash"]


def get_user_by_id(connection: sqlite3.Connection, user_id: str) -> User | None:
    row = connection.execute(
        "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return _to_user(row) if row is not None else None


def _to_user(row: sqlite3.Row) -> User:
    return User(id=row["id"], email=row["email"], created_at=row["created_at"])


__all__ = [
    "EmailTakenError",
    "User",
    "create_user",
    "get_user_by_email",
    "get_user_by_id",
    "normalize_email",
]
