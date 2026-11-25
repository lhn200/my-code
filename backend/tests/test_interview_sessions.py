from __future__ import annotations

import json
from typing import Any, Callable

from fastapi.testclient import TestClient

from tests.auth_utils import login, register
from tests.fakes import json_block

JOB = {"job_id": "job-1", "title": "Backend Engineer", "original_position_text": "Python"}


def _required_choice_error(body: Any) -> str:
    return str((body.get("error") or {}).get("code") or "")


def _make_run(client: TestClient) -> str:
    response = client.post(
        "/api/runs",
        json={"goal": "后端", "resume_text": "Python SQL", "jobs": [JOB]},
    )
    assert response.status_code == 200, response.text
    return response.json()["thread_id"]


def make_questioner(followup_first: bool = False) -> Callable[[Any], str]:
    def handler(messages: Any) -> str:
        human = messages[-1][1]
        meta = json_block(human, "INTERVIEW_SESSION_META_JSON") or {}
        transcript = json_block(human, "INTERVIEW_TRANSCRIPT_JSON") or []
        if not transcript:
            return json.dumps(
                {
                    "feedback": "",
                    "score": None,
                    "done": False,
                    "next_question": "请介绍你最近负责的项目。",
                    "dimension": "projects",
                    "focus": "项目",
                    "is_followup": False,
                },
                ensure_ascii=False,
            )
        followup = followup_first and len(transcript) == 1
        asked = int(meta.get("asked_count", 1))
        question = (
            "请补充该项目的量化结果。"
            if followup
            else f"请说明你在第 {asked + 1} 个问题上的相关经验。"
        )
        return json.dumps(
            {
                "feedback": "回答结构清晰，但缺少量化结果。",
                "score": 78,
                "done": False,
                "next_question": question,
                "dimension": "experience",
                "focus": "经历",
                "is_followup": followup,
            },
            ensure_ascii=False,
        )

    return handler


def evaluator_handler(_messages: Any) -> str:
    return json.dumps(
        {
            "overall_score": 76,
            "dimension_averages": {
                "skills": 78,
                "experience": 74,
                "projects": 75,
                "education": 80,
            },
            "highlights": ["项目描述具体"],
            "red_flags": ["部分回答缺少量化指标"],
            "improvements": ["补充结果数据"],
            "requirement_gaps": ["Kubernetes"],
        },
        ensure_ascii=False,
    )


def _install(client: TestClient, followup_first: bool = False) -> None:
    client.models.models["interview_questioner"].handler = make_questioner(followup_first)
    client.models.models["interview_evaluator"].handler = evaluator_handler


def _create(client: TestClient, thread_id: str, job_id: str = "job-1") -> Any:
    return client.post(
        "/api/interviews", json={"thread_id": thread_id, "job_id": job_id}
    )


def _answer(client: TestClient, session_id: str, text: str) -> Any:
    return client.post(f"/api/interviews/{session_id}/answers", json={"answer": text})


def test_interview_requires_auth(anon_client: TestClient) -> None:
    assert anon_client.get("/api/interviews/abc").status_code == 401
    assert anon_client.post("/api/interviews", json={}).status_code in (401, 422)


def test_create_answer_finish_flow(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    _install(fake_client)

    created = _create(fake_client, thread_id)
    assert created.status_code == 200, created.text
    body = created.json()
    session_id = body["session"]["id"]
    assert body["session"]["status"] == "active"
    assert body["session"]["asked_count"] == 1
    assert body["session"]["planned_count"] == 5
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "interviewer"
    assert body["messages"][0]["kind"] == "question"

    reused = _create(fake_client, thread_id)
    assert reused.status_code == 200
    assert reused.json()["session"]["id"] == session_id
    assert fake_client.models.calls("interview_questioner") == 1

    for index in range(1, 6):
        response = _answer(fake_client, session_id, f"这是第 {index} 题的回答，包含具体做法。")
        assert response.status_code == 200, response.text
        payload = response.json()
        if index < 5:
            assert payload["session"]["status"] == "active"
            assert payload["session"]["asked_count"] == index + 1
            assert payload["messages"][-1]["role"] == "interviewer"
            assert payload["messages"][-1]["kind"] == "question"
        else:
            assert payload["session"]["status"] == "ready_to_finish"
            assert payload["messages"][-1]["kind"] == "feedback"

    finished = fake_client.post(f"/api/interviews/{session_id}/finish")
    assert finished.status_code == 200, finished.text
    payload = finished.json()
    assert payload["session"]["status"] == "completed"
    assert payload["report"]["source"] == "practice"
    assert payload["report"]["session_id"] == session_id
    assert payload["report"]["status"] == "completed"
    assert payload["report"]["answered_count"] == 5
    assert payload["report"]["planned_count"] == 5
    assert payload["report"]["overall_score"] == 76

    run_result = fake_client.get(f"/api/runs/{thread_id}").json()["result"]
    stored = run_result["interview_reports"]["job-1"]
    assert stored["source"] == "practice"
    assert stored["session_id"] == session_id
    assert stored["interview_thread_id"] == f"practice-{session_id}"

    again = fake_client.post(f"/api/interviews/{session_id}/finish")
    assert again.status_code == 200
    assert again.json()["report"] == payload["report"]
    assert fake_client.models.calls("interview_evaluator") == 1

    closed = _answer(fake_client, session_id, "还能继续吗")
    assert closed.status_code == 409
    assert _required_choice_error(closed.json()) == "interview_closed"


def test_followup_is_limited_per_question(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    _install(fake_client, followup_first=True)
    session_id = _create(fake_client, thread_id).json()["session"]["id"]

    first = _answer(fake_client, session_id, "我负责了一个数据平台项目。")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["messages"][-1]["kind"] == "followup"
    assert payload["session"]["followups_used"] == 1
    assert payload["session"]["current_question_no"] == 1

    second = _answer(fake_client, session_id, "平台支撑了每日千万级请求。")
    assert second.status_code == 200, second.text
    payload = second.json()
    assert payload["messages"][-1]["kind"] == "question"
    assert payload["session"]["current_question_no"] == 2
    assert payload["session"]["asked_count"] == 2
    assert payload["session"]["followups_used"] == 0


def test_answer_and_finish_validation(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    _install(fake_client)
    session_id = _create(fake_client, thread_id).json()["session"]["id"]

    blank = _answer(fake_client, session_id, "   ")
    assert blank.status_code == 422

    too_long = _answer(fake_client, session_id, "长" * 2001)
    assert too_long.status_code == 422
    assert _required_choice_error(too_long.json()) == "interview_answer_too_long"

    no_answers = fake_client.post(f"/api/interviews/{session_id}/finish")
    assert no_answers.status_code == 422
    assert _required_choice_error(no_answers.json()) == "interview_no_answers"

    unknown_job = _create(fake_client, thread_id, job_id="job-missing")
    assert unknown_job.status_code == 422
    assert _required_choice_error(unknown_job.json()) == "interview_job_not_ready"

    register(fake_client, "other@example.com", "password123")
    token = login(fake_client, "other@example.com", "password123")
    fake_client.headers["Authorization"] = f"Bearer {token}"
    assert fake_client.get(f"/api/interviews/{session_id}").status_code == 404
    assert fake_client.post(f"/api/interviews/{session_id}/finish").status_code == 404


def test_questioner_failure_keeps_session_retryable(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    _install(fake_client)
    session_id = _create(fake_client, thread_id).json()["session"]["id"]

    fake_client.models.models["interview_questioner"].handler = lambda _messages: "not json"
    failed = _answer(fake_client, session_id, "我的回答")
    assert failed.status_code == 502
    assert _required_choice_error(failed.json()) == "interview_generation_failed"

    stored = fake_client.get(f"/api/interviews/{session_id}").json()
    assert len(stored["messages"]) == 1
    assert stored["session"]["asked_count"] == 1

    fake_client.models.models["interview_questioner"].handler = make_questioner()
    retried = _answer(fake_client, session_id, "我的回答")
    assert retried.status_code == 200


def test_evaluator_failure_keeps_ready_state(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    _install(fake_client)
    session_id = _create(fake_client, thread_id).json()["session"]["id"]

    for index in range(5):
        assert _answer(fake_client, session_id, f"回答 {index}").status_code == 200

    fake_client.models.models["interview_evaluator"].handler = lambda _messages: "not json"
    failed = fake_client.post(f"/api/interviews/{session_id}/finish")
    assert failed.status_code == 502
    assert _required_choice_error(failed.json()) == "interview_report_failed"

    stored = fake_client.get(f"/api/interviews/{session_id}").json()
    assert stored["session"]["status"] == "ready_to_finish"
    assert stored["report"] is None

    fake_client.models.models["interview_evaluator"].handler = evaluator_handler
    retried = fake_client.post(f"/api/interviews/{session_id}/finish")
    assert retried.status_code == 200
    assert retried.json()["session"]["status"] == "completed"


def test_list_sessions_for_run(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    _install(fake_client)
    session_id = _create(fake_client, thread_id).json()["session"]["id"]

    listed = fake_client.get("/api/interviews", params={"thread_id": thread_id})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["session"]["id"] for item in items] == [session_id]
    assert listed.json()["items"][0]["messages"]
