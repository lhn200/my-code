from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.resume_pdf import render_resume_pdf, resume_pdf_filename
from tests.auth_utils import authenticate
from tests.fakes import DEFAULT_HANDLERS, FakeModels, make_reviewer_handler


def _payload() -> dict:
    return {
        "goal": "找后端工作",
        "resume_text": "张三\nPython SQL",
        "jobs": [
            {
                "title": "Backend Engineer",
                "original_position_text": "需要 Python 与 SQL",
            }
        ],
    }


def _make_client(settings, reviewer=None) -> TestClient:
    handlers = dict(DEFAULT_HANDLERS)
    if reviewer is not None:
        handlers["resume_reviewer"] = reviewer
    return TestClient(create_app(settings, model_factory=FakeModels(handlers).factory))


def test_render_resume_pdf_handles_markdown_and_chinese() -> None:
    pdf = render_resume_pdf(
        title="后端工程师",
        company="示例公司",
        text=(
            "# 张三\n\n**后端工程师**\n\n## 工作经历\n\n"
            "- 支付网关重构，QPS 提升 3 倍\n1. Python / SQL\n\n```\ncode\n```\n"
        ),
        version=2,
        score=86,
        source="variant",
    )
    assert pdf.startswith(b"%PDF")
    assert resume_pdf_filename("后端/工程师", 2) == "后端_工程师-简历-v2.pdf"


def test_download_optimized_resume_pdf(settings) -> None:
    reviewer = make_reviewer_handler({"Backend Engineer": 60}, improved_score=85)
    with _make_client(settings, reviewer) as client:
        authenticate(client)
        created = client.post("/api/runs", json=_payload())
        assert created.status_code == 200, created.text
        thread_id = created.json()["thread_id"]

        response = client.get(f"/api/runs/{thread_id}/jobs/job-1/resume.pdf")

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/pdf")
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert "filename*=UTF-8''" in disposition
        assert response.content.startswith(b"%PDF")


def test_download_baseline_resume_pdf(settings) -> None:
    with _make_client(settings) as client:
        authenticate(client)
        thread_id = client.post("/api/runs", json=_payload()).json()["thread_id"]

        response = client.get(f"/api/runs/{thread_id}/jobs/job-1/resume.pdf")

        assert response.status_code == 200, response.text
        assert response.content.startswith(b"%PDF")


def test_download_unknown_job_returns_404(settings) -> None:
    with _make_client(settings) as client:
        authenticate(client)
        thread_id = client.post("/api/runs", json=_payload()).json()["thread_id"]

        response = client.get(f"/api/runs/{thread_id}/jobs/missing/resume.pdf")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "job_not_found"


def test_download_requires_auth(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/runs/thread-x/jobs/job-1/resume.pdf")

        assert response.status_code == 401
