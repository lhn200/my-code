"""Run creation, resumption, state and snapshot queries."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response

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
from ..services.resume_pdf import render_resume_pdf, resume_pdf_filename
from ..state import RunResult
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


def _pending_payload(thread_id: str, run_status: str) -> dict[str, Any]:
    """占位 payload：尚无检查点时用于告知前端当前运行状态。"""
    result = RunResult(run_status=run_status, thread_id=thread_id)  # type: ignore[arg-type]
    return {
        "thread_id": thread_id,
        "next": [],
        "state": {},
        "result": result.model_dump(),
    }


async def _run_memory_jobs(
    app: Any, *, user_id: str, thread_id: str, state: dict[str, Any]
) -> None:
    """后台任务内直接等待记忆写入，避免再嵌套 BackgroundTasks。"""
    settings = app.state.settings
    pipeline = getattr(app.state, "memory_pipeline", None)
    if pipeline is not None:
        try:
            with connect(settings.checkpoint_db_path) as connection:
                enabled = is_enabled(
                    connection, user_id, default_enabled=settings.memory_enabled_default
                )
            if enabled:
                await pipeline.run(user_id=user_id, thread_id=thread_id, state=dict(state))
        except Exception:
            logger.warning("memory pipeline failed thread_id=%s", thread_id)
    try:
        await update_session_memory(
            app, user_id=user_id, thread_id=thread_id, state=dict(state)
        )
    except Exception:
        logger.warning("session memory failed thread_id=%s", thread_id)


async def _execute_run(
    app: Any, *, user_id: str, thread_id: str, state: dict[str, Any]
) -> None:
    """在后台执行完整分析，并同步 runs 表状态。"""
    settings = app.state.settings
    graph = app.state.graph
    try:
        final = await graph.ainvoke(state, config=_run_config(thread_id))
    except Exception:
        _set_status(settings, thread_id, "failed")
        logger.exception("run failed thread_id=%s", thread_id)
        return

    result = build_run_result(final, thread_id, settings)
    _set_status(settings, thread_id, map_run_status(result.run_status))
    if result.run_status in {"succeeded", "partial"}:
        await _run_memory_jobs(app, user_id=user_id, thread_id=thread_id, state=final)


@router.post("/runs")
async def create_run(
    payload: RunRequest,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
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

    # 分析耗时较长，立即返回 thread_id，由后台任务继续执行；
    # 前端结果页轮询 GET /runs/{thread_id} 获取最新进度。
    background.add_task(
        _execute_run,
        request.app,
        user_id=user.id,
        thread_id=thread_id,
        state=state,
    )
    return _pending_payload(thread_id, "running")["result"]


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
    with connect(settings.checkpoint_db_path) as connection:
        record = get_owned_run(connection, thread_id, user.id)
    snapshot = await graph.aget_state(_run_config(thread_id))
    status = str(record["status"])
    if not snapshot.values:
        # 运行刚开始（尚无检查点）或启动即失败时，用占位 payload 告知状态。
        return _pending_payload(thread_id, "failed" if status == "failed" else "running")
    payload = _state_payload(snapshot, thread_id, settings)
    if status == "running":
        # 后台仍在执行：中间检查点不代表最终结论，只暴露运行中状态。
        payload["result"]["run_status"] = "running"
        payload["result"]["jobs"] = []
    return payload


@router.get("/runs/{thread_id}/jobs/{job_id}/resume.pdf")
async def download_job_resume(
    thread_id: str,
    job_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> Response:
    """Render the job's current resume variant (or baseline) as a PDF."""
    settings = request.app.state.settings
    graph = request.app.state.graph
    _require_owned(settings, thread_id, user.id)
    snapshot = await graph.aget_state(_run_config(thread_id))
    state = snapshot.values or {}
    if not state:
        raise thread_not_found(thread_id)

    result = build_run_result(state, thread_id, settings)
    job = next((item for item in result.jobs if item.job_id == job_id), None)
    if job is None:
        raise ApiError(404, "job_not_found", f"job {job_id} was not found in this run")
    if job.status != "ok" or not job.resume_text.strip():
        raise ApiError(409, "resume_unavailable", "resume is not ready for this job")

    pdf = render_resume_pdf(
        title=job.title,
        company=job.profile.company if job.profile else "",
        text=job.resume_text,
        version=job.current_variant_version,
        score=job.review.score if job.review else None,
        source=job.resume_source,
    )
    filename = resume_pdf_filename(job.title, job.current_variant_version)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"resume.pdf\"; filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "private, max-age=0, must-revalidate",
        },
    )


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
