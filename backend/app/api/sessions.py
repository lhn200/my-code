"""Session directory endpoints: list, rename, trash, restore and purge."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from ..auth.dependencies import get_current_user
from ..db import User, connect
from ..db.runs import (
    list_runs,
    purge_thread,
    rename_run,
    restore_run,
    soft_delete_run,
)
from ..errors import ApiError, field_error, internal_error, not_trashed
from ..memory.repository import detach_source_thread
from .ownership import get_owned_run

router = APIRouter(tags=["sessions"])


class TitleUpdate(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PydanticCustomError("blank", "title must not be blank")
        return value.strip()


def _item(row: Any) -> dict[str, Any]:
    return {
        "thread_id": row["thread_id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
    }


@router.get("/sessions")
def list_sessions(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None),
    trashed: bool = Query(default=False),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    query = (q or "").strip() or None
    with connect(settings.checkpoint_db_path) as connection:
        rows, total = list_runs(
            connection, user.id, page, page_size, q=query, trashed=trashed
        )
    return {
        "items": [_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/sessions/{thread_id}")
def rename_session(
    thread_id: str,
    payload: TitleUpdate,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    if len(payload.title) > settings.max_session_title_chars:
        raise ApiError(
            422,
            "validation_error",
            "request validation failed",
            fields=[
                field_error(
                    "title",
                    "too_long",
                    f"title must be at most {settings.max_session_title_chars} characters",
                )
            ],
        )
    with connect(settings.checkpoint_db_path) as connection:
        get_owned_run(connection, thread_id, user.id)
        rename_run(connection, thread_id, user.id, payload.title)
        row = get_owned_run(connection, thread_id, user.id)
    return _item(row)


@router.delete("/sessions/{thread_id}", status_code=204)
def delete_session(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> Response:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        get_owned_run(connection, thread_id, user.id, include_trashed=True)
        soft_delete_run(connection, thread_id, user.id)
    return Response(status_code=204)


@router.post("/sessions/{thread_id}/restore")
def restore_session(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        row = get_owned_run(connection, thread_id, user.id, include_trashed=True)
        if row["deleted_at"] is None:
            raise not_trashed()
        restore_run(connection, thread_id, user.id)
        row = get_owned_run(connection, thread_id, user.id, include_trashed=True)
    return _item(row)


@router.delete("/sessions/{thread_id}/purge", status_code=204)
def purge_session(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> Response:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        row = get_owned_run(connection, thread_id, user.id, include_trashed=True)
        if row["deleted_at"] is None:
            raise not_trashed()
        detach_source_thread(connection, thread_id=thread_id)
    try:
        purge_thread(settings.checkpoint_db_path, thread_id)
    except Exception:
        raise internal_error(thread_id) from None
    return Response(status_code=204)


__all__ = ["router"]
