"""Run creation, resumption, state and snapshot queries."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ..auth.dependencies import get_current_user
from ..checkpoint.sqlite import new_thread_id, thread_config
from ..db import User, connect
from ..db.runs import create_run as insert_run
from ..db.runs import default_title, map_run_status, touch_run
from ..errors import ApiError, internal_error, snapshot_not_found, thread_not_found
from ..graph.main import (
    RunInputError,
    build_initial_state,
    normalize_jobs,
    validate_run_input,
)
from ..memory.repository import is_enabled
from ..memory.retrieval import retrieve_memories
from ..memory.session_runtime import update_session_memory
from ..services.results import build_run_result
from .ownership import get_owned_run
from .schemas import RunRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])

_RECURSION_LIMIT = 200


def _run_config(thread_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
    config = thread_config(thread_id, checkpoint_id)
    config["recursion_limit"] = _RECURSION_LIMIT
    return config


def _state_payload(snapshot: Any, thread_id: str, settings: Any) -> dict[str, Any]:
    result = build_run_result(snapshot.values or {}, thread_id, settings)
    return {
        "thread_id": thread_id,
        "next": list(snapshot.next or []),
        "state": snapshot.values or {},
        "result": result.model_dump(),
    }


def _require_owned(settings: Any, thread_id: str, user_id: str) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        get_owned_run(connection, thread_id, user_id)


def _memory_query(state: dict[str, Any]) -> str:
    parts = [str(state.get("goal") or "").strip()]
    parts.extend(
        str(job.get("title") or "").strip()
        for job in state.get("jobs") or []
        if isinstance(job, dict)
    )
    return " ".join(part for part in parts if part)


def _attach_memories(
    connection: Any, state: dict[str, Any], *, user_id: str, settings: Any
) -> None:
    memories = retrieve_memories(
        connection,
        user_id=user_id,
        query=_memory_query(state),
        settings=settings,
    )
    enabled = is_enabled(
        connection, user_id, default_enabled=settings.memory_enabled_default
    )
    state["memory_context"] = memories
    state["memory_context_meta"] = {
        "enabled": enabled,
        "count": len(memories),
        "kinds": sorted({item["kind"] for item in memories}),
    }


def _set_status(settings: Any, thread_id: str, status: str) -> None:
    try:
        with connect(settings.checkpoint_db_path) as connection:
            touch_run(connection, thread_id, status)
    except Exception:
        logger.warning("failed to update run status thread_id=%s", thread_id)


def _schedule_memory(
    request: Request,
    background: BackgroundTasks,
    *,
    user_id: str,
    thread_id: str,
    state: dict[str, Any],
    run_status: str,
) -> None:
    pipeline = getattr(request.app.state, "memory_pipeline", None)
    if pipeline is None or run_status not in {"succeeded", "partial"}:
        return
    settings = request.app.state.settings
    with connect(settings.checkpoint_db_path) as connection:
        if not is_enabled(
            connection, user_id, default_enabled=settings.memory_enabled_default
        ):
            return
    background.add_task(
        pipeline.run, user_id=user_id, thread_id=thread_id, state=dict(state)
    )


def _schedule_session_memory(
    request: Request,
    background: BackgroundTasks,
    *,
    user_id: str,
    thread_id: str,
    state: dict[str, Any],
    run_status: str,
) -> None:
    if run_status not in {"succeeded", "partial"}:
        return
    background.add_task(
        update_session_memory,
        request.app,
        user_id=user_id,
        thread_id=thread_id,
        state=dict(state),
    )


@router.post("/runs")
async def create_run(
    payload: RunRequest,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    jobs = normalize_jobs([job.model_dump() for job in payload.jobs])
    state = build_initial_state(payload.goal, payload.resume_text, jobs)
    try:
        validate_run_input(state, settings)
    except RunInputError as exc:
        raise ApiError(422, exc.code, str(exc), exc.fields) from exc

    thread_id = new_thread_id()
    with connect(settings.checkpoint_db_path) as connection:
        insert_run(
            connection,
            thread_id,
            user.id,
            default_title(payload.goal, settings.max_session_title_chars),
        )
        _attach_memories(connection, state, user_id=user.id, settings=settings)
    try:
        final = await graph.ainvoke(state, config=_run_config(thread_id))
    except RunInputError as exc:
        _set_status(settings, thread_id, "failed")
        raise ApiError(422, exc.code, str(exc), exc.fields) from exc
    except Exception:
        _set_status(settings, thread_id, "failed")
        logger.exception("run failed thread_id=%s", thread_id)
        raise internal_error(thread_id) from None

    result = build_run_result(final, thread_id, settings)
    _set_status(settings, thread_id, map_run_status(result.run_status))
    _schedule_memory(
        request,
        background,
        user_id=user.id,
        thread_id=thread_id,
        state=final,
        run_status=result.run_status,
    )
    _schedule_session_memory(
        request,
        background,
        user_id=user.id,
        thread_id=thread_id,
        state=final,
        run_status=result.run_status,
    )
    return result.model_dump()


@router.post("/runs/{thread_id}/resume")
async def resume_run(
    thread_id: str,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    _require_owned(settings, thread_id, user.id)
    config = _run_config(thread_id)
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise thread_not_found(thread_id)
    try:
        final = await graph.ainvoke(None, config=config)
    except Exception:
        logger.exception("resume failed thread_id=%s", thread_id)
        raise internal_error(thread_id) from None
    result = build_run_result(final, thread_id, settings)
    _set_status(settings, thread_id, map_run_status(result.run_status))
    _schedule_memory(
        request,
        background,
        user_id=user.id,
        thread_id=thread_id,
        state=final,
        run_status=result.run_status,
    )
    _schedule_session_memory(
        request,
        background,
        user_id=user.id,
        thread_id=thread_id,
        state=final,
        run_status=result.run_status,
    )
    return result.model_dump()


@router.get("/runs/{thread_id}")
async def get_run(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    _require_owned(settings, thread_id, user.id)
    snapshot = await graph.aget_state(_run_config(thread_id))
    if not snapshot.values:
        raise thread_not_found(thread_id)
    return _state_payload(snapshot, thread_id, settings)


@router.get("/runs/{thread_id}/snapshots")
async def list_snapshots(
    thread_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    _require_owned(settings, thread_id, user.id)
    config = _run_config(thread_id)
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise thread_not_found(thread_id)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    async for state_snapshot in graph.aget_state_history(config):
        step = (state_snapshot.metadata or {}).get("step", -1)
        if step < 0 or not state_snapshot.values:
            continue
        checkpoint_id = (state_snapshot.config.get("configurable") or {}).get("checkpoint_id")
        if not checkpoint_id or checkpoint_id in seen:
            continue
        seen.add(checkpoint_id)
        items.append(
            {
                "checkpoint_id": checkpoint_id,
                "created_at": str(state_snapshot.created_at or ""),
                "step": step,
                "next": list(state_snapshot.next or []),
            }
        )
    items.sort(key=lambda item: (item["step"], item["created_at"]))
    return {"thread_id": thread_id, "snapshots": items}


@router.get("/runs/{thread_id}/snapshots/{checkpoint_id}")
async def get_snapshot(
    thread_id: str,
    checkpoint_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    _require_owned(settings, thread_id, user.id)
    snapshot = await graph.aget_state(_run_config(thread_id, checkpoint_id))
    if not snapshot.values or (snapshot.metadata or {}).get("step", -1) < 0:
        raise snapshot_not_found(checkpoint_id)
    return _state_payload(snapshot, thread_id, settings)


__all__ = ["router"]
