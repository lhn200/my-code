"""SQLite connection helpers shared by business tables and checkpoints."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def connect(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with WAL, foreign keys and row access by name."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Yield a connection wrapped in a transaction; roll back on error."""
    with connect(db_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()


__all__ = ["connect", "transaction"]
