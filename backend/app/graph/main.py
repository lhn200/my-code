"""Main workflow graph: intake -> supervisor -> workers -> coach."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from ..errors import field_error
from ..state import AgentState, review_key
from .context import GraphContext
from .job_analysis import build_job_analysis_graph
from .nodes import (
    attempts_used,
    current_review,
    current_variant,
    current_variant_version,
    run_coach,
    run_optimize_resume,
    run_review_job,
)

logger = logging.getLogger(__name__)


class RunInputError(ValueError):
    def __init__(self, fields: list[dict[str, str]], message: str = "run input is invalid") -> None:
        super().__init__(message)
        self.fields = fields
        self.code = (
            "too_many_jobs"
            if fields and all(item["type"] == "too_many_jobs" for item in fields)
            else "validation_error"
        )


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def validate_run_input(state: Mapping[str, Any], settings: Any) -> None:
    """Entry validation; callers must run this before creating a checkpoint."""
    fields: list[dict[str, str]] = []
    if _blank(state.get("goal")):
        fields.append(field_error("goal", "blank", "goal must not be blank"))
    if _blank(state.get("resume_text")):
        fields.append(field_error("resume_text", "blank", "resume_text must not be blank"))

    jobs = state.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        fields.append(field_error("jobs", "missing", "at least one job is required"))
    elif len(jobs) > settings.max_jobs:
        fields.append(
            field_error(
                "jobs",
                "too_many_jobs",
                f"at most {settings.max_jobs} jobs are allowed per run",
            )
        )
    else:
        for index, job in enumerate(jobs):
            if not isinstance(job, Mapping):
                fields.append(field_error(f"jobs[{index}]", "object_type", "job must be an object"))
                continue
            if _blank(job.get("title")):
                fields.append(field_error(f"jobs[{index}].title", "blank", "title must not be blank"))
            if _blank(job.get("original_position_text")):
                fields.append(
                    field_error(
                        f"jobs[{index}].original_position_text",
                        "blank",
                        "original_position_text must not be blank",
                    )
                )
    if fields:
        raise RunInputError(fields)


def normalize_jobs(jobs: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every job has a stable, unique job_id."""
    normalized: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, job in enumerate(jobs):
        job_id = str(job.get("job_id") or "").strip() or f"job-{index + 1}"
        if job_id in used:
            job_id = f"{job_id}-{index + 1}"
        used.add(job_id)
        normalized.append(
            {
                "job_id": job_id,
                "title": str(job.get("title") or "").strip(),
                "original_position_text": str(job.get("original_position_text") or ""),
            }
        )
    return normalized


def clip_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[...内容已截断]"


def build_initial_state(
    goal: str,
    resume_text: str,
    jobs: list[Mapping[str, Any]],
    *,
    resume_file_id: str | None = None,
    resume_file_url: str | None = None,
) -> dict[str, Any]:
    return {
        "goal": goal,
        "resume_text": resume_text,
        "resume_file_id": resume_file_id,
        "resume_file_url": resume_file_url,
        "jobs": [dict(job) for job in jobs],
        "job_profiles": {},
        "reviews": {},
        "resume_variants": {},
        "optimization_history": [],
        "optimization_attempts": {},
        "interview_reports": {},
        "errors": [],
        "advice": "",
    }


def _review_payload(state: Mapping[str, Any], job: Mapping[str, Any]) -> dict[str, Any]:
    job_id = job["job_id"]
    variant = current_variant(state, job_id)
    version = int(variant.get("variant_version", 0)) if variant else 0
    resume_text = variant["text"] if variant else state.get("resume_text", "")
    round_entry = next(
        (
            item
            for item in state.get("optimization_history", [])
            if item.get("job_id") == job_id and int(item.get("variant_version", 0)) == version
        ),
        None,
    )
    return {
        "job_id": job_id,
        "goal": state.get("goal", ""),
        "profile": state.get("job_profiles", {}).get(job_id),
        "resume_text": resume_text,
        "variant_version": version,
        "round": round_entry.get("round") if round_entry else None,
        "score_before": round_entry.get("score_before") if round_entry else 0,
    }


def _optimize_payload(state: Mapping[str, Any], job: Mapping[str, Any]) -> dict[str, Any]:
    job_id = job["job_id"]
    review = current_review(state, job_id) or {}
    return {
        "job_id": job_id,
        "goal": state.get("goal", ""),
        "profile": state.get("job_profiles", {}).get(job_id),
        "review": review,
        "resume_text": state.get("resume_text", ""),
        "current_variant_version": current_variant_version(state, job_id),
        "round": attempts_used(state, job_id) + 1,
        "score_before": int(review.get("score", 0)),
    }


def build_main_graph(
    context: GraphContext,
    checkpointer: Any | None = None,
    interrupt_after: list[str] | None = None,
):
    settings = context.settings
    analysis_graph = build_job_analysis_graph(context)

    async def intake(state: Mapping[str, Any]) -> dict[str, Any]:
        validate_run_input(state, settings)
        jobs = normalize_jobs(state.get("jobs") or [])
        jobs = [
            {
                **job,
                "original_position_text": clip_text(
                    job["original_position_text"], settings.max_job_text_chars
                ),
            }
            for job in jobs
        ]
        logger.info(
            "run intake prompt_version=%s roles=%s",
            context.prompts.version,
            context.prompts.versions,
        )
        return {
            "goal": str(state.get("goal", "")).strip(),
            "resume_text": clip_text(str(state.get("resume_text", "")), settings.max_input_chars),
            "jobs": jobs,
            "threshold": settings.resume_match_threshold,
            "max_rounds": settings.max_optimization_rounds,
            "job_profiles": {},
            "reviews": {},
            "resume_variants": {},
            "optimization_history": [],
            "optimization_attempts": {},
            "interview_reports": {},
            "errors": [],
            "advice": "",
            "prompt_versions": context.prompts.versions,
        }

    async def analyze_job(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = await analysis_graph.ainvoke(
            {
                "job_id": payload["job_id"],
                "title": payload.get("title", ""),
                "job_text": payload.get("job_text", ""),
            }
        )
        update: dict[str, Any] = {
            "job_profiles": {payload["job_id"]: result["profile"]}
        }
        error = result.get("error")
        if error:
            update["errors"] = [error]
        return update

    async def review_job(payload: Mapping[str, Any]) -> dict[str, Any]:
        return await run_review_job(payload, context)

    async def optimize_resume(payload: Mapping[str, Any]) -> dict[str, Any]:
        return await run_optimize_resume(payload, context)

    async def coach(state: Mapping[str, Any]) -> dict[str, Any]:
        return await run_coach(state, context)

    def supervisor(state: Mapping[str, Any]) -> Command:
        if state.get("advice"):
            return Command(goto=END)

        jobs = sorted(state.get("jobs", []), key=lambda item: item["job_id"])
        profiles = state.get("job_profiles", {})
        reviews = state.get("reviews", {})

        analyze_sends = [
            Send(
                "analyze_job",
                {
                    "job_id": job["job_id"],
                    "title": job.get("title", ""),
                    "job_text": job.get("original_position_text", ""),
                },
            )
            for job in jobs
            if job["job_id"] not in profiles
        ]
        if analyze_sends:
            return Command(goto=analyze_sends)

        review_sends = [
            Send("review_job", _review_payload(state, job))
            for job in jobs
            if profiles.get(job["job_id"], {}).get("status") == "ok"
            and review_key(
                job["job_id"], current_variant_version(state, job["job_id"])
            )
            not in reviews
        ]
        if review_sends:
            return Command(goto=review_sends)

        threshold = int(state.get("threshold", settings.resume_match_threshold))
        max_rounds = int(state.get("max_rounds", settings.max_optimization_rounds))
        optimize_sends = []
        for job in jobs:
            job_id = job["job_id"]
            if profiles.get(job_id, {}).get("status") != "ok":
                continue
            review = current_review(state, job_id)
            if not review or review.get("status") != "ok":
                continue
            if int(review.get("score", 0)) >= threshold:
                continue
            if attempts_used(state, job_id) >= max_rounds:
                continue
            optimize_sends.append(Send("optimize_resume", _optimize_payload(state, job)))
        if optimize_sends:
            return Command(goto=optimize_sends)

        return Command(goto="coach")

    builder = StateGraph(AgentState)
    builder.add_node("intake", intake)
    builder.add_node("supervisor", supervisor)
    builder.add_node("analyze_job", analyze_job)
    builder.add_node("review_job", review_job)
    builder.add_node("optimize_resume", optimize_resume)
    builder.add_node("coach", coach)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "supervisor")
    builder.add_edge("analyze_job", "supervisor")
    builder.add_edge("review_job", "supervisor")
    builder.add_edge("optimize_resume", "supervisor")
    builder.add_edge("coach", END)
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after or None,
    )


__all__ = [
    "RunInputError",
    "build_initial_state",
    "build_main_graph",
    "clip_text",
    "normalize_jobs",
    "validate_run_input",
]
