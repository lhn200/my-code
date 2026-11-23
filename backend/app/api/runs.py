"""Run creation, resumption, state and snapshot queries."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from ..checkpoint.sqlite import new_thread_id, thread_config
from ..errors import ApiError, internal_error, snapshot_not_found, thread_not_found
from ..graph.main import (
    RunInputError,
    build_initial_state,
    normalize_jobs,
    validate_run_input,
)
from ..services.results import build_run_result
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


@router.post("/runs")
async def create_run(payload: RunRequest, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    jobs = normalize_jobs([job.model_dump() for job in payload.jobs])
    state = build_initial_state(payload.goal, payload.resume_text, jobs)
    try:
        validate_run_input(state, settings)
    except RunInputError as exc:
        raise ApiError(422, exc.code, str(exc), exc.fields) from exc

    thread_id = new_thread_id()
    try:
        final = await graph.ainvoke(state, config=_run_config(thread_id))
    except RunInputError as exc:
        raise ApiError(422, exc.code, str(exc), exc.fields) from exc
    except Exception:
        logger.exception("run failed thread_id=%s", thread_id)
        raise internal_error(thread_id) from None

    return build_run_result(final, thread_id, settings).model_dump()


@router.post("/runs/{thread_id}/resume")
async def resume_run(thread_id: str, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    config = _run_config(thread_id)
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise thread_not_found(thread_id)
    try:
        final = await graph.ainvoke(None, config=config)
    except Exception:
        logger.exception("resume failed thread_id=%s", thread_id)
        raise internal_error(thread_id) from None
    return build_run_result(final, thread_id, settings).model_dump()


@router.get("/runs/{thread_id}")
async def get_run(thread_id: str, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_run_config(thread_id))
    if not snapshot.values:
        raise thread_not_found(thread_id)
    return _state_payload(snapshot, thread_id, settings)


@router.get("/runs/{thread_id}/snapshots")
async def list_snapshots(thread_id: str, request: Request) -> dict[str, Any]:
    graph = request.app.state.graph
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
async def get_snapshot(thread_id: str, checkpoint_id: str, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    graph = request.app.state.graph
    snapshot = await graph.aget_state(_run_config(thread_id, checkpoint_id))
    if not snapshot.values or (snapshot.metadata or {}).get("step", -1) < 0:
        raise snapshot_not_found(checkpoint_id)
    return _state_payload(snapshot, thread_id, settings)


__all__ = ["router"]
