"""Session state access used by the session memory service.

The service never reads or writes the checkpointer directly. A store adapter keeps
optimistic concurrency and ownership checks in one place, so the production adapter
can later be backed by the LangGraph SQLite checkpointer while tests use an
in-memory implementation.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class SessionSnapshot:
    thread_id: str
    user_id: str
    state: dict[str, Any]
    revision: int


class SessionStateStore(Protocol):
    def load(self, thread_id: str, user_id: str) -> SessionSnapshot | None:
        """Return the snapshot only when the session belongs to the user."""

    def save(
        self,
        thread_id: str,
        user_id: str,
        state: Mapping[str, Any],
        expected_revision: int,
    ) -> int | None:
        """Persist state when the revision still matches; return the new revision."""


@dataclass
class _Row:
    user_id: str
    state: dict[str, Any]
    revision: int


class InMemorySessionStateStore:
    """Store double for unit tests and local development."""

    def __init__(self) -> None:
        self._rows: dict[str, _Row] = {}
        self._lock = threading.RLock()

    def seed(
        self,
        thread_id: str,
        user_id: str,
        state: Mapping[str, Any],
    ) -> int:
        with self._lock:
            self._rows[thread_id] = _Row(
                user_id=user_id,
                state=copy.deepcopy(dict(state)),
                revision=1,
            )
            return 1

    def load(self, thread_id: str, user_id: str) -> SessionSnapshot | None:
        with self._lock:
            row = self._rows.get(thread_id)
            if row is None or row.user_id != user_id:
                return None
            return SessionSnapshot(
                thread_id=thread_id,
                user_id=row.user_id,
                state=copy.deepcopy(row.state),
                revision=row.revision,
            )

    def save(
        self,
        thread_id: str,
        user_id: str,
        state: Mapping[str, Any],
        expected_revision: int,
    ) -> int | None:
        with self._lock:
            row = self._rows.get(thread_id)
            if row is None or row.user_id != user_id:
                return None
            if row.revision != expected_revision:
                return None
            row.state = copy.deepcopy(dict(state))
            row.revision += 1
            return row.revision
