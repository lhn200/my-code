from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from tests.auth_utils import login, register


class FakeGraph:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = dict(values)
        self.updates: list[dict[str, Any]] = []

    async def aget_state(self, _config: Any) -> Any:
        return SimpleNamespace(values=dict(self.values))

    async def aupdate_state(self, _config: Any, values: dict[str, Any]) -> None:
        self.updates.append(dict(values))
        self.values.update(values)


def make_run(fake_client) -> str:
    response = fake_client.post(
        "/api/runs",
        json={
            "goal": "转数据分析岗",
            "resume_text": "三年运营经验，熟悉 SQL。",
            "jobs": [
                {
                    "title": "数据分析师",
                    "original_position_text": "负责数据分析与报表建设。",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["thread_id"]


def summary_request(fake_client, thread_id: str, expected_version=None):
    body = {} if expected_version is None else {"expected_version": expected_version}
    return fake_client.post(f"/api/sessions/{thread_id}/summary/regenerate", json=body)


def install_state(fake_client, thread_id: str, **overrides) -> FakeGraph:
    state = {
        "thread_id": thread_id,
        "session_turns": [
            {"turn": 1, "user": "我想转数据分析岗", "assistant": "建议先补 SQL 项目"},
            {"turn": 2, "user": "我偏好远程办公", "assistant": "可以优先投远程岗位"},
        ],
        "session_summary": {},
        "session_summary_version": 0,
        "session_summary_updated_at": None,
        "summarized_through_turn": 0,
    }
    state.update(overrides)
    graph = FakeGraph(state)
    fake_client.app.state.graph = graph
    return graph


def summarizer_handler(_messages: Any) -> str:
    return json.dumps(
        {
            "facts": ["用户有三年运营经验"],
            "open_questions": ["期望薪资是多少"],
            "preferences": ["偏好远程办公"],
            "constraints": [],
            "decisions": ["先补充 SQL 项目"],
        },
        ensure_ascii=False,
    )


def test_summary_requires_auth(anon_client) -> None:
    assert anon_client.get("/api/sessions/t1/summary").status_code == 401


def test_summary_cross_user_returns_404(fake_client) -> None:
    thread_id = make_run(fake_client)
    register(fake_client, "other@example.com", "password123")
    token = login(fake_client, "other@example.com", "password123")
    fake_client.headers["Authorization"] = f"Bearer {token}"
    assert fake_client.get(f"/api/sessions/{thread_id}/summary").status_code == 404


def test_summary_empty_state(fake_client) -> None:
    thread_id = make_run(fake_client)
    install_state(fake_client, thread_id, session_turns=[])
    body = fake_client.get(f"/api/sessions/{thread_id}/summary").json()
    assert body["summarized"] is False
    assert body["version"] == 0
    assert body["summary_status"] == "idle"
    assert body["summary"] is None


def test_summary_read_lazily_rolls_when_due(fake_client) -> None:
    thread_id = make_run(fake_client)
    turns = [
        {"turn": number, "user": f"输入{number}", "assistant": f"输出{number}"}
        for number in range(1, 13)
    ]
    graph = install_state(fake_client, thread_id, session_turns=turns)
    fake_client.models.models["summarizer"].handler = summarizer_handler

    body = fake_client.get(f"/api/sessions/{thread_id}/summary").json()

    assert body["summarized"] is True
    assert body["version"] == 1
    assert body["summarized_through_turn"] == 6
    assert body["summary"]["facts"] == ["用户有三年运营经验"]
    assert graph.updates and graph.updates[0]["session_summary_version"] == 1



def test_regenerate_writes_back_and_is_readable(fake_client) -> None:
    thread_id = make_run(fake_client)
    graph = install_state(fake_client, thread_id)
    fake_client.models.models["summarizer"].handler = summarizer_handler

    response = summary_request(fake_client, thread_id, expected_version=0)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["regenerated"] is True
    assert payload["version"] == 1
    assert payload["summarized"] is True
    assert payload["summary"]["facts"] == ["用户有三年运营经验"]
    assert "我想转数据分析岗" not in json.dumps(payload, ensure_ascii=False)
    assert graph.updates and graph.updates[0]["session_summary_version"] == 1

    stored = fake_client.get(f"/api/sessions/{thread_id}/summary").json()
    assert stored["version"] == 1
    assert stored["summary"] == payload["summary"]


def test_regenerate_without_pending_returns_false(fake_client) -> None:
    thread_id = make_run(fake_client)
    graph = install_state(fake_client, thread_id, summarized_through_turn=2)
    fake_client.models.models["summarizer"].handler = summarizer_handler

    response = summary_request(fake_client, thread_id)
    assert response.status_code == 200
    assert response.json()["regenerated"] is False
    assert response.json()["version"] == 0
    assert graph.updates == []


def test_regenerate_conflict(fake_client) -> None:
    thread_id = make_run(fake_client)
    install_state(fake_client, thread_id, session_summary_version=2)
    response = summary_request(fake_client, thread_id, expected_version=0)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "summary_conflict"


def test_regenerate_failure_keeps_old_summary(fake_client) -> None:
    thread_id = make_run(fake_client)
    old_body = {
        "facts": ["旧事实"],
        "open_questions": [],
        "preferences": [],
        "constraints": [],
        "decisions": [],
    }
    install_state(
        fake_client,
        thread_id,
        session_summary=old_body,
        session_summary_version=3,
        summarized_through_turn=0,
    )
    fake_client.models.models["summarizer"].handler = lambda _messages: "not json"

    response = summary_request(fake_client, thread_id)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "summary_failed"

    stored = fake_client.get(f"/api/sessions/{thread_id}/summary").json()
    assert stored["version"] == 3
    assert stored["summary"] == old_body
    assert stored["summary_status"] == "failed"


@pytest.mark.parametrize("bad", ["not json", json.dumps({"facts": ["x"]})])
def test_regenerate_invalid_payload_fails(fake_client, bad: str) -> None:
    thread_id = make_run(fake_client)
    install_state(fake_client, thread_id)
    fake_client.models.models["summarizer"].handler = lambda _messages: bad
    response = summary_request(fake_client, thread_id)
    assert response.status_code == 502
