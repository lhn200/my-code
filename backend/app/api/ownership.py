"""Ownership lookup shared by run and session endpoints."""

from __future__ import annotations

import sqlite3

from ..db.runs import get_run
from ..errors import session_not_found


def get_owned_run(
    connection: sqlite3.Connection,
    thread_id: str,
    user_id: str,
    include_trashed: bool = False,
) -> sqlite3.Row:
    record = get_run(connection, thread_id, user_id, include_trashed=include_trashed)
    if record is None:
        raise session_not_found(thread_id)
    return record


__all__ = ["get_owned_run"]
