from __future__ import annotations

import json

import pytest

from app.graph.job_analysis import build_job_analysis_graph
from tests.fakes import DEFAULT_HANDLERS, make_context


async def _analyze(settings, handlers, payload):
    context, models = make_context(settings, handlers)
    graph = build_job_analysis_graph(context)
    result = await graph.ainvoke(payload)
    return result, models, context


async def test_normal_job(settings) -> None:
    result, models, context = await _analyze(
        settings,
        DEFAULT_HANDLERS,
        {"job_id": "job-1", "title": "Backend Engineer", "job_text": "需要 Python 与 SQL。"},
    )
    profile = result["profile"]
    assert profile["job_id"] == "job-1"
    assert profile["status"] == "ok"
    assert profile["must_have"] == ["Python"]
    assert result["error"] is None
    system, human = models.last_messages("job_analyst")
    assert system[1].startswith("你是求职助手后端工作流中的一个受约束角色")
    assert "岗位分析专家" in system[1]
    assert "需要 Python" in human[1]


async def test_job_missing_requirements_fails(settings) -> None:
    def handler(messages):
        return json.dumps({"is_job_posting": True, "title": "", "must_have": [], "keywords": []})

    result, _, _ = await _analyze(
        settings,
        {"job_analyst": handler},
        {"job_id": "job-2", "title": "", "job_text": "只写了一个岗位名称。"},
    )
    assert result["profile"]["status"] == "failed"
    assert result["error"]["code"] == "job_no_requirements"


async def test_irrelevant_text_fails(settings) -> None:
    result, _, _ = await _analyze(
        settings,
        DEFAULT_HANDLERS,
        {"job_id": "job-3", "title": "x", "job_text": "NOT_A_JOB 今天天气很好。"},
    )
    assert result["profile"]["status"] == "failed"
    assert result["error"]["code"] == "job_not_recognized"


async def test_broken_model_output_marks_failure(settings) -> None:
    result, models, _ = await _analyze(
        settings,
        DEFAULT_HANDLERS,
        {"job_id": "job-4", "title": "Broken", "job_text": "BROKEN_JD"},
    )
    assert result["profile"]["status"] == "failed"
    assert "job analysis failed" in result["profile"]["error"]
    assert models.calls("job_analyst") == 2  # one retry


async def test_subgraph_ignores_resume_fields(settings) -> None:
    result, models, _ = await _analyze(
        settings,
        DEFAULT_HANDLERS,
        {
            "job_id": "job-5",
            "title": "Data Engineer",
            "job_text": "需要数据管道经验。",
            "resume_text": "SECRET_RESUME_CONTENT",
            "goal": "SECRET_GOAL",
        },
    )
    assert result["profile"]["status"] == "ok"
    system, human = models.last_messages("job_analyst")
    assert "SECRET_RESUME_CONTENT" not in system[1] + human[1]
    assert "SECRET_GOAL" not in system[1] + human[1]
    assert "resume_text" not in result
    assert "goal" not in result


@pytest.mark.parametrize("empty_value", ["", None])
async def test_empty_model_response_fails(settings, empty_value) -> None:
    def handler(messages):
        return empty_value

    result, _, _ = await _analyze(
        settings,
        {"job_analyst": handler},
        {"job_id": "job-6", "title": "t", "job_text": "text"},
    )
    assert result["profile"]["status"] == "failed"
