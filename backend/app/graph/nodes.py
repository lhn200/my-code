"""Business nodes: review, optimize, interview and coach."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..llm import call_json, call_text
from ..memory.context_assembler import ContextOverflow
from ..state import (
    InterviewReportSummary,
    JobProfile,
    OptimizationRound,
    ResumeVariant,
    ReviewResult,
    make_review_result,
    review_key,
)
from .context import GraphContext

logger = logging.getLogger(__name__)


class ReviewOutput(BaseModel):
    dimensions: dict[str, Any] = Field(default_factory=dict)
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class OptimizerOutput(BaseModel):
    variant_text: str = ""
    changes: list[str] = Field(default_factory=list)
    remaining_gaps: list[str] = Field(default_factory=list)


class InterviewOutput(BaseModel):
    overall_score: float = Field(ge=0, le=100)
    dimension_averages: dict[str, float] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    requirement_gaps: list[str] = Field(default_factory=list)
    answered_count: int = Field(default=0, ge=0)
    planned_count: int = Field(default=0, ge=0)


def current_variant_version(state: Mapping[str, Any], job_id: str) -> int:
    variants = state.get("resume_variants", {}).get(job_id) or []
    versions = [int(item.get("variant_version", 0)) for item in variants]
    return max(versions) if versions else 0


def current_variant(state: Mapping[str, Any], job_id: str) -> dict[str, Any] | None:
    variants = state.get("resume_variants", {}).get(job_id) or []
    if not variants:
        return None
    return max(variants, key=lambda item: int(item.get("variant_version", 0)))


def current_review(state: Mapping[str, Any], job_id: str) -> dict[str, Any] | None:
    version = current_variant_version(state, job_id)
    return state.get("reviews", {}).get(review_key(job_id, version))


def rounds_used(state: Mapping[str, Any], job_id: str) -> int:
    return sum(
        1
        for item in state.get("optimization_history", [])
        if item.get("job_id") == job_id
    )


def attempts_used(state: Mapping[str, Any], job_id: str) -> int:
    return int(state.get("optimization_attempts", {}).get(job_id, 0))


def interview_attempts_used(state: Mapping[str, Any], job_id: str) -> int:
    return int(state.get("interview_attempts", {}).get(job_id, 0))


def job_summaries(state: Mapping[str, Any], settings: Any) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for job in sorted(state.get("jobs", []), key=lambda item: item["job_id"]):
        job_id = job["job_id"]
        profile = state.get("job_profiles", {}).get(job_id)
        review = current_review(state, job_id)
        variant = current_variant(state, job_id)
        history = [
            item
            for item in state.get("optimization_history", [])
            if item.get("job_id") == job_id
        ]
        usable = bool(profile and profile.get("status") == "ok" and review and review.get("status") == "ok")
        score = int(review["score"]) if usable else None
        risk = bool(
            usable
            and score is not None
            and score < settings.resume_match_threshold
            and attempts_used(state, job_id) >= settings.max_optimization_rounds
        )
        summaries.append(
            {
                "job_id": job_id,
                "title": job.get("title") or (profile or {}).get("title", ""),
                "status": "ok" if usable else "failed",
                "error": None if usable else (profile or {}).get("error") or "review unavailable",
                "score": score,
                "resume_source": "variant" if variant else "baseline",
                "variant_version": int(variant.get("variant_version", 0)) if variant else 0,
                "matched": (review or {}).get("matched", []),
                "missing": (review or {}).get("missing", []),
                "issues": (review or {}).get("issues", []),
                "optimization_rounds": len(history),
                "risk": risk,
            }
        )
    return summaries


def compute_run_status(state: Mapping[str, Any], settings: Any) -> str:
    summaries = job_summaries(state, settings)
    if any(item["status"] == "ok" for item in summaries) and all(
        item["status"] == "ok" for item in summaries
    ):
        return "succeeded"
    if any(item["status"] == "ok" for item in summaries):
        return "partial"
    return "failed"


def _review_failure(job_id: str, version: int, message: str) -> ReviewResult:
    return ReviewResult(job_id=job_id, variant_version=version, status="failed", error=message)


async def run_review_job(payload: Mapping[str, Any], context: GraphContext) -> dict[str, Any]:
    job_id = str(payload["job_id"])
    version = int(payload.get("variant_version", 0))
    profile = payload.get("profile") or {}
    session = payload.get("session") or {}
    label = f"review_job:{job_id}:{version}"
    meta: dict[str, Any] | None = None
    try:
        async with context.semaphore:  # type: ignore[union-attr]
            messages, meta = context.prepare(
                "resume_reviewer",
                session,
                {
                    "goal": payload.get("goal", ""),
                    "profile_json": profile,
                    "resume_text": payload.get("resume_text", ""),
                },
                job_profile=profile,
            )
            output = await call_json(
                context.model("resume_reviewer"), messages, ReviewOutput, attempts=2
            )
        review = make_review_result(output.model_dump(), job_id, version)
    except ContextOverflow as exc:
        message = "context budget exceeded before resume review"
        failed = _review_failure(job_id, version, message)
        return {
            "reviews": {review_key(job_id, version): failed.model_dump()},
            "errors": [
                {
                    "stage": "review_job",
                    "job_id": job_id,
                    "code": "context_overflow",
                    "message": message,
                }
            ],
            "context_budget_meta": {
                label: {"role": "resume_reviewer", "overflow": True, **exc.meta}
            },
        }
    except Exception as exc:
        message = f"resume review failed: {exc}"
        failed = _review_failure(job_id, version, message)
        update: dict[str, Any] = {
            "reviews": {review_key(job_id, version): failed.model_dump()},
            "errors": [
                {
                    "stage": "review_job",
                    "job_id": job_id,
                    "code": "review_failed",
                    "message": message,
                }
            ],
        }
        if meta is not None:
            update["context_budget_meta"] = {label: meta}
        return update

    update: dict[str, Any] = {"reviews": {review_key(job_id, version): review.model_dump()}}
    if meta is not None:
        update["context_budget_meta"] = {label: meta}
    round_number = payload.get("round")
    if round_number is not None:
        round_entry = OptimizationRound(
            job_id=job_id,
            round=int(round_number),
            variant_version=version,
            score_before=int(payload.get("score_before", 0)),
            score_after=review.score,
        )
        update["optimization_history"] = [round_entry.model_dump()]
    return update


async def run_optimize_resume(payload: Mapping[str, Any], context: GraphContext) -> dict[str, Any]:
    job_id = str(payload["job_id"])
    round_number = int(payload.get("round", 1))
    current_version = int(payload.get("current_variant_version", 0))
    score_before = int(payload.get("score_before", 0))
    profile = payload.get("profile") or {}
    session = payload.get("session") or {}
    label = f"optimize_resume:{job_id}:{round_number}"
    meta: dict[str, Any] | None = None
    try:
        async with context.semaphore:  # type: ignore[union-attr]
            messages, meta = context.prepare(
                "resume_optimizer",
                session,
                {
                    "goal": payload.get("goal", ""),
                    "profile_json": profile,
                    "review_json": payload.get("review") or {},
                    "baseline_resume": payload.get("resume_text", ""),
                    "interview_report_json": payload.get("interview_report") or {},
                },
                job_profile=profile,
            )
            output = await call_json(
                context.model("resume_optimizer"), messages, OptimizerOutput, attempts=2
            )
        text = output.variant_text.strip()
        if not text:
            raise ValueError("optimizer returned an empty resume")
        text = text[: context.settings.max_input_chars]
        variant = ResumeVariant(
            job_id=job_id,
            variant_version=current_version + 1,
            text=text,
            base_version=0,
        )
        summary = "; ".join(output.changes)[:500]
        if output.remaining_gaps:
            summary = (summary + " | gaps: " + "; ".join(output.remaining_gaps))[:500]
        round_entry = OptimizationRound(
            job_id=job_id,
            round=round_number,
            variant_version=variant.variant_version,
            score_before=score_before,
            score_after=None,
            summary=summary,
        )
    except ContextOverflow as exc:
        message = "context budget exceeded before resume optimization"
        return {
            "optimization_attempts": {job_id: round_number},
            "errors": [
                {
                    "stage": "optimize_resume",
                    "job_id": job_id,
                    "code": "context_overflow",
                    "message": message,
                }
            ],
            "context_budget_meta": {
                label: {"role": "resume_optimizer", "overflow": True, **exc.meta}
            },
        }
    except Exception as exc:
        message = f"resume optimization failed: {exc}"
        update: dict[str, Any] = {
            "optimization_attempts": {job_id: round_number},
            "errors": [
                {
                    "stage": "optimize_resume",
                    "job_id": job_id,
                    "code": "optimization_failed",
                    "message": message,
                }
            ],
        }
        if meta is not None:
            update["context_budget_meta"] = {label: meta}
        return update

    return {
        "resume_variants": {job_id: [variant.model_dump()]},
        "optimization_history": [round_entry.model_dump()],
        "optimization_attempts": {job_id: round_number},
        "context_budget_meta": {label: meta} if meta is not None else {},
    }


async def run_interview(payload: Mapping[str, Any], context: GraphContext) -> dict[str, Any]:
    job_id = str(payload["job_id"])
    round_number = int(payload.get("round", 1))
    variant_version = int(payload.get("variant_version", 0))
    profile = payload.get("profile") or {}
    session = payload.get("session") or {}
    label = f"interview:{job_id}:{round_number}"
    meta: dict[str, Any] | None = None
    try:
        async with context.semaphore:  # type: ignore[union-attr]
            messages, meta = context.prepare(
                "interviewer",
                session,
                {
                    "goal": payload.get("goal", ""),
                    "profile_json": profile,
                    "review_json": payload.get("review") or {},
                    "resume_text": payload.get("resume_text", ""),
                    "prior_interview_json": payload.get("prior_report") or {},
                },
                job_profile=profile,
            )
            output = await call_json(
                context.model("interviewer"), messages, InterviewOutput, attempts=2
            )
        report = InterviewReportSummary(
            job_id=job_id,
            interview_thread_id=f"auto-{job_id}-{round_number}",
            status="completed",
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            variant_version=variant_version,
            source="offline",
            dimension_averages={
                key: max(0.0, min(100.0, float(value)))
                for key, value in output.dimension_averages.items()
            },
            overall_score=max(0.0, min(100.0, float(output.overall_score))),
            highlights=output.highlights,
            red_flags=output.red_flags,
            improvements=output.improvements,
            requirement_gaps=output.requirement_gaps,
            answered_count=output.answered_count,
            planned_count=output.planned_count,
        )
    except ContextOverflow as exc:
        message = "context budget exceeded before interview"
        return {
            "interview_attempts": {job_id: round_number},
            "errors": [
                {
                    "stage": "interview",
                    "job_id": job_id,
                    "code": "context_overflow",
                    "message": message,
                }
            ],
            "context_budget_meta": {
                label: {"role": "interviewer", "overflow": True, **exc.meta}
            },
        }
    except Exception as exc:
        message = f"auto interview failed: {exc}"
        update: dict[str, Any] = {
            "interview_attempts": {job_id: round_number},
            "errors": [
                {
                    "stage": "interview",
                    "job_id": job_id,
                    "code": "interview_failed",
                    "message": message,
                }
            ],
        }
        if meta is not None:
            update["context_budget_meta"] = {label: meta}
        return update

    return {
        "interview_reports": {job_id: report.model_dump()},
        "interview_attempts": {job_id: round_number},
        "context_budget_meta": {label: meta} if meta is not None else {},
    }


def _fallback_advice(state: Mapping[str, Any], settings: Any) -> str:
    summaries = [item for item in job_summaries(state, settings) if item["status"] == "ok"]
    unavailable = [item for item in job_summaries(state, settings) if item["status"] != "ok"]
    reports = state.get("interview_reports") or {}
    lines: list[str] = ["## 投递优先级"]
    if summaries:
        ranked = sorted(summaries, key=lambda item: (-(item["score"] or 0), item["job_id"]))
        for index, item in enumerate(ranked, start=1):
            version = f"variant_version {item['variant_version']}" if item["variant_version"] else "基线简历"
            lines.append(
                f"{index}. {item['title']} (`{item['job_id']}`) — 匹配分 {item['score']}，"
                f"建议投递{version}；理由：{', '.join(item['matched'][:3]) or '综合匹配'}"
            )
    else:
        lines.append("暂无可用岗位结果，无法给出投递优先级。")
    lines.append("")
    lines.append("## 各岗位建议")
    for item in job_summaries(state, settings):
        if item["status"] != "ok":
            lines.append(f"- {item['title']} (`{item['job_id']}`)：结果不可用（{item['error']}），暂不给出投递结论。")
            continue
        version = f"variant_version {item['variant_version']}" if item["variant_version"] else "基线简历"
        gaps = "、".join(item["missing"][:5]) or "无明显硬性缺口"
        lines.append(
            f"- {item['title']} (`{item['job_id']}`)：使用{version}，匹配分 {item['score']}；"
            f"主要缺口：{gaps}；建议优先补强与岗位最相关的缺失项。"
        )
    lines.append("")
    if reports:
        lines.append("## 面试反馈")
        for job_id, report in sorted(reports.items()):
            status = report.get("status", "")
            if status == "completed":
                lines.append(
                    f"- `{job_id}`：模拟面试已完成，亮点：{'、'.join(report.get('highlights', [])[:2]) or '无'}；"
                    f"改进方向：{'、'.join(report.get('improvements', [])[:2]) or '无'}。该结论来自模拟面试，不代表简历评审分数变化。"
                )
            else:
                lines.append(
                    f"- `{job_id}`：本次模拟面试未完成（abandoned），已答 "
                    f"{report.get('answered_count', 0)}/{report.get('planned_count', 0)} 题，"
                    f"已覆盖的改进点：{'、'.join(report.get('improvements', [])[:2]) or '暂无'}。"
                )
        lines.append("")
    lines.append("## 下一步行动")
    if summaries:
        lines.append("- 针对未达标岗位的缺失项补充可验证的项目或经历后再投递。")
    lines.append("- 投递前按岗位版本核对简历，避免把某一岗位的定制版本用于其他岗位。")
    if unavailable:
        lines.append("- 对结果不可用的岗位，检查岗位文本是否完整后重新发起分析。")
    return "\n".join(lines)


async def run_coach(state: Mapping[str, Any], context: GraphContext) -> dict[str, Any]:
    settings = context.settings
    summaries = job_summaries(state, settings)
    reports = state.get("interview_reports") or {}
    advice: str
    meta: dict[str, Any] | None = None
    try:
        async with context.semaphore:  # type: ignore[union-attr]
            messages, meta = context.prepare(
                "career_coach",
                state,
                {
                    "goal": state.get("goal", ""),
                    "job_summaries_json": summaries,
                    "interview_reports_json": reports,
                },
            )
            advice = await call_text(context.model("career_coach"), messages, attempts=2)
    except ContextOverflow:
        logger.warning("coach context overflow, using deterministic advice")
        advice = _fallback_advice(state, settings)
    except Exception as exc:
        logger.warning("career coach model call failed, using deterministic advice: %s", exc)
        advice = _fallback_advice(state, settings)
    update: dict[str, Any] = {
        "advice": advice,
        "run_status": compute_run_status(state, settings),
    }
    if meta is not None:
        update["context_budget_meta"] = {"coach": meta}
    return update


__all__ = [
    "InterviewOutput",
    "OptimizerOutput",
    "ReviewOutput",
    "attempts_used",
    "compute_run_status",
    "current_review",
    "current_variant",
    "current_variant_version",
    "interview_attempts_used",
    "job_summaries",
    "rounds_used",
    "run_coach",
    "run_interview",
    "run_optimize_resume",
    "run_review_job",
]
