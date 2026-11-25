"""AI coach chat endpoints: sessions and messages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..auth.dependencies import get_current_user
from ..db import User
from ..errors import ApiError
from ..services.coach_chat import (
    CoachError,
    create_session,
    delete_session,
    get_session_payload,
    list_sessions,
    send_message,
    update_session,
)
from .schemas import (
    CoachMessageRequest,
    CoachSessionCreateRequest,
    CoachSessionUpdateRequest,
)

router = APIRouter(tags=["coach"])


def _translate(exc: CoachError) -> ApiError:
    return ApiError(exc.status_code, exc.code, exc.message)


@router.post("/coach/sessions")
async def create_coach_session(
    payload: CoachSessionCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return create_session(
            settings.checkpoint_db_path, user.id, payload.thread_id, payload.title
        )
    except CoachError as exc:
        raise _translate(exc) from exc


@router.get("/coach/sessions")
async def list_coach_sessions(
    request: Request,
    thread_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        items = list_sessions(settings.checkpoint_db_path, user.id, thread_id)
    except CoachError as exc:
        raise _translate(exc) from exc
    return {"items": items}


@router.get("/coach/sessions/{session_id}")
async def get_coach_session(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return get_session_payload(settings.checkpoint_db_path, user.id, session_id)
    except CoachError as exc:
        raise _translate(exc) from exc


@router.patch("/coach/sessions/{session_id}")
async def patch_coach_session(
    session_id: str,
    payload: CoachSessionUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    provided = payload.model_dump(exclude_unset=True)
    kwargs: dict[str, Any] = {}
    if "thread_id" in provided:
        kwargs["thread_id"] = provided["thread_id"]
    try:
        return update_session(
            settings.checkpoint_db_path,
            user.id,
            session_id,
            title=provided.get("title"),
            **kwargs,
        )
    except CoachError as exc:
        raise _translate(exc) from exc


@router.delete("/coach/sessions/{session_id}", status_code=204)
async def remove_coach_session(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    settings = request.app.state.settings
    try:
        delete_session(settings.checkpoint_db_path, user.id, session_id)
    except CoachError as exc:
        raise _translate(exc) from exc


@router.post("/coach/sessions/{session_id}/messages")
async def send_coach_message(
    session_id: str,
    payload: CoachMessageRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return await send_message(
            request.app.state.graph,
            request.app.state.context,
            settings.checkpoint_db_path,
            user.id,
            session_id,
            payload.content,
        )
    except CoachError as exc:
        raise _translate(exc) from exc


__all__ = ["router"]
