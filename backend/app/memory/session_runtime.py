"""Run-end session memory: append one turn and roll the summary when due."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import FastAPI

from ..checkpoint.sqlite import thread_config
from ..config import Settings
from ..state import ensure_memory_defaults
from .session_memory import (
    SessionMemoryProjection,
    SessionMemoryService,
    SummaryConflict,
    SummaryFailed,
    append_turn,
    pending_turn_count,
)
from .session_store import InMemorySessionStateStore
from .summarizer import ModelSummarizer

logger = logging.getLogger(__name__)

SUMMARY_STATE_KEYS: tuple[str, ...] = (
    "session_summary",
    "session_summary_version",
    "session_summary_updated_at",
    "summarized_through_turn",
)


def run_turn_input(state: Mapping[str, Any]) -> str:
    """Describe the user side of one run as a single turn input."""
    goal = str(state.get("goal") or "").strip()
    titles = [
        str(job.get("title") or "").strip()
        for job in state.get("jobs") or []
        if isinstance(job, Mapping)
    ]
    titles = [title for title in titles if title]
    parts: list[str] = []
    if goal:
        parts.append(f"目标：{goal}")
    if titles:
        parts.append("岗位：" + "、".join(titles))
    return "\n".join(parts)


def build_session_service(
    context: Any,
    settings: Settings,
    *,
    thread_id: str,
    user_id: str,
    state: Mapping[str, Any],
) -> tuple[SessionMemoryService, InMemorySessionStateStore]:
    store = InMemorySessionStateStore()
    store.seed(thread_id, user_id, state)
    service = SessionMemoryService(
        store,
        ModelSummarizer(context.model("summarizer"), context.prompts),
        settings,
        SessionMemoryProjection(settings.checkpoint_db_path),
    )
    return service, store


def lock_for(app: FastAPI, thread_id: str) -> asyncio.Lock:
    locks: dict[str, asyncio.Lock] = app.state.summary_locks
    lock = locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        locks[thread_id] = lock
    return lock


async def update_session_memory(
    app: FastAPI,
    *,
    user_id: str,
    thread_id: str,
    state: Mapping[str, Any],
) -> None:
    """Append the finished run as a turn, then summarize when turn count is due.

    Background execution must never break the request that scheduled it, so all
    failures are logged and swallowed.
    """
    settings: Settings = app.state.settings
    graph = app.state.graph
    try:
        snapshot = await graph.aget_state(thread_config(thread_id))
        current = ensure_memory_defaults(dict(snapshot.values or state))
        user_text = run_turn_input(current)
        assistant_text = str(current.get("advice") or "").strip()
        if not _already_recorded(current, user_text, assistant_text):
            updated = append_turn(
                current,
                user=user_text,
                assistant=assistant_text,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            if updated.get("session_turns") != current.get("session_turns"):
                await graph.aupdate_state(
                    thread_config(thread_id),
                    {"session_turns": updated["session_turns"]},
                )
                current = updated
        if pending_turn_count(current) < settings.summary_trigger_turns:
            return
        await roll_summary(app, user_id=user_id, thread_id=thread_id)
    except Exception:  # pragma: no cover - background isolation
        logger.warning(
            "session memory update failed thread_id=%s", thread_id, exc_info=True
        )


async def roll_summary(app: FastAPI, *, user_id: str, thread_id: str) -> bool:
    """Summarize inside the per-thread lock; return whether a new version landed."""
    settings: Settings = app.state.settings
    graph = app.state.graph
    async with lock_for(app, thread_id):
        snapshot = await graph.aget_state(thread_config(thread_id))
        if not snapshot.values:
            return False
        current = ensure_memory_defaults(dict(snapshot.values))
        if pending_turn_count(current) < settings.summary_trigger_turns:
            return False
        service, store = build_session_service(
            app.state.context,
            settings,
            thread_id=thread_id,
            user_id=user_id,
            state=current,
        )
        try:
            outcome = await asyncio.to_thread(
                service.summarize_if_due, thread_id, user_id
            )
        except (SummaryConflict, SummaryFailed):
            logger.warning("session summary skipped thread_id=%s", thread_id)
            return False
        if not outcome.regenerated:
            return False
        saved = store.load(thread_id, user_id)
        if saved is not None:
            await graph.aupdate_state(
                thread_config(thread_id),
                {key: saved.state.get(key) for key in SUMMARY_STATE_KEYS},
            )
        return True


def _already_recorded(
    state: Mapping[str, Any], user_text: str, assistant_text: str
) -> bool:
    turns = state.get("session_turns") or []
    if not turns:
        return False
    last = turns[-1]
    if not isinstance(last, Mapping):
        return False
    return (
        str(last.get("user") or "").strip() == user_text
        and str(last.get("assistant") or "").strip() == assistant_text
    )


__all__ = [
    "SUMMARY_STATE_KEYS",
    "build_session_service",
    "lock_for",
    "roll_summary",
    "run_turn_input",
    "update_session_memory",
]
