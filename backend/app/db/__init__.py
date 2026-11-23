"""SQLite data layer: connection, migrations, users and sessions."""

from __future__ import annotations

from .connection import connect, transaction
from .migrations import SCHEMA_VERSION, SchemaInfo, init_db
from .users import (
    EmailTakenError,
    User,
    create_user,
    get_user_by_email,
    get_user_by_id,
    normalize_email,
)

__all__ = [
    "EmailTakenError",
    "SCHEMA_VERSION",
    "SchemaInfo",
    "User",
    "connect",
    "create_user",
    "get_user_by_email",
    "get_user_by_id",
    "init_db",
    "normalize_email",
    "transaction",
]
