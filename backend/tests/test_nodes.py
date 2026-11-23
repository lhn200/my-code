from __future__ import annotations

from app.graph.nodes import run_coach, run_optimize_resume, run_review_job
from app.state import ReviewResult
from tests.fakes import (
    DEFAULT_HANDLERS,
    coach_handler,
    make_context,
    make_reviewer_handler,
    optimizer_handler,
)

PROFILE = {
    "job_id": "job-1",
    "title": "Backend Engineer",
    "company": "Acme",
    "must_have": ["Python", "Kubernetes"],
    "nice_to_have": [],
    "responsibilities": ["Build services"],
    "keywords": ["Python"],
    "status": "ok",
    "error": None,
}


async def test_reviewer_marks_unmentioned_tech_missing(settings) -> None:
    handlers = {"resume_reviewer": make_reviewer_handler({"Backend Engineer": 60})}
    context, models = make_context(settings, handlers)
    update = await run_review_job(
        {
            "job_id": "job-1",
            "goal": "后端",
            "profile": PROFILE,
            "resume_text": "Python developer with SQL experience.",
            "variant_version": 0,
        },
        context,
    )
    review = ReviewResult.model_validate(update["reviews"]["job-1::0"])
    assert review.score == 60
    assert "Kubernetes" in review.missing
    system, human = models.last_messages("resume_reviewer")
    assert "Python developer" not in system[1]
    assert "Python developer" in human[1]


async def test_review_after_optimization_records_round_score(settings) -> None:
    context, _ = make_context(settings, {"resume_reviewer": make_reviewer_handler()})
    update = await run_review_job(
        {
            "job_id": "job-1",
            "goal": "后端",
            "profile": PROFILE,
            "resume_text": "OPTIMIZED resume with Python",
            "variant_version": 1,
            "round": 1,
            "score_before": 60,
        },
        context,
    )
    assert update["reviews"]["job-1::1"]["score"] == 85
    round_entry = update["optimization_history"][0]
    assert round_entry["score_after"] == 85
    assert round_entry["score_before"] == 60


async def test_review_failure_is_marked(settings) -> None:
    context, _ = make_context(settings, {"resume_reviewer": lambda messages: RuntimeError("boom")})
    update = await run_review_job(
        {
            "job_id": "job-1",
            "goal": "x",
            "profile": PROFILE,
            "resume_text": "resume",
            "variant_version": 0,
        },
        context,
    )
    review = update["reviews"]["job-1::0"]
    assert review["status"] == "failed"
    assert update["errors"][0]["stage"] == "review_job"


async def test_optimizer_only_uses_baseline_and_creates_next_version(settings) -> None:
    context, models = make_context(settings, {"resume_optimizer": optimizer_handler})
    payload = {
        "job_id": "job-1",
        "goal": "后端",
        "profile": PROFILE,
        "review": {"score": 60, "missing": ["Kubernetes"]},
        "resume_text": "BASELINE_RESUME Python SQL",
        "current_variant_version": 0,
        "round": 1,
        "score_before": 60,
    }
    update = await run_optimize_resume(payload, context)
    variant = update["resume_variants"]["job-1"][0]
    assert variant["variant_version"] == 1
    assert "Kubernetes" not in variant["text"]
    assert update["optimization_attempts"]["job-1"] == 1
    assert update["optimization_history"][0]["score_after"] is None
    system, human = models.last_messages("resume_optimizer")
    assert "BASELINE_RESUME" in human[1]
    assert "BASELINE_RESUME" not in system[1]


async def test_two_low_jobs_get_independent_variants(settings) -> None:
    context, _ = make_context(settings, {"resume_optimizer": optimizer_handler})
    base = {
        "goal": "后端",
        "review": {"score": 55, "missing": ["Kubernetes"]},
        "resume_text": "BASELINE Python SQL",
        "current_variant_version": 0,
        "round": 1,
        "score_before": 55,
    }
    first = await run_optimize_resume(
        {**base, "job_id": "job-1", "profile": {**PROFILE, "job_id": "job-1", "title": "Backend"}},
        context,
    )
    second = await run_optimize_resume(
        {**base, "job_id": "job-2", "profile": {**PROFILE, "job_id": "job-2", "title": "Frontend"}},
        context,
    )
    first_text = first["resume_variants"]["job-1"][0]["text"]
    second_text = second["resume_variants"]["job-2"][0]["text"]
    assert "Backend" in first_text
    assert "Frontend" in second_text
    assert first_text != second_text
    assert "job-2" not in first["resume_variants"]


async def test_optimizer_failure_increments_attempts(settings) -> None:
    context, _ = make_context(settings, {"resume_optimizer": lambda messages: RuntimeError("down")})
    update = await run_optimize_resume(
        {
            "job_id": "job-1",
            "goal": "x",
            "profile": PROFILE,
            "review": {"score": 60},
            "resume_text": "baseline",
            "current_variant_version": 0,
            "round": 1,
            "score_before": 60,
        },
        context,
    )
    assert update["optimization_attempts"] == {"job-1": 1}
    assert update["errors"][0]["stage"] == "optimize_resume"


def _state_with_reports() -> dict:
    return {
        "goal": "找后端工作",
        "resume_text": "baseline Python",
        "jobs": [
            {"job_id": "job-1", "title": "Backend Engineer", "original_position_text": "Python"},
            {"job_id": "job-2", "title": "Data Engineer", "original_position_text": "SQL"},
        ],
        "job_profiles": {
            "job-1": PROFILE,
            "job-2": {**PROFILE, "job_id": "job-2", "title": "Data Engineer"},
        },
        "reviews": {
            "job-1::1": {"job_id": "job-1", "variant_version": 1, "score": 85, "dimensions": {}, "matched": ["Python"], "missing": [], "issues": [], "status": "ok"},
            "job-2::0": {"job_id": "job-2", "variant_version": 0, "score": 55, "dimensions": {}, "matched": ["SQL"], "missing": ["Kafka"], "issues": [], "status": "ok"},
        },
        "resume_variants": {"job-1": [{"job_id": "job-1", "variant_version": 1, "text": "OPTIMIZED"}]},
        "optimization_history": [
            {"job_id": "job-1", "round": 1, "variant_version": 1, "score_before": 60, "score_after": 85}
        ],
        "optimization_attempts": {"job-1": 1},
        "interview_reports": {
            "job-1": {
                "job_id": "job-1",
                "interview_thread_id": "it-1",
                "status": "completed",
                "generated_at": "2026-01-01",
                "highlights": ["清晰的架构解释"],
                "red_flags": ["缺少量化指标"],
                "improvements": ["补充性能数据"],
                "requirement_gaps": ["Kubernetes"],
                "answered_count": 5,
                "planned_count": 5,
                "dimension_averages": {},
                "overall_score": 78.0,
            },
            "job-2": {
                "job_id": "job-2",
                "interview_thread_id": "it-2",
                "status": "abandoned",
                "generated_at": "2026-01-02",
                "highlights": [],
                "red_flags": [],
                "improvements": ["完成剩余问题"],
                "requirement_gaps": [],
                "answered_count": 2,
                "planned_count": 5,
                "dimension_averages": {},
                "overall_score": None,
            },
        },
    }


async def test_coach_uses_scores_variants_and_interviews(settings) -> None:
    context, _ = make_context(settings, {"career_coach": coach_handler})
    update = await run_coach(_state_with_reports(), context)
    advice = update["advice"]
    assert "85" in advice
    assert "variant_version 1" in advice
    assert "清晰的架构解释" in advice
    assert "abandoned" in advice
    assert update["run_status"] == "succeeded"


async def test_coach_without_interview_reports_does_not_mention_interviews(settings) -> None:
    context, _ = make_context(settings, {"career_coach": coach_handler})
    state = _state_with_reports()
    state["interview_reports"] = {}
    update = await run_coach(state, context)
    assert "面试" not in update["advice"]


async def test_coach_falls_back_when_model_fails(settings) -> None:
    context, _ = make_context(settings, {"career_coach": lambda messages: RuntimeError("down")})
    update = await run_coach(_state_with_reports(), context)
    advice = update["advice"]
    assert "投递优先级" in advice
    assert "85" in advice
    assert "variant_version 1" in advice
    assert "改进方向" in advice
