"""Build API-facing run results from graph state."""

from __future__ import annotations

from typing import Any, Mapping

from ..state import (
    InterviewReportSummary,
    JobProfile,
    JobResult,
    OptimizationRound,
    ResumeVariant,
    ReviewResult,
    RunResult,
)
from ..graph.nodes import compute_run_status, current_review, current_variant


def build_run_result(state: Mapping[str, Any], thread_id: str, settings: Any) -> RunResult:
    jobs: list[JobResult] = []
    reports: dict[str, InterviewReportSummary] = {}
    for job_id, report in (state.get("interview_reports") or {}).items():
        try:
            reports[job_id] = InterviewReportSummary.model_validate(report)
        except Exception:
            continue

    for job in sorted(state.get("jobs") or [], key=lambda item: item["job_id"]):
        job_id = job["job_id"]
        raw_profile = (state.get("job_profiles") or {}).get(job_id)
        profile = JobProfile.model_validate(raw_profile) if raw_profile else None
        raw_review = current_review(state, job_id)
        review = ReviewResult.model_validate(raw_review) if raw_review else None
        variant = current_variant(state, job_id)
        variants = [
            ResumeVariant.model_validate(item)
            for item in (state.get("resume_variants") or {}).get(job_id, [])
        ]
        history = [
            OptimizationRound.model_validate(item)
            for item in (state.get("optimization_history") or [])
            if item.get("job_id") == job_id
        ]
        history.sort(key=lambda item: (item.variant_version, item.round))

        usable = bool(profile and profile.status == "ok" and review and review.status == "ok")
        error = None
        if profile is not None and profile.status != "ok":
            error = profile.error
        elif not usable:
            error = review.error if review is not None else "job result is unavailable"

        jobs.append(
            JobResult(
                job_id=job_id,
                title=job.get("title") or (profile.title if profile else ""),
                status="ok" if usable else "failed",
                error=error,
                profile=profile,
                resume_source="variant" if variant else "baseline",
                current_variant_version=int(variant.get("variant_version", 0)) if variant else 0,
                resume_text=variant["text"] if variant else state.get("resume_text", ""),
                review=review,
                variants=variants,
                optimization_history=history,
            )
        )

    return RunResult(
        run_status=compute_run_status(state, settings),
        thread_id=thread_id,
        advice=state.get("advice", ""),
        jobs=jobs,
        interview_reports=reports,
    )


__all__ = ["build_run_result"]
