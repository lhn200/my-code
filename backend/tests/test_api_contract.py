from __future__ import annotations

from fastapi.testclient import TestClient

from app.checkpoint.sqlite import new_thread_id
from app.db import connect
from app.db.runs import create_run as insert_run
from app.main import create_app
from tests.auth_utils import authenticate
from tests.fakes import DEFAULT_HANDLERS, FakeModels


def _payload(jobs=None, **overrides):
    body = {
        "goal": "寻找后端岗位",
        "resume_text": "Python developer with SQL experience",
        "jobs": jobs
        if jobs is not None
        else [
            {
                "job_id": "job-1",
                "title": "Backend Engineer",
                "original_position_text": "需要 Python 与 SQL",
            }
        ],
    }
    body.update(overrides)
    return body


def _fields(response):
    return {(item["field"], item["type"]) for item in response.json()["error"]["fields"]}


def _submit_and_fetch(client, payload):
    """创建接口立即返回 thread_id，真正的结果通过 GET 查询。"""
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["run_status"] == "running"
    assert created["jobs"] == []
    thread_id = created["thread_id"]
    assert thread_id
    detail = client.get(f"/api/runs/{thread_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()


def test_running_run_without_checkpoint_returns_pending(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        user_id = client.get("/api/auth/me").json()["id"]
        thread_id = new_thread_id()
        with connect(settings.checkpoint_db_path) as connection:
            insert_run(connection, thread_id, user_id, "尚未开始的运行")

        response = client.get(f"/api/runs/{thread_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["result"]["run_status"] == "running"
        assert body["result"]["jobs"] == []


def test_top_level_thread_id_is_rejected(client) -> None:
    response = client.post("/api/runs", json={**_payload(), "thread_id": "client-made"})
    assert response.status_code == 422
    assert ("thread_id", "unexpected_field") in _fields(response)


def test_legacy_field_name_is_rejected(client) -> None:
    job = {"title": "Backend", "jd": "Python"}
    response = client.post("/api/runs", json=_payload([job]))
    assert response.status_code == 422
    fields = _fields(response)
    assert ("jobs[0].jd", "unexpected_field") in fields
    assert ("jobs[0].original_position_text", "missing") in fields


def test_type_error_is_located(client) -> None:
    job = {"title": "Backend", "original_position_text": 42}
    response = client.post("/api/runs", json=_payload([job]))
    assert response.status_code == 422
    assert ("jobs[0].original_position_text", "string_type") in _fields(response)


def test_blank_field_is_located(client) -> None:
    job = {"title": "   ", "original_position_text": "Python"}
    response = client.post("/api/runs", json=_payload([job]))
    assert response.status_code == 422
    assert ("jobs[0].title", "blank") in _fields(response)


def test_multiple_errors_are_returned_together(client) -> None:
    jobs = [{"title": "", "original_position_text": ""} for _ in range(6)]
    response = client.post("/api/runs", json=_payload(jobs, goal="  "))
    assert response.status_code == 422
    fields = _fields(response)
    assert ("goal", "blank") in fields
    assert ("jobs", "too_many_jobs") in fields
    assert ("jobs[0].title", "blank") in fields


def test_six_jobs_rejected_without_thread(client) -> None:
    jobs = [
        {"title": f"Job {index}", "original_position_text": "Python"} for index in range(6)
    ]
    response = client.post("/api/runs", json=_payload(jobs))
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "too_many_jobs"
    assert "thread_id" not in body


def test_job_id_is_generated(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    job = {"title": "Backend Engineer", "original_position_text": "Python"}
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        body = _submit_and_fetch(client, _payload([job]))
        assert body["result"]["jobs"][0]["job_id"] == "job-1"


def test_five_jobs_accepted(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    jobs = [
        {
            "title": f"Role {index}",
            "original_position_text": f"Python role {index}",
        }
        for index in range(5)
    ]
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        body = _submit_and_fetch(client, _payload(jobs))
        assert len(body["result"]["jobs"]) == 5


def test_run_returns_structured_result(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        body = _submit_and_fetch(client, _payload())["result"]
        assert body["run_status"] == "succeeded"
        assert body["thread_id"]
        assert body["advice"]
        job = body["jobs"][0]
        assert job["status"] == "ok"
        assert job["review"]["score"] == 80
        assert job["resume_source"] == "baseline"
        assert job["variants"] == []


def test_unknown_thread_returns_404(client) -> None:
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.post("/api/runs/does-not-exist/resume").status_code == 404
    assert client.get("/api/runs/does-not-exist/snapshots").status_code == 404


def test_unknown_snapshot_returns_404(client) -> None:
    response = client.get("/api/runs/does-not-exist/snapshots/checkpoint-x")
    assert response.status_code == 404
