"""Rolling session summaries: read, write and manual regeneration."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..config import Settings
from ..db import connect
from ..state import ensure_memory_defaults
from .session_store import SessionSnapshot, SessionStateStore

logger = logging.getLogger(__name__)

SUMMARY_KEYS: tuple[str, ...] = (
    "facts",
    "open_questions",
    "preferences",
    "constraints",
    "decisions",
)

MAX_SESSION_TURNS = 18

STATUS_IDLE = "idle"
STATUS_OK = "ok"
STATUS_FAILED = "failed"


class SessionMemoryError(Exception):
    """Base class for session memory failures."""


class SessionNotFound(SessionMemoryError):
    """The thread does not exist or does not belong to the user."""


class SummaryConflict(SessionMemoryError):
    """The summary version or the underlying state changed concurrently."""


class SummaryFailed(SessionMemoryError):
    """The summarizer failed or returned an invalid structure."""


class Summarizer(Protocol):
    def summarize(
        self,
        existing: Mapping[str, Any] | None,
        turns: Sequence[Mapping[str, Any]],
    ) -> Any:
        """Return a structured summary for the given turns."""


@dataclass(frozen=True)
class ProjectionRow:
    summary_version: int
    summarized_through_turn: int
    summary_status: str
    updated_at: str


class SessionMemoryProjection:
    """Non-authoritative projection used by summary status endpoints."""

    def __init__(self, db_path) -> None:
        self._db_path = db_path

    def get(self, thread_id: str) -> ProjectionRow | None:
        with connect(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT summary_version, summarized_through_turn, summary_status, updated_at
                FROM session_memory_meta
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return ProjectionRow(
            summary_version=int(row["summary_version"]),
            summarized_through_turn=int(row["summarized_through_turn"]),
            summary_status=str(row["summary_status"]),
            updated_at=str(row["updated_at"]),
        )

    def upsert(
        self,
        thread_id: str,
        user_id: str,
        summary_version: int,
        summarized_through_turn: int,
        summary_status: str,
        updated_at: str,
    ) -> None:
        with connect(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO session_memory_meta (
                    thread_id, user_id, summarized, summary_version,
                    summarized_through_turn, summary_status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    summarized = excluded.summarized,
                    summary_version = excluded.summary_version,
                    summarized_through_turn = excluded.summarized_through_turn,
                    summary_status = excluded.summary_status,
                    updated_at = excluded.updated_at
                """,
                (
                    thread_id,
                    user_id,
                    1 if summary_version > 0 else 0,
                    summary_version,
                    summarized_through_turn,
                    summary_status,
                    updated_at,
                ),
            )
            connection.commit()


@dataclass(frozen=True)
class SummaryView:
    thread_id: str
    summarized: bool
    version: int
    updated_at: str | None
    summarized_through_turn: int
    summary_status: str
    summary: dict[str, list[str]] | None


@dataclass(frozen=True)
class SummaryOutcome:
    view: SummaryView
    regenerated: bool


class SessionMemoryService:
    """Read, roll and regenerate a session summary.

    The store owns state revision checks; this service only mutates the summary
    fields and never writes round content back into the state.
    """

    def __init__(
        self,
        store: SessionStateStore,
        summarizer: Summarizer,
        settings: Settings,
        projection: SessionMemoryProjection | None = None,
        retry_delays: tuple[float, ...] = (1.0, 3.0),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._summarizer = summarizer
        self._settings = settings
        self._projection = projection
        self._retry_delays = retry_delays
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def get_summary(self, thread_id: str, user_id: str) -> SummaryView:
        snapshot = self._load(thread_id, user_id)
        view, needs_repair = self._build_view(snapshot)
        if needs_repair:
            self._upsert_projection(thread_id, user_id, view)
        return view

    def regenerate(
        self,
        thread_id: str,
        user_id: str,
        expected_version: int | None = None,
    ) -> SummaryOutcome:
        with self._thread_lock(thread_id):
            snapshot = self._load(thread_id, user_id)
            state = snapshot.state
            current_version = _summary_version(state)
            if expected_version is not None and expected_version != current_version:
                raise SummaryConflict(
                    f"summary version changed: expected {expected_version}, got {current_version}"
                )

            pending = _pending_turns(state)
            if not pending:
                view, needs_repair = self._build_view(snapshot)
                if needs_repair:
                    self._upsert_projection(thread_id, user_id, view)
                return SummaryOutcome(view=view, regenerated=False)

            window = pending[:6]
            return self._summarize_locked(snapshot, window)

    def summarize_if_due(self, thread_id: str, user_id: str) -> SummaryOutcome:
        with self._thread_lock(thread_id):
            snapshot = self._load(thread_id, user_id)
            pending = _pending_turns(snapshot.state)
            if len(pending) < self._settings.summary_trigger_turns:
                view, needs_repair = self._build_view(snapshot)
                if needs_repair:
                    self._upsert_projection(thread_id, user_id, view)
                return SummaryOutcome(view=view, regenerated=False)

            window = pending[:6]
            return self._summarize_locked(snapshot, window)

    def _summarize_locked(
        self,
        snapshot: SessionSnapshot,
        window: Sequence[Mapping[str, Any]],
    ) -> SummaryOutcome:
        state = snapshot.state
        current_version = _summary_version(state)
        existing = state.get("session_summary")
        existing_body = existing if isinstance(existing, Mapping) else None
        turn_numbers = [int(turn["turn"]) for turn in window]
        updated_at = self._now_iso()

        try:
            body = self._generate(existing_body, window)
            body = _trim_to_char_limit(body, self._settings.summary_max_chars)
        except SummaryFailed:
            self._mark_failed(snapshot, current_version, updated_at)
            raise
        except Exception as exc:  # defensive: summarizer or validation failure
            logger.warning(
                "session summary failed: thread=%s error=%s",
                snapshot.thread_id,
                type(exc).__name__,
            )
            self._mark_failed(snapshot, current_version, updated_at)
            raise SummaryFailed(str(exc)) from exc

        new_state = dict(state)
        new_state["session_summary"] = body
        new_state["session_summary_version"] = current_version + 1
        new_state["session_summary_updated_at"] = updated_at
        new_state["summarized_through_turn"] = max(turn_numbers)

        revision = self._store.save(
            snapshot.thread_id,
            snapshot.user_id,
            new_state,
            snapshot.revision,
        )
        if revision is None:
            raise SummaryConflict("session state changed while summarizing")

        view = SummaryView(
            thread_id=snapshot.thread_id,
            summarized=True,
            version=current_version + 1,
            updated_at=updated_at,
            summarized_through_turn=max(turn_numbers),
            summary_status=STATUS_OK,
            summary=body,
        )
        self._upsert_projection(snapshot.thread_id, snapshot.user_id, view)
        logger.info(
            "session summary updated: thread=%s version=%s turns=%s",
            snapshot.thread_id,
            view.version,
            len(window),
        )
        return SummaryOutcome(view=view, regenerated=True)

    def _generate(
        self,
        existing: Mapping[str, Any] | None,
        turns: Sequence[Mapping[str, Any]],
    ) -> dict[str, list[str]]:
        attempts = 1 + len(self._retry_delays)
        last_error: Exception | None = None
        for attempt in range(attempts):
            if attempt:
                time.sleep(self._retry_delays[attempt - 1])
            try:
                raw = self._call_with_timeout(existing, turns)
                return _validate_summary(raw)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "summary attempt %s/%s failed: %s",
                    attempt + 1,
                    attempts,
                    type(exc).__name__,
                )
        raise SummaryFailed(str(last_error) if last_error else "summary generation failed")

    def _call_with_timeout(
        self,
        existing: Mapping[str, Any] | None,
        turns: Sequence[Mapping[str, Any]],
    ) -> Any:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-summary")
        try:
            future = executor.submit(self._summarizer.summarize, existing, list(turns))
            return future.result(timeout=self._settings.summary_timeout_seconds)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _build_view(self, snapshot: SessionSnapshot) -> tuple[SummaryView, bool]:
        state = snapshot.state
        version = _summary_version(state)
        through = _summarized_through(state)
        summary = state.get("session_summary")
        body = dict(summary) if isinstance(summary, Mapping) and summary else None
        updated_at = state.get("session_summary_updated_at")
        default_status = STATUS_OK if body else STATUS_IDLE

        status = default_status
        needs_repair = body is not None
        if self._projection is not None:
            try:
                row = self._projection.get(snapshot.thread_id)
            except sqlite3.Error:
                row = None
            if row is not None:
                if row.summary_version == version and row.summarized_through_turn == through:
                    status = row.summary_status
                    needs_repair = False
                else:
                    needs_repair = True

        view = SummaryView(
            thread_id=snapshot.thread_id,
            summarized=body is not None,
            version=version,
            updated_at=str(updated_at) if updated_at else None,
            summarized_through_turn=through,
            summary_status=status,
            summary=body,
        )
        return view, needs_repair

    def _mark_failed(
        self,
        snapshot: SessionSnapshot,
        version: int,
        updated_at: str,
    ) -> None:
        if self._projection is None:
            return
        try:
            self._projection.upsert(
                snapshot.thread_id,
                snapshot.user_id,
                version,
                _summarized_through(snapshot.state),
                STATUS_FAILED,
                updated_at,
            )
        except sqlite3.Error as exc:
            logger.warning("summary projection update failed: %s", type(exc).__name__)

    def _upsert_projection(self, thread_id: str, user_id: str, view: SummaryView) -> None:
        if self._projection is None:
            return
        try:
            self._projection.upsert(
                thread_id,
                user_id,
                view.version,
                view.summarized_through_turn,
                view.summary_status,
                view.updated_at or self._now_iso(),
            )
        except sqlite3.Error as exc:
            logger.warning("summary projection update failed: %s", type(exc).__name__)

    def _load(self, thread_id: str, user_id: str) -> SessionSnapshot:
        snapshot = self._store.load(thread_id, user_id)
        if snapshot is None:
            raise SessionNotFound(thread_id)
        return snapshot

    def _thread_lock(self, thread_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(thread_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[thread_id] = lock
            return lock

    def _now_iso(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat()


def append_turn(
    state: Mapping[str, Any],
    *,
    user: str,
    assistant: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Append one complete turn (user input + assistant output).

    Turns are numbered monotonically and capped at ``MAX_SESSION_TURNS`` so the
    checkpoint never grows without bound. The input state is never mutated.
    """
    base = ensure_memory_defaults(state)
    turns = [
        dict(turn)
        for turn in base.get("session_turns") or []
        if isinstance(turn, Mapping)
    ]
    user_text = (user or "").strip()
    assistant_text = (assistant or "").strip()
    if not user_text and not assistant_text:
        return base
    last = max((_turn_number(turn) for turn in turns), default=0)
    entry: dict[str, Any] = {
        "turn": last + 1,
        "user": user_text,
        "assistant": assistant_text,
    }
    if created_at:
        entry["created_at"] = created_at
    turns.append(entry)
    if len(turns) > MAX_SESSION_TURNS:
        turns = turns[-MAX_SESSION_TURNS:]
    return {**base, "session_turns": turns}


def pending_turn_count(state: Mapping[str, Any]) -> int:
    """Count turns that have not been folded into the summary yet."""
    return len(_pending_turns(state))


def _turn_number(turn: Mapping[str, Any]) -> int:
    try:
        return int(turn.get("turn", 0))
    except (TypeError, ValueError):
        return 0


def _summary_version(state: Mapping[str, Any]) -> int:
    value = state.get("session_summary_version")
    return int(value) if isinstance(value, int) else 0


def _summarized_through(state: Mapping[str, Any]) -> int:
    value = state.get("summarized_through_turn")
    return int(value) if isinstance(value, int) else 0


def _pending_turns(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    through = _summarized_through(state)
    turns = state.get("session_turns") or []
    pending: list[dict[str, Any]] = []
    for turn in turns:
        if not isinstance(turn, Mapping):
            continue
        number = turn.get("turn")
        if not isinstance(number, int) or number <= through:
            continue
        pending.append(dict(turn))
    pending.sort(key=lambda item: int(item["turn"]))
    return pending


def _validate_summary(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, Mapping):
        raise SummaryFailed("summary must be an object")
    unknown = set(raw) - set(SUMMARY_KEYS)
    if unknown:
        raise SummaryFailed(f"unexpected summary keys: {sorted(unknown)}")
    missing = set(SUMMARY_KEYS) - set(raw)
    if missing:
        raise SummaryFailed(f"missing summary keys: {sorted(missing)}")

    body: dict[str, list[str]] = {}
    for key in SUMMARY_KEYS:
        value = raw[key]
        if not isinstance(value, list):
            raise SummaryFailed(f"summary field {key} must be a list")
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise SummaryFailed(f"summary field {key} must contain strings")
            text = item.strip()
            if text and text not in items:
                items.append(text)
        body[key] = items
    return body


def _trim_to_char_limit(body: dict[str, list[str]], limit: int) -> dict[str, list[str]]:
    trimmed = {key: list(values) for key, values in body.items()}
    total = sum(len(item) for values in trimmed.values() for item in values)
    if total <= limit:
        return trimmed

    for key in ("decisions", "open_questions", "preferences", "constraints", "facts"):
        while trimmed[key] and total > limit:
            removed = trimmed[key].pop()
            total -= len(removed)
        if total <= limit:
            return trimmed

    while total > limit:
        longest: tuple[int, str, int] | None = None
        for key, values in trimmed.items():
            for index, item in enumerate(values):
                if longest is None or len(item) > longest[0]:
                    longest = (len(item), key, index)
        if longest is None:
            break
        length, key, index = longest
        cut = min(total - limit, length)
        trimmed[key][index] = trimmed[key][index][: length - cut]
        total -= cut
        if not trimmed[key][index]:
            trimmed[key].pop(index)
    return trimmed
