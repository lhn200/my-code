from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.auth_utils import login, register

JOB = {"job_id": "job-1", "title": "Backend Engineer", "original_position_text": "Python"}


def _error_code(body: Any) -> str:
    return str((body.get("error") or {}).get("code") or "")


def _make_run(client: TestClient) -> str:
    response = client.post(
        "/api/runs",
        json={"goal": "后端", "resume_text": "Python SQL", "jobs": [JOB]},
    )
    assert response.status_code == 200, response.text
    return response.json()["thread_id"]


def _create(client: TestClient, thread_id: str | None = None, title: str | None = None) -> Any:
    payload: dict[str, Any] = {}
    if thread_id is not None:
        payload["thread_id"] = thread_id
    if title is not None:
        payload["title"] = title
    return client.post("/api/coach/sessions", json=payload)


def _send(client: TestClient, session_id: str, text: str) -> Any:
    return client.post(
        f"/api/coach/sessions/{session_id}/messages", json={"content": text}
    )


def test_coach_requires_auth(anon_client: TestClient) -> None:
    assert anon_client.get("/api/coach/sessions").status_code == 401
    assert anon_client.post("/api/coach/sessions", json={}).status_code == 401


def test_create_and_send_unbound(fake_client: TestClient) -> None:
    created = _create(fake_client)
    assert created.status_code == 200, created.text
    body = created.json()
    session_id = body["session"]["id"]
    assert body["session"]["thread_id"] is None
    assert body["session"]["title"] == ""
    assert body["session"]["message_count"] == 0
    assert body["messages"] == []

    sent = _send(fake_client, session_id, "帮我看看简历")
    assert sent.status_code == 200, sent.text
    payload = sent.json()
    assert [item["role"] for item in payload["messages"]] == ["user", "coach"]
    assert payload["session"]["title"] == "帮我看看简历"
    assert payload["session"]["message_count"] == 2

    second = _send(fake_client, session_id, "再具体一点")
    assert second.status_code == 200, second.text
    assert len(second.json()["messages"]) == 4

    messages = fake_client.models.last_messages("coach_chat")
    assert [item[0] for item in messages] == ["system", "human", "ai", "human"]

    stored = fake_client.get(f"/api/coach/sessions/{session_id}")
    assert stored.status_code == 200
    assert len(stored.json()["messages"]) == 4

    listed = fake_client.get("/api/coach/sessions")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [session_id]
    assert items[0]["message_count"] == 4


def test_bound_context_includes_analysis(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    created = _create(fake_client, thread_id=thread_id)
    assert created.status_code == 200, created.text
    session_id = created.json()["session"]["id"]
    assert created.json()["session"]["thread_id"] == thread_id

    sent = _send(fake_client, session_id, "这个岗位还差什么")
    assert sent.status_code == 200, sent.text

    messages = fake_client.models.last_messages("coach_chat")
    human = messages[-1][1]
    assert "Backend Engineer" in human
    assert "review_score" in human
    assert "后端" in human

    missing = _create(fake_client, thread_id="missing-thread")
    assert missing.status_code == 404
    assert _error_code(missing.json()) == "coach_analysis_not_found"


def test_message_validation_and_ownership(fake_client: TestClient) -> None:
    session_id = _create(fake_client).json()["session"]["id"]

    blank = _send(fake_client, session_id, "   ")
    assert blank.status_code == 422
    assert _error_code(blank.json()) == "coach_message_blank"

    limit = fake_client.app.state.settings.max_message_chars
    too_long = _send(fake_client, session_id, "长" * (limit + 1))
    assert too_long.status_code == 422
    assert _error_code(too_long.json()) == "coach_message_too_long"

    register(fake_client, "other@example.com", "password123")
    token = login(fake_client, "other@example.com", "password123")
    fake_client.headers["Authorization"] = f"Bearer {token}"

    assert fake_client.get(f"/api/coach/sessions/{session_id}").status_code == 404
    assert _send(fake_client, session_id, "你好").status_code == 404
    renamed = fake_client.patch(f"/api/coach/sessions/{session_id}", json={"title": "别人的"})
    assert renamed.status_code == 404
    assert fake_client.delete(f"/api/coach/sessions/{session_id}").status_code == 404


def test_rename_rebind_and_delete(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    session_id = _create(fake_client, thread_id=thread_id).json()["session"]["id"]

    renamed = fake_client.patch(
        f"/api/coach/sessions/{session_id}", json={"title": "面试冲刺"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["session"]["title"] == "面试冲刺"

    unbound = fake_client.patch(
        f"/api/coach/sessions/{session_id}", json={"thread_id": None}
    )
    assert unbound.status_code == 200
    assert unbound.json()["session"]["thread_id"] is None

    invalid = fake_client.patch(
        f"/api/coach/sessions/{session_id}", json={"thread_id": "missing-thread"}
    )
    assert invalid.status_code == 404
    assert _error_code(invalid.json()) == "coach_analysis_not_found"

    blank_title = fake_client.patch(
        f"/api/coach/sessions/{session_id}", json={"title": "  "}
    )
    assert blank_title.status_code == 422

    deleted = fake_client.delete(f"/api/coach/sessions/{session_id}")
    assert deleted.status_code == 204
    assert fake_client.get(f"/api/coach/sessions/{session_id}").status_code == 404
    assert fake_client.delete(f"/api/coach/sessions/{session_id}").status_code == 404


def test_model_failure_keeps_messages_retryable(fake_client: TestClient) -> None:
    session_id = _create(fake_client).json()["session"]["id"]
    fake_client.models.models["coach_chat"].handler = lambda _messages: "   "

    failed = _send(fake_client, session_id, "给我建议")
    assert failed.status_code == 502
    assert _error_code(failed.json()) == "coach_reply_failed"

    stored = fake_client.get(f"/api/coach/sessions/{session_id}").json()
    assert stored["messages"] == []
    assert stored["session"]["title"] == ""

    fake_client.models.models["coach_chat"].handler = lambda _messages: "恢复后的建议"
    retried = _send(fake_client, session_id, "给我建议")
    assert retried.status_code == 200, retried.text
    assert [item["role"] for item in retried.json()["messages"]] == ["user", "coach"]
    assert retried.json()["session"]["title"] == "给我建议"


def test_list_filters_by_thread(fake_client: TestClient) -> None:
    thread_id = _make_run(fake_client)
    bound = _create(fake_client, thread_id=thread_id).json()["session"]["id"]
    unbound = _create(fake_client).json()["session"]["id"]

    filtered = fake_client.get("/api/coach/sessions", params={"thread_id": thread_id})
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [bound]

    every = fake_client.get("/api/coach/sessions")
    assert {item["id"] for item in every.json()["items"]} == {bound, unbound}

    unknown = fake_client.get(
        "/api/coach/sessions", params={"thread_id": "missing-thread"}
    )
    assert unknown.status_code == 404
    assert _error_code(unknown.json()) == "coach_analysis_not_found"
