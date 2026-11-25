from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import Settings
from tests.auth_utils import login, register


def _payload(goal: str = "寻找后端岗位") -> dict:
    return {
        "goal": goal,
        "resume_text": "Python developer with SQL experience",
        "jobs": [
            {
                "job_id": "job-1",
                "title": "Backend Engineer",
                "original_position_text": "需要 Python 与 SQL",
            }
        ],
    }


def _create(client, goal: str = "寻找后端岗位") -> str:
    response = client.post("/api/runs", json=_payload(goal))
    assert response.status_code == 200, response.text
    return response.json()["thread_id"]


def _checkpoint_rows(settings: Settings, thread_id: str) -> int:
    with sqlite3.connect(settings.checkpoint_db_path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]


def test_sessions_are_listed_with_title_and_status(fake_client) -> None:
    thread_id = _create(fake_client)
    body = fake_client.get("/api/sessions").json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    item = body["items"][0]
    assert item["thread_id"] == thread_id
    assert item["status"] == "completed"
    assert item["deleted_at"] is None


def test_sessions_are_isolated_between_users(fake_client) -> None:
    thread_id = _create(fake_client)
    register(fake_client, "other@example.com", "password456")
    other = {"Authorization": f"Bearer {login(fake_client, 'other@example.com', 'password456')}"}

    assert fake_client.get(f"/api/runs/{thread_id}", headers=other).status_code == 404
    assert fake_client.get("/api/sessions", headers=other).json()["total"] == 0
    assert fake_client.delete(f"/api/sessions/{thread_id}", headers=other).status_code == 404
    assert fake_client.get(f"/api/sessions/{thread_id}/snapshots", headers=other).status_code == 404
    assert fake_client.post(f"/api/sessions/{thread_id}/restore", headers=other).status_code == 404


def test_rename_and_search(fake_client) -> None:
    thread_id = _create(fake_client)
    renamed = fake_client.patch(
        f"/api/sessions/{thread_id}", json={"title": "My Backend Search"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "My Backend Search"

    assert fake_client.get("/api/sessions", params={"q": "backend"}).json()["total"] == 1
    assert fake_client.get("/api/sessions", params={"q": "missing"}).json()["total"] == 0
    assert fake_client.get("/api/sessions", params={"q": "%"}).json()["total"] == 0


def test_blank_title_and_oversized_page_size_are_422(fake_client) -> None:
    thread_id = _create(fake_client)
    blank = fake_client.patch(f"/api/sessions/{thread_id}", json={"title": "   "})
    assert blank.status_code == 422
    assert blank.json()["error"]["fields"][0]["field"] == "title"

    too_long = fake_client.patch(f"/api/sessions/{thread_id}", json={"title": "x" * 101})
    assert too_long.status_code == 422
    assert too_long.json()["error"]["fields"][0]["type"] == "too_long"

    oversized = fake_client.get("/api/sessions", params={"page_size": 101})
    assert oversized.status_code == 422


def test_pagination(fake_client) -> None:
    _create(fake_client, "第一个岗位")
    _create(fake_client, "第二个岗位")
    page = fake_client.get("/api/sessions", params={"page": 2, "page_size": 1}).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_trash_restore_and_purge(fake_client, settings) -> None:
    thread_id = _create(fake_client)
    assert _checkpoint_rows(settings, thread_id) > 0

    assert fake_client.delete(f"/api/sessions/{thread_id}").status_code == 204
    assert fake_client.get(f"/api/runs/{thread_id}").status_code == 404
    assert fake_client.post(f"/api/runs/{thread_id}/resume").status_code == 404
    assert fake_client.get("/api/sessions").json()["total"] == 0
    trashed = fake_client.get("/api/sessions", params={"trashed": True}).json()
    assert trashed["total"] == 1
    assert trashed["items"][0]["deleted_at"] is not None

    # deleting twice stays idempotent
    assert fake_client.delete(f"/api/sessions/{thread_id}").status_code == 204

    restored = fake_client.post(f"/api/sessions/{thread_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert fake_client.get(f"/api/runs/{thread_id}").status_code == 200
    again = fake_client.post(f"/api/sessions/{thread_id}/restore")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "not_trashed"

    assert fake_client.delete(f"/api/sessions/{thread_id}").status_code == 204
    assert fake_client.delete(f"/api/sessions/{thread_id}/purge").status_code == 204
    assert _checkpoint_rows(settings, thread_id) == 0
    assert fake_client.get(f"/api/runs/{thread_id}").status_code == 404


def test_purge_requires_trash(fake_client) -> None:
    thread_id = _create(fake_client)
    response = fake_client.delete(f"/api/sessions/{thread_id}/purge")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_trashed"


def test_purge_failure_keeps_session(monkeypatch, fake_client) -> None:
    import app.api.sessions as sessions_api

    thread_id = _create(fake_client)
    assert fake_client.delete(f"/api/sessions/{thread_id}").status_code == 204

    def _boom(db_path, target):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(sessions_api, "purge_thread", _boom)
    response = fake_client.delete(f"/api/sessions/{thread_id}/purge")
    assert response.status_code == 500
    assert fake_client.get("/api/sessions", params={"trashed": True}).json()["total"] == 1


def test_end_to_end_account_and_session_flow(fake_client) -> None:
    # 首个用户创建并重命名会话
    thread_id = _create(fake_client)
    fake_client.patch(f"/api/sessions/{thread_id}", json={"title": "我的后端岗位"})
    assert fake_client.get("/api/sessions").json()["total"] == 1

    # 第二个用户看不到、也访问不到
    register(fake_client, "second@example.com", "password456")
    other = {"Authorization": f"Bearer {login(fake_client, 'second@example.com', 'password456')}"}
    assert fake_client.get("/api/sessions", headers=other).json()["total"] == 0
    assert fake_client.get(f"/api/runs/{thread_id}", headers=other).status_code == 404

    # 软删除 → 回收站 → 恢复 → 再删除 → 永久删除
    assert fake_client.delete(f"/api/sessions/{thread_id}").status_code == 204
    assert fake_client.get("/api/sessions").json()["total"] == 0
    assert fake_client.get("/api/sessions", params={"trashed": True}).json()["total"] == 1
    assert fake_client.post(f"/api/sessions/{thread_id}/restore").status_code == 200
    assert fake_client.get("/api/sessions").json()["total"] == 1
    assert fake_client.delete(f"/api/sessions/{thread_id}").status_code == 204
    assert fake_client.delete(f"/api/sessions/{thread_id}/purge").status_code == 204
    assert fake_client.get(f"/api/runs/{thread_id}").status_code == 404
    assert fake_client.get("/api/sessions", params={"trashed": True}).json()["total"] == 0


def test_unknown_session_operations_are_404(fake_client) -> None:
    assert fake_client.patch("/api/sessions/nope", json={"title": "x"}).status_code == 404
    assert fake_client.delete("/api/sessions/nope").status_code == 404
    assert fake_client.post("/api/sessions/nope/restore").status_code == 404
    assert fake_client.delete("/api/sessions/nope/purge").status_code == 404
