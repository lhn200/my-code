from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.db import connect
from app.memory.repository import archive_expired, upsert_memory

from tests.auth_utils import DEFAULT_EMAIL

NOW = datetime.now(timezone.utc)


def current_user_id(settings: Settings) -> str:
    with connect(settings.checkpoint_db_path) as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE email = ?", (DEFAULT_EMAIL,)
        ).fetchone()
    return row["id"]


def seed(settings: Settings, user_id: str, content: str, **overrides):
    payload = {
        "user_id": user_id,
        "kind": "preference",
        "content": content,
        "confidence": 0.9,
        "settings": settings,
        "now": NOW,
    }
    payload.update(overrides)
    with connect(settings.checkpoint_db_path) as connection:
        return upsert_memory(connection, **payload)


def test_memories_require_auth(anon_client) -> None:
    assert anon_client.get("/api/memories").status_code == 401
    assert anon_client.get("/api/memories/settings").status_code == 401


def test_empty_memory_list(client) -> None:
    response = client.get("/api/memories")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_list_filters_and_enum_validation(client, settings: Settings) -> None:
    user = current_user_id(settings)
    preference = seed(settings, user, "偏好远程办公")
    fact = seed(settings, user, "三年数据分析经验", kind="fact")
    assert client.get("/api/memories").json()["total"] == 2
    assert [item["id"] for item in client.get("/api/memories?kind=preference").json()["items"]] == [
        preference["id"]
    ]
    assert [item["id"] for item in client.get("/api/memories?q=数据").json()["items"]] == [fact["id"]]
    assert client.get("/api/memories?status=active").json()["total"] == 2
    assert client.get("/api/memories?status=bogus").status_code == 422
    assert client.get("/api/memories?limit=500").status_code == 422


def test_patch_edit_and_sensitive_rejection(client, settings: Settings) -> None:
    user = current_user_id(settings)
    row = seed(settings, user, "偏好大厂")
    updated = client.patch(f"/api/memories/{row['id']}", json={"content": "偏好外企"})
    assert updated.status_code == 200
    assert updated.json()["content"] == "偏好外企"

    sensitive = client.patch(
        f"/api/memories/{row['id']}", json={"content": "手机 13800138000"}
    )
    assert sensitive.status_code == 422
    assert sensitive.json()["error"]["code"] == "sensitive_content"

    assert client.patch(f"/api/memories/{row['id']}", json={}).status_code == 422
    assert client.patch("/api/memories/missing", json={"content": "x"}).status_code == 404


def test_patch_confirm_and_archive(client, settings: Settings) -> None:
    user = current_user_id(settings)
    row = seed(settings, user, "可能偏好外企", confidence=0.5)
    assert client.get("/api/memories?status=pending_confirmation").json()["total"] == 1
    confirmed = client.patch(f"/api/memories/{row['id']}", json={"status": "active"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "active"

    archived = client.patch(f"/api/memories/{row['id']}", json={"status": "archived"})
    assert archived.json()["archived_reason"] == "user"
    assert client.get("/api/memories").json()["total"] == 0
    assert client.get("/api/memories?status=archived").json()["total"] == 1


def test_delete_is_idempotent_and_user_scoped(client, settings: Settings) -> None:
    user = current_user_id(settings)
    row = seed(settings, user, "偏好远程")
    foreign = seed(settings, "someone-else", "别人的记忆")
    assert client.delete(f"/api/memories/{foreign['id']}").status_code == 404
    assert client.delete(f"/api/memories/{row['id']}").status_code == 204
    assert client.delete(f"/api/memories/{row['id']}").status_code == 204
    assert client.get("/api/memories").json()["total"] == 0


def test_clear_returns_deleted_count(client, settings: Settings) -> None:
    user = current_user_id(settings)
    seed(settings, user, "偏好一")
    seed(settings, user, "偏好二")
    seed(settings, user, "目标", kind="goal")
    response = client.delete("/api/memories")
    assert response.status_code == 200
    assert response.json() == {"deleted": 3}
    assert client.get("/api/memories").json()["total"] == 0


def test_settings_default_off_and_persisted(client) -> None:
    assert client.get("/api/memories/settings").json()["enabled"] is False
    assert client.put("/api/memories/settings", json={"enabled": True}).status_code == 200
    assert client.get("/api/memories/settings").json()["enabled"] is True
    assert client.put("/api/memories/settings", json={"enabled": "yes"}).status_code == 422


def test_expired_memory_hidden_but_archived_visible(client, settings: Settings) -> None:
    user = current_user_id(settings)
    expired = seed(
        settings,
        user,
        "会过期的经验",
        kind="fact",
        now=datetime.now(timezone.utc) - timedelta(days=365),
    )
    with connect(settings.checkpoint_db_path) as connection:
        archive_expired(connection, now=NOW)
    assert client.get("/api/memories").json()["total"] == 0
    archived = client.get("/api/memories?status=archived").json()["items"]
    assert [item["id"] for item in archived] == [expired["id"]]
    assert archived[0]["archived_reason"] == "ttl"


def test_cross_user_isolation(client, settings: Settings) -> None:
    seed(settings, "someone-else", "不属于当前用户的记忆")
    assert client.get("/api/memories").json()["total"] == 0
