"""Attach mock-interview report summaries to a main analysis run."""

from __future__ import annotations

from typing import Any, Mapping

from ..checkpoint.sqlite import thread_config
from ..graph.context import GraphContext
from ..graph.nodes import run_coach
from ..state import InterviewReportSummary


class InterviewReportError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


async def attach_interview_report(
    graph: Any,
    context: GraphContext,
    thread_id: str,
    job_id: str,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Write the latest interview summary for a job and refresh the coach advice."""
    config = thread_config(thread_id)
    snapshot = await graph.aget_state(config)
    values = dict(snapshot.values or {})
    if not values:
        raise InterviewReportError(404, "thread_not_found", f"run {thread_id} was not found")
    if job_id not in (values.get("job_profiles") or {}):
        raise InterviewReportError(
            422, "job_not_in_run", f"job {job_id} does not belong to run {thread_id}"
        )

    payload = dict(summary)
    payload["job_id"] = job_id
    report = InterviewReportSummary.model_validate(payload)

    existing = (values.get("interview_reports") or {}).get(job_id)
    if existing and existing.get("interview_thread_id") == report.interview_thread_id:
        return {
            "thread_id": thread_id,
            "job_id": job_id,
            "written": False,
            "idempotent": True,
            "retryable": False,
            "report": report.model_dump(),
            "advice": values.get("advice", ""),
        }

    previous_advice = values.get("advice", "")
    try:
        await graph.aupdate_state(
            config, {"interview_reports": {job_id: report.model_dump()}}
        )
    except Exception as exc:  # persistence failure: report stays with the caller
        return {
            "thread_id": thread_id,
            "job_id": job_id,
            "written": False,
            "idempotent": False,
            "retryable": True,
            "error": f"failed to persist interview report: {exc}",
            "report": report.model_dump(),
            "advice": previous_advice,
        }

    refreshed_snapshot = await graph.aget_state(config)
    refreshed = dict(refreshed_snapshot.values or {})
    try:
        coach_update = await run_coach(refreshed, context)
        advice = coach_update["advice"]
        await graph.aupdate_state(config, {"advice": advice})
    except Exception as exc:
        return {
            "thread_id": thread_id,
            "job_id": job_id,
            "written": True,
            "idempotent": False,
            "retryable": True,
            "error": f"advice refresh failed: {exc}",
            "report": report.model_dump(),
            "advice": previous_advice,
        }

    return {
        "thread_id": thread_id,
        "job_id": job_id,
        "written": True,
        "idempotent": False,
        "retryable": False,
        "report": report.model_dump(),
        "advice": advice,
    }


__all__ = ["InterviewReportError", "attach_interview_report"]
