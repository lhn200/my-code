"""Long-term memory management endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, StrictBool

from ..auth.dependencies import get_current_user
from ..db import User, connect
from ..errors import ApiError, field_error
from ..memory.content import MemoryContentError, SensitiveContentError
from ..memory.repository import (
    MemoryConflict,
    MemoryNotFound,
    clear_memories,
    delete_memory,
    get_settings,
    list_memories,
    maybe_archive_expired,
    set_enabled,
    update_memory,
)

router = APIRouter(tags=["memories"])

Kind = Literal["preference", "goal", "fact", "constraint"]
Status = Literal["active", "pending_confirmation", "archived"]


class MemoryUpdate(BaseModel):
    content: str | None = None
    kind: Kind | None = None
    status: Literal["active", "archived"] | None = None


class MemorySettingsUpdate(BaseModel):
    enabled: StrictBool


def _item(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "content": row["content"],
        "confidence": float(row["confidence"]),
        "status": row["status"],
        "source_thread_id": row["source_thread_id"],
        "source_type": row["source_type"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
        "archived_reason": row["archived_reason"],
    }


def _not_found(memory_id: str) -> ApiError:
    return ApiError(404, "memory_not_found", f"memory {memory_id} was not found")


@router.get("/memories/settings")
def read_memory_settings(
    request: Request, user: User = Depends(get_current_user)
) -> dict[str, Any]:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        return get_settings(
            connection, user.id, default_enabled=settings.memory_enabled_default
        )


@router.put("/memories/settings")
def write_memory_settings(
    payload: MemorySettingsUpdate,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        return set_enabled(connection, user.id, payload.enabled)


@router.get("/memories")
def list_user_memories(
    request: Request,
    kind: Kind | None = Query(default=None),
    status: Status | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    maybe_archive_expired(settings.checkpoint_db_path)
    with connect(settings.checkpoint_db_path) as connection:
        rows = list_memories(
            connection,
            user.id,
            kind=kind,
            status=status,
            q=(q or "").strip() or None,
            limit=limit,
        )
    return {"items": [_item(row) for row in rows], "total": len(rows)}


@router.delete("/memories")
def clear_user_memories(
    request: Request, user: User = Depends(get_current_user)
) -> dict[str, Any]:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        deleted = clear_memories(connection, user_id=user.id)
    return {"deleted": deleted}


@router.patch("/memories/{memory_id}")
def edit_memory(
    memory_id: str,
    payload: MemoryUpdate,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if payload.content is None and payload.kind is None and payload.status is None:
        raise ApiError(
            422,
            "validation_error",
            "request validation failed",
            fields=[
                field_error(
                    "content", "missing", "at least one of content, kind or status is required"
                )
            ],
        )
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        try:
            row = update_memory(
                connection,
                user_id=user.id,
                memory_id=memory_id,
                settings=settings,
                content=payload.content,
                kind=payload.kind,
                status=payload.status,
            )
        except MemoryNotFound:
            raise _not_found(memory_id) from None
        except SensitiveContentError:
            raise ApiError(
                422,
                "sensitive_content",
                "content contains a category that must not be stored",
                fields=[field_error("content", "sensitive_content", "contains sensitive data")],
            ) from None
        except MemoryContentError as exc:
            raise ApiError(
                422,
                "invalid_content",
                "request validation failed",
                fields=[field_error("content", "invalid", str(exc))],
            ) from None
        except MemoryConflict:
            raise ApiError(409, "memory_conflict", "another memory already has this content") from None
    return _item(row)


@router.delete("/memories/{memory_id}", status_code=204)
def remove_memory(
    memory_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> Response:
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        try:
            delete_memory(connection, user_id=user.id, memory_id=memory_id)
        except MemoryNotFound:
            raise _not_found(memory_id) from None
    return Response(status_code=204)


__all__ = ["router"]
