from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.interview_reports import InterviewReportError, attach_interview_report
from tests.fakes import DEFAULT_HANDLERS, FakeModels, make_reviewer_handler

JOB = {"job_id": "job-1", "title": "Backend Engineer", "original_position_text": "Python"}


def _summary(interview_thread_id: str = "it-1", status: str = "completed") -> dict:
    return {
        "interview_thread_id": interview_thread_id,
        "status": status,
        "generated_at": "2026-02-01T10:00:00",
        "dimension_averages": {"clarity": 80.0},
        "overall_score": 80.0,
        "highlights": ["架构解释清晰"],
        "red_flags": ["缺少量化指标"],
        "improvements": ["补充性能数据"],
        "requirement_gaps": ["Kubernetes"],
        "answered_count": 5,
        "planned_count": 5,
    }


def _run(client: TestClient) -> str:
    response = client.post(
        "/api/runs",
        json={"goal": "后端", "resume_text": "Python SQL", "jobs": [JOB]},
    )
    assert response.status_code == 200
    return response.json()["thread_id"]


async def test_attach_report_updates_state_and_advice(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        thread_id = _run(client)
        before = client.get(f"/api/runs/{thread_id}/snapshots").json()["snapshots"]
        old_checkpoint = before[0]["checkpoint_id"]

        result = await attach_interview_report(
            client.app.state.graph,
            client.app.state.context,
            thread_id,
            "job-1",
            _summary(),
        )
        assert result["written"] is True
        assert result["retryable"] is False
        assert "架构解释清晰" in result["advice"]

        current = client.get(f"/api/runs/{thread_id}").json()
        report = current["result"]["interview_reports"]["job-1"]
        assert report["interview_thread_id"] == "it-1"
        assert report["status"] == "completed"
        assert "架构解释清晰" in current["result"]["advice"]
        assert "模拟面试" in current["result"]["advice"]

        after = client.get(f"/api/runs/{thread_id}/snapshots").json()["snapshots"]
        assert len(after) > len(before)

        historical = client.get(f"/api/runs/{thread_id}/snapshots/{old_checkpoint}").json()
        assert historical["state"]["interview_reports"] == {}


async def test_attach_report_is_idempotent(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        thread_id = _run(client)
        await attach_interview_report(
            client.app.state.graph, client.app.state.context, thread_id, "job-1", _summary()
        )
        calls_after_first = models.calls("career_coach")
        second = await attach_interview_report(
            client.app.state.graph, client.app.state.context, thread_id, "job-1", _summary()
        )
        assert second["written"] is False
        assert second["idempotent"] is True
        assert models.calls("career_coach") == calls_after_first


async def test_attach_report_replace_with_newer_interview(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        thread_id = _run(client)
        await attach_interview_report(
            client.app.state.graph,
            client.app.state.context,
            thread_id,
            "job-1",
            _summary("it-1", "abandoned"),
        )
        newer = _summary("it-2", "completed")
        newer["generated_at"] = "2026-02-02T10:00:00"
        result = await attach_interview_report(
            client.app.state.graph, client.app.state.context, thread_id, "job-1", newer
        )
        assert result["written"] is True
        report = client.get(f"/api/runs/{thread_id}").json()["result"]["interview_reports"][
            "job-1"
        ]
        assert report["interview_thread_id"] == "it-2"


async def test_attach_report_rejects_unknown_job_or_thread(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        thread_id = _run(client)
        with pytest.raises(InterviewReportError) as excinfo:
            await attach_interview_report(
                client.app.state.graph,
                client.app.state.context,
                thread_id,
                "job-unknown",
                _summary(),
            )
        assert excinfo.value.code == "job_not_in_run"

        with pytest.raises(InterviewReportError) as missing:
            await attach_interview_report(
                client.app.state.graph,
                client.app.state.context,
                "missing-thread",
                "job-1",
                _summary(),
            )
        assert missing.value.code == "thread_not_found"


async def test_advice_refresh_failure_keeps_report_and_old_advice(settings, monkeypatch) -> None:
    models = FakeModels(DEFAULT_HANDLERS)

    async def failing_coach(state, context):
        raise RuntimeError("coach down")

    monkeypatch.setattr(
        "app.services.interview_reports.run_coach", failing_coach
    )
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        thread_id = _run(client)
        old_advice = client.get(f"/api/runs/{thread_id}").json()["result"]["advice"]

        result = await attach_interview_report(
            client.app.state.graph, client.app.state.context, thread_id, "job-1", _summary()
        )
        assert result["written"] is True
        assert result["retryable"] is True
        assert result["advice"] == old_advice

        current = client.get(f"/api/runs/{thread_id}").json()["result"]
        assert current["interview_reports"]["job-1"]["status"] == "completed"
        assert current["advice"] == old_advice


async def test_review_isolation_after_report_attach(settings) -> None:
    models = FakeModels(
        {**DEFAULT_HANDLERS, "resume_reviewer": make_reviewer_handler({"Backend Engineer": 60})}
    )
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        thread_id = _run(client)
        before = client.get(f"/api/runs/{thread_id}").json()["result"]
        await attach_interview_report(
            client.app.state.graph, client.app.state.context, thread_id, "job-1", _summary()
        )
        after = client.get(f"/api/runs/{thread_id}").json()["result"]
        assert before["jobs"][0]["review"]["score"] == after["jobs"][0]["review"]["score"]
        assert before["jobs"][0]["variants"] == after["jobs"][0]["variants"]
