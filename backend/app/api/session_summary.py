"""Session summary read and regeneration endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..auth.dependencies import get_current_user
from ..checkpoint.sqlite import thread_config
from ..db import User, connect
from ..errors import ApiError, thread_not_found
from ..memory.session_memory import (
    SummaryConflict,
    SummaryFailed,
    SummaryView,
    pending_turn_count,
)
from ..memory.session_runtime import (
    SUMMARY_STATE_KEYS,
    build_session_service,
    lock_for,
)
from .ownership import get_owned_run

router = APIRouter(tags=["sessions"])


class RegenerateRequest(BaseModel):
    expected_version: int | None = None


def _payload(view: SummaryView, *, regenerated: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "thread_id": view.thread_id,
        "summarized": view.summarized,
        "version": view.version,
        "updated_at": view.updated_at,
        "summarized_through_turn": view.summarized_through_turn,
        "summary_status": view.summary_status,
        "summary": view.summary,
    }
    if regenerated is not None:
        body["regenerated"] = regenerated
    return body


@router.get("/sessions/{thread_id}/summary")
async def read_session_summary(
    thread_id: str, request: Request, user: User = Depends(get_current_user)
) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    with connect(settings.checkpoint_db_path) as connection:
        get_owned_run(connection, thread_id, user.id)

    snapshot = await graph.aget_state(thread_config(thread_id))
    if not snapshot.values:
        raise thread_not_found(thread_id)

    state = dict(snapshot.values)
    service, _store = build_session_service(
        request.app.state.context,
        settings,
        thread_id=thread_id,
        user_id=user.id,
        state=state,
    )
    view = service.get_summary(thread_id, user.id)
    if pending_turn_count(state) >= settings.summary_trigger_turns:
        view = await _compensate(request, thread_id, user.id)
    return _payload(view)


async def _compensate(request: Request, thread_id: str, user_id: str) -> SummaryView:
    """Lazily roll the summary when a read finds enough pending turns."""
    settings = request.app.state.settings
    graph = request.app.state.graph
    async with lock_for(request.app, thread_id):
        snapshot = await graph.aget_state(thread_config(thread_id))
        state = dict(snapshot.values or {})
        service, store = build_session_service(
            request.app.state.context,
            settings,
            thread_id=thread_id,
            user_id=user_id,
            state=state,
        )
        try:
            outcome = await asyncio.to_thread(
                service.summarize_if_due, thread_id, user_id
            )
        except (SummaryConflict, SummaryFailed):
            return service.get_summary(thread_id, user_id)
        if outcome.regenerated:
            saved = store.load(thread_id, user_id)
            if saved is not None:
                await graph.aupdate_state(
                    thread_config(thread_id),
                    {key: saved.state.get(key) for key in SUMMARY_STATE_KEYS},
                )
        return outcome.view


@router.post("/sessions/{thread_id}/summary/regenerate")
async def regenerate_session_summary(
    thread_id: str,
    payload: RegenerateRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph

    async with lock_for(request.app, thread_id):
        with connect(settings.checkpoint_db_path) as connection:
            get_owned_run(connection, thread_id, user.id)
        snapshot = await graph.aget_state(thread_config(thread_id))
        if not snapshot.values:
            raise thread_not_found(thread_id)

        service, store = build_session_service(
            request.app.state.context,
            settings,
            thread_id=thread_id,
            user_id=user.id,
            state=dict(snapshot.values),
        )
        try:
            outcome = await asyncio.to_thread(
                service.regenerate, thread_id, user.id, payload.expected_version
            )
        except SummaryConflict:
            raise ApiError(
                409,
                "summary_conflict",
                "session summary changed; reload before regenerating",
            ) from None
        except SummaryFailed:
            raise ApiError(
                502,
                "summary_failed",
                "session summary generation failed",
            ) from None

        if outcome.regenerated:
            saved = store.load(thread_id, user.id)
            if saved is not None:
                await graph.aupdate_state(
                    thread_config(thread_id),
                    {key: saved.state.get(key) for key in SUMMARY_STATE_KEYS},
                )
        return _payload(outcome.view, regenerated=outcome.regenerated)


__all__ = ["router"]
