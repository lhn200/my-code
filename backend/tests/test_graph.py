from __future__ import annotations

import pytest

from app.graph.main import (
    RunInputError,
    build_initial_state,
    build_main_graph,
    validate_run_input,
)
from app.graph.nodes import job_summaries
from app.memory.context_assembler import ContextOverflow
from tests.fakes import (
    DEFAULT_HANDLERS,
    analyst_handler,
    coach_handler,
    interviewer_handler,
    json_block,
    make_context,
    make_interviewer_handler,
    make_reviewer_handler,
    optimizer_handler,
    untrusted_block,
)


def _jobs(count: int = 2) -> list[dict[str, str]]:
    titles = ["Backend Engineer", "Frontend Engineer", "Data Engineer", "ML Engineer", "SRE", "QA"]
    return [
        {
            "job_id": f"job-{index + 1}",
            "title": titles[index],
            "original_position_text": f"{titles[index]} 需要 Python 与 SQL。",
        }
        for index in range(count)
    ]


def _handlers(reviewer=None, interviewer=None):
    return {
        "job_analyst": analyst_handler,
        "resume_reviewer": reviewer or make_reviewer_handler(),
        "resume_optimizer": optimizer_handler,
        "career_coach": coach_handler,
        "interviewer": interviewer or interviewer_handler,
    }


async def test_three_jobs_run_in_parallel_and_merge(settings) -> None:
    context, models = make_context(settings, _handlers())
    graph = build_main_graph(context)
    final = await graph.ainvoke(
        build_initial_state("找后端工作", "Python SQL resume", _jobs(3))
    )
    assert set(final["job_profiles"]) == {"job-1", "job-2", "job-3"}
    assert len(final["reviews"]) == 3
    assert models.calls("job_analyst") == 3
    assert models.calls("resume_reviewer") == 3
    assert final["advice"]
    assert final["prompt_versions"]
    assert final["run_status"] == "succeeded"


async def test_single_job_failure_does_not_block_others(settings) -> None:
    context, _ = make_context(settings, _handlers())
    broken_jobs = [
        {"job_id": "job-1", "title": "Backend Engineer", "original_position_text": "Python"},
        {"job_id": "job-2", "title": "Broken", "original_position_text": "BROKEN_JD"},
        {"job_id": "job-3", "title": "Data Engineer", "original_position_text": "SQL"},
    ]
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python SQL", broken_jobs))
    assert final["job_profiles"]["job-2"]["status"] == "failed"
    assert final["job_profiles"]["job-1"]["status"] == "ok"
    assert len(final["reviews"]) == 2
    assert final["run_status"] == "partial"
    assert "结果不可用" in final["advice"]


async def test_two_low_jobs_each_get_one_round_then_stop(settings) -> None:
    reviewer = make_reviewer_handler(
        {"Backend Engineer": 60, "Frontend Engineer": 60}, improved_score=85
    )
    context, _ = make_context(settings, _handlers(reviewer))
    graph = build_main_graph(context)
    final = await graph.ainvoke(
        build_initial_state("goal", "Python SQL", _jobs(2))
    )
    assert final["reviews"]["job-1::0"]["score"] == 60
    assert final["reviews"]["job-2::0"]["score"] == 60
    assert final["reviews"]["job-1::1"]["score"] == 85
    assert final["reviews"]["job-2::1"]["score"] == 85
    assert [item["variant_version"] for item in final["resume_variants"]["job-1"]] == [1]
    assert [item["variant_version"] for item in final["resume_variants"]["job-2"]] == [1]
    assert final["optimization_attempts"] == {"job-1": 1, "job-2": 1}
    assert len(final["optimization_history"]) == 2
    assert "variant_version 1" in final["advice"]


async def test_round_limit_exits_with_risk(settings) -> None:
    limited = settings.model_copy(update={"max_optimization_rounds": 2})
    reviewer = make_reviewer_handler(always_low=True)
    context, models = make_context(limited, _handlers(reviewer))
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))
    assert final["optimization_attempts"]["job-1"] == 2
    assert [item["variant_version"] for item in final["resume_variants"]["job-1"]] == [1, 2]
    assert len(final["optimization_history"]) == 2
    assert models.calls("resume_optimizer") == 2
    summaries = job_summaries(final, limited)
    assert summaries[0]["risk"] is True


async def test_passed_job_gets_no_variant(settings) -> None:
    context, models = make_context(
        settings, _handlers(make_reviewer_handler({"Backend Engineer": 90}))
    )
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))
    assert final["reviews"]["job-1::0"]["score"] == 90
    assert not final["resume_variants"].get("job-1")
    assert models.calls("resume_optimizer") == 0
    assert "90" in final["advice"]
    assert "基线简历" in final["advice"]
    assert "variant_version" not in final["advice"]
    assert "已优化" not in final["advice"]


async def test_threshold_from_settings_triggers_round(settings) -> None:
    strict = settings.model_copy(update={"resume_match_threshold": 80})
    reviewer = make_reviewer_handler({"Backend Engineer": 75}, improved_score=85)
    context, models = make_context(strict, _handlers(reviewer))
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))
    assert final["reviews"]["job-1::0"]["score"] == 75
    assert final["reviews"]["job-1::1"]["score"] == 85
    assert models.calls("resume_optimizer") == 1


async def test_single_round_limit_from_settings(settings) -> None:
    limited = settings.model_copy(update={"max_optimization_rounds": 1})
    reviewer = make_reviewer_handler(always_low=True)
    context, models = make_context(limited, _handlers(reviewer))
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))
    assert final["optimization_attempts"]["job-1"] == 1
    assert [item["variant_version"] for item in final["resume_variants"]["job-1"]] == [1]
    assert models.calls("resume_optimizer") == 1
    assert job_summaries(final, limited)[0]["risk"] is True


async def test_six_jobs_rejected_before_checkpoint(settings) -> None:
    state = build_initial_state("goal", "Python", _jobs(6))
    with pytest.raises(RunInputError) as excinfo:
        validate_run_input(state, settings)
    assert excinfo.value.code == "too_many_jobs"


async def test_five_jobs_accepted(settings) -> None:
    context, _ = make_context(settings, _handlers())
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(5)))
    assert len(final["job_profiles"]) == 5
    assert final["run_status"] == "succeeded"


async def test_max_jobs_follows_settings(settings) -> None:
    restricted = settings.model_copy(update={"max_jobs": 2})
    with pytest.raises(RunInputError) as excinfo:
        validate_run_input(build_initial_state("goal", "Python", _jobs(3)), restricted)
    assert excinfo.value.code == "too_many_jobs"

    context, _ = make_context(restricted, _handlers())
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(2)))
    assert len(final["job_profiles"]) == 2


async def test_repository_jobs_have_generated_ids(settings) -> None:
    context, _ = make_context(settings, _handlers())
    graph = build_main_graph(context)
    jobs = [{"title": "Backend Engineer", "original_position_text": "Python"}]
    final = await graph.ainvoke(build_initial_state("goal", "Python", jobs))
    assert list(final["job_profiles"]) == ["job-1"]


async def test_interview_runs_after_reviews_and_ends_when_score_passes(settings) -> None:
    context, models = make_context(settings, _handlers())
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(2)))
    assert set(final["interview_reports"]) == {"job-1", "job-2"}
    assert final["interview_attempts"] == {"job-1": 1, "job-2": 1}
    assert models.calls("interviewer") == 2
    assert models.calls("career_coach") == 2
    assert final["run_status"] == "succeeded"


async def test_interview_uses_latest_optimized_resume(settings) -> None:
    reviewer = make_reviewer_handler({"Backend Engineer": 60}, improved_score=85)
    context, models = make_context(settings, _handlers(reviewer))
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))
    human = models.last_messages("interviewer")[-1][1]
    assert "OPTIMIZED" in untrusted_block(human, "RESUME_TEXT")
    assert final["interview_attempts"]["job-1"] == 1


async def test_low_interview_score_retries_until_limit(settings) -> None:
    limited = settings.model_copy(update={"max_interview_rounds": 2})
    handlers = _handlers(interviewer=make_interviewer_handler(always_low=True))
    context, models = make_context(limited, handlers)
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))
    assert final["interview_attempts"] == {"job-1": 2}
    assert final["interview_reports"]["job-1"]["overall_score"] == 60
    assert models.calls("interviewer") == 2
    assert models.calls("career_coach") == 3


async def test_low_interview_triggers_feedback_driven_optimization(settings) -> None:
    interviewer = make_interviewer_handler({"Backend Engineer": 55}, improved_score=90)
    context, models = make_context(settings, _handlers(interviewer=interviewer))
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))

    human = models.last_messages("resume_optimizer")[-1][1]
    report_json = untrusted_block(human, "INTERVIEW_REPORT_JSON")
    assert "Kubernetes" in report_json
    assert final["optimization_attempts"]["job-1"] == 1
    assert final["interview_attempts"]["job-1"] == 2
    assert final["interview_reports"]["job-1"]["variant_version"] >= 1
    assert models.calls("interviewer") == 2


async def test_interview_recovers_and_ends_early(settings) -> None:
    interviewer = make_interviewer_handler({"Backend Engineer": 55}, improved_score=88)
    context, models = make_context(settings, _handlers(interviewer=interviewer))
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))
    assert final["interview_attempts"] == {"job-1": 2}
    assert final["interview_reports"]["job-1"]["overall_score"] == 88
    assert models.calls("interviewer") == 2
    assert models.calls("career_coach") == 3


async def test_interview_failure_is_recorded_and_loop_terminates(settings) -> None:
    limited = settings.model_copy(update={"max_interview_rounds": 2})
    handlers = _handlers(interviewer=lambda messages: RuntimeError("interview model down"))
    context, models = make_context(limited, handlers)
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(1)))

    failures = [error for error in final["errors"] if error.get("code") == "interview_failed"]
    # 相同 (stage, job_id, message) 的错误会按确定性规则去重，这里只断言失败被记录
    assert failures
    assert all(error["stage"] == "interview" for error in failures)
    assert all(error["job_id"] == "job-1" for error in failures)
    assert final["interview_attempts"] == {"job-1": 2}
    assert not final.get("interview_reports")
    # 每轮 call_json 自带 2 次尝试
    assert models.calls("interviewer") == limited.max_interview_rounds * 2
    assert models.calls("career_coach") == 3
    assert final["advice"]
    assert final["run_status"] == "succeeded"


async def test_interview_failure_does_not_block_other_jobs(settings) -> None:
    limited = settings.model_copy(update={"max_interview_rounds": 2})

    def mixed_handler(messages):
        human = messages[-1][1]
        profile = json_block(human, "JOB_PROFILE_JSON") or {}
        if profile.get("title") == "Frontend Engineer":
            return RuntimeError("interview model down")
        return interviewer_handler(messages)

    context, models = make_context(limited, _handlers(interviewer=mixed_handler))
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(2)))

    # job-1 面试成功并产出报告，job-2 两轮均失败但不影响 job-1 与最终建议
    assert set(final["interview_reports"]) == {"job-1"}
    assert final["interview_attempts"] == {"job-1": 1, "job-2": 2}
    failures = [error for error in final["errors"] if error.get("code") == "interview_failed"]
    assert failures
    assert all(error["stage"] == "interview" for error in failures)
    assert all(error["job_id"] == "job-2" for error in failures)
    # job-1 成功一次调用；job-2 每轮 call_json 自带 2 次尝试
    assert models.calls("interviewer") == 1 + limited.max_interview_rounds * 2
    assert models.calls("career_coach") == 3
    assert "job-1 模拟面试已完成" in final["advice"]
    assert final["run_status"] == "succeeded"


async def test_interview_context_overflow_is_recorded(settings, monkeypatch) -> None:
    limited = settings.model_copy(update={"max_interview_rounds": 1})
    context, models = make_context(limited, _handlers())
    original_prepare = context.prepare

    def prepare(role, state, values, *, job_profile=None):
        title = (job_profile or {}).get("title", "")
        if role == "interviewer" and title == "Frontend Engineer":
            raise ContextOverflow(
                "context budget exceeded before interview",
                {"reason": "budget_exceeded", "tokens": {"total": 9000}},
            )
        return original_prepare(role, state, values, job_profile=job_profile)

    monkeypatch.setattr(context, "prepare", prepare)
    graph = build_main_graph(context)
    final = await graph.ainvoke(build_initial_state("goal", "Python", _jobs(2)))

    # 超限只影响 job-2，job-1 仍正常完成面试
    assert set(final["interview_reports"]) == {"job-1"}
    assert final["interview_attempts"] == {"job-1": 1, "job-2": 1}
    overflow = [error for error in final["errors"] if error.get("code") == "context_overflow"]
    assert overflow
    assert all(error["stage"] == "interview" for error in overflow)
    assert all(error["job_id"] == "job-2" for error in overflow)
    meta = final["context_budget_meta"]["interview:job-2:1"]
    assert meta["role"] == "interviewer"
    assert meta["overflow"] is True
    assert meta["reason"] == "budget_exceeded"
    # 超限发生在模型调用之前，job-2 不产生调用；job-1 正常调用一次
    assert models.calls("interviewer") == 1
    assert models.calls("career_coach") == 2
    assert final["advice"]
    assert final["run_status"] == "succeeded"

