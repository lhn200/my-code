"""Practice interview endpoints: create, answer, finish and query sessions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..auth.dependencies import get_current_user
from ..db import User
from ..errors import ApiError
from ..services.interview_sessions import (
    InterviewSessionError,
    create_session as create_practice_session,
    finish_session,
    get_session_payload,
    list_session_payloads,
    submit_answer,
)
from .schemas import InterviewAnswerRequest, InterviewCreateRequest

router = APIRouter(tags=["interviews"])


def _translate(exc: InterviewSessionError) -> ApiError:
    return ApiError(exc.status_code, exc.code, exc.message)


@router.post("/interviews")
async def create_interview(
    payload: InterviewCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return await create_practice_session(
            request.app.state.graph,
            request.app.state.context,
            settings.checkpoint_db_path,
            user.id,
            payload.thread_id,
            payload.job_id,
        )
    except InterviewSessionError as exc:
        raise _translate(exc) from exc


@router.get("/interviews")
async def list_interviews(
    request: Request,
    thread_id: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        items = list_session_payloads(settings.checkpoint_db_path, user.id, thread_id)
    except InterviewSessionError as exc:
        raise _translate(exc) from exc
    return {"items": items}


@router.get("/interviews/{session_id}")
async def get_interview(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return get_session_payload(settings.checkpoint_db_path, user.id, session_id)
    except InterviewSessionError as exc:
        raise _translate(exc) from exc


@router.post("/interviews/{session_id}/answers")
async def submit_interview_answer(
    session_id: str,
    payload: InterviewAnswerRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return await submit_answer(
            request.app.state.graph,
            request.app.state.context,
            settings.checkpoint_db_path,
            user.id,
            session_id,
            payload.answer,
        )
    except InterviewSessionError as exc:
        raise _translate(exc) from exc


@router.post("/interviews/{session_id}/finish")
async def finish_interview(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return await finish_session(
            request.app.state.graph,
            request.app.state.context,
            settings.checkpoint_db_path,
            user.id,
            session_id,
        )
    except InterviewSessionError as exc:
        raise _translate(exc) from exc


__all__ = ["router"]
