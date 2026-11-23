from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.db import connect, init_db
from app.db.utils import parse_iso
from app.memory.content import (
    SensitiveContentError,
    content_hash,
    detect_sensitive,
    normalize_content,
)
from app.memory.repository import (
    MemoryNotFound,
    apply_operation,
    archive_expired,
    clear_memories,
    delete_memory,
    get_memory,
    get_settings,
    list_memories,
    recent_by_kind,
    set_enabled,
    update_memory,
    upsert_memory,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    config = Settings(checkpoint_db_path=tmp_path / "career.sqlite3")
    init_db(config.checkpoint_db_path)
    return config


def write(connection, settings: Settings, **overrides):
    payload = {
        "user_id": "u1",
        "kind": "preference",
        "content": "偏好远程办公",
        "confidence": 0.9,
        "settings": settings,
        "now": NOW,
    }
    payload.update(overrides)
    return upsert_memory(connection, **payload)


def test_normalize_and_hash() -> None:
    assert normalize_content("  偏好   远程 \n 办公 ", 200) == "偏好 远程 办公"
    assert normalize_content("x" * 20, 10) == "x" * 10
    with pytest.raises(ValueError):
        normalize_content("   ", 200)
    with pytest.raises(ValueError):
        normalize_content("x" * 20, 10, strict=True)
    assert content_hash("u1", "goal", "转岗") == content_hash("u1", "goal", "转岗")
    assert content_hash("u1", "goal", "转岗") != content_hash("u2", "goal", "转岗")


def test_sensitive_detection() -> None:
    assert detect_sensitive("手机号 13800138000") == "phone"
    assert detect_sensitive("邮箱 a@b.com") == "email"
    assert detect_sensitive("已婚已育") == "marital"
    assert detect_sensitive("民族：汉族") == "ethnicity"
    assert detect_sensitive("偏好远程办公") is None


def test_dedupe_updates_instead_of_inserting(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        first = write(connection, settings, content="  偏好  远程 ")
        assert first["action"] == "created"
        second = write(connection, settings, content="偏好 远程", confidence=0.5)
        assert second["action"] == "updated"
        assert second["id"] == first["id"]
        row = get_memory(connection, "u1", first["id"])
        assert row is not None
        assert row["content"] == "偏好 远程"
        assert row["confidence"] == pytest.approx(0.9)
        assert len(list_memories(connection, "u1")) == 1


def test_ttl_defaults_per_kind(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        fact = write(connection, settings, kind="fact", content="三年数据分析经验")
        goal = write(connection, settings, kind="goal", content="半年内转入数据岗")
        preference = write(connection, settings)
        constraint = write(connection, settings, kind="constraint", content="只考虑上海岗位")
        fact_row = get_memory(connection, "u1", fact["id"])
        goal_row = get_memory(connection, "u1", goal["id"])
        preference_row = get_memory(connection, "u1", preference["id"])
        constraint_row = get_memory(connection, "u1", constraint["id"])
        assert fact_row["expires_at"] == (NOW + timedelta(days=180)).isoformat()
        assert goal_row["expires_at"] == (NOW + timedelta(days=365)).isoformat()
        assert preference_row["expires_at"] is None
        assert constraint_row["expires_at"] is None


def test_confidence_tiers_and_sensitive_rejection(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        pending = write(connection, settings, content="可能偏好外企", confidence=0.5)
        assert pending["status"] == "pending_confirmation"
        discarded = write(connection, settings, content="低置信度内容", confidence=0.2)
        assert discarded["action"] == "discarded"
        with pytest.raises(SensitiveContentError):
            write(connection, settings, content="手机 13800138000")


def test_conflict_update_requires_larger_confidence(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        created = write(connection, settings, content="偏好大厂", confidence=0.7)
        weak = apply_operation(
            connection,
            user_id="u1",
            candidate={
                "op": "update",
                "target_id": created["id"],
                "kind": "preference",
                "content": "偏好创业公司",
                "confidence": 0.75,
            },
            settings=settings,
            now=NOW,
        )
        assert weak["action"] == "skipped"
        strong = apply_operation(
            connection,
            user_id="u1",
            candidate={
                "op": "update",
                "target_id": created["id"],
                "kind": "preference",
                "content": "偏好创业公司",
                "confidence": 0.85,
            },
            settings=settings,
            now=NOW,
        )
        assert strong["action"] == "updated"
        assert get_memory(connection, "u1", created["id"])["content"] == "偏好创业公司"


def test_operation_skip_and_missing_target(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        assert (
            apply_operation(
                connection, user_id="u1", candidate={"op": "skip"}, settings=settings
            )["action"]
            == "skipped"
        )
        missing = apply_operation(
            connection,
            user_id="u1",
            candidate={
                "op": "update",
                "target_id": "nope",
                "kind": "goal",
                "content": "新目标",
                "confidence": 0.9,
            },
            settings=settings,
        )
        assert missing["reason"] == "missing_target"


def test_list_filters_and_archive(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        active = write(connection, settings, content="偏好远程")
        archived = write(connection, settings, content="目标是数据岗", kind="goal")
        update_memory(
            connection,
            user_id="u1",
            memory_id=archived["id"],
            settings=settings,
            status="archived",
        )
        assert [row["id"] for row in list_memories(connection, "u1")] == [active["id"]]
        assert [row["id"] for row in list_memories(connection, "u1", status="archived")] == [
            archived["id"]
        ]
        assert list_memories(connection, "u1", q="远程")[0]["id"] == active["id"]
        assert list_memories(connection, "u1", kind="goal") == []


def test_expiry_archives_and_hides(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        row = write(connection, settings, kind="fact", content="两年经验")
        later = NOW + timedelta(days=181)
        assert list_memories(connection, "u1", now=later) == []
        assert archive_expired(connection, now=later) == 1
        archived = list_memories(connection, "u1", status="archived", now=later)
        assert [item["id"] for item in archived] == [row["id"]]
        assert archived[0]["archived_reason"] == "ttl"


def test_update_refreshes_expiry(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        row = write(connection, settings, kind="fact", content="旧经验")
        later = NOW + timedelta(days=10)
        updated = update_memory(
            connection,
            user_id="u1",
            memory_id=row["id"],
            content="新经验",
            settings=settings,
            now=later,
        )
        assert parse_iso(updated["expires_at"]) == later + timedelta(
            days=settings.memory_ttl_days_fact
        )
        assert parse_iso(updated["updated_at"]) == later


def test_cli_expire_archives_ttl_rows(
    settings: Settings, monkeypatch, capsys
) -> None:
    from app.memory import cli

    with connect(settings.checkpoint_db_path) as connection:
        write(connection, settings, kind="fact", content="两年经验")
    monkeypatch.setattr(cli, "Settings", lambda: settings)

    code = cli.main(["expire", "--now", (NOW + timedelta(days=181)).isoformat()])

    assert code == 0
    assert "archived 1 expired memories" in capsys.readouterr().out


def test_delete_is_tombstone_and_idempotent(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        row = write(connection, settings)
        assert delete_memory(connection, user_id="u1", memory_id=row["id"]) == 1
        assert delete_memory(connection, user_id="u1", memory_id=row["id"]) == 0
        tombstone = get_memory(connection, "u1", row["id"], include_deleted=True)
        assert tombstone["content"] == ""
        assert tombstone["content_hash"] == ""
        assert tombstone["deleted_at"] is not None
        assert get_memory(connection, "u1", row["id"]) is None
        with pytest.raises(MemoryNotFound):
            delete_memory(connection, user_id="u2", memory_id=row["id"])


def test_clear_memories_counts_only_live_rows(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        write(connection, settings, content="偏好一")
        second = write(connection, settings, content="偏好二")
        delete_memory(connection, user_id="u1", memory_id=second["id"])
        assert clear_memories(connection, user_id="u1") == 1
        assert list_memories(connection, "u1") == []


def test_settings_default_off_and_upsert(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        assert get_settings(connection, "u1", default_enabled=False)["enabled"] is False
        set_enabled(connection, "u1", True, now=NOW)
        assert get_settings(connection, "u1")["enabled"] is True
        set_enabled(connection, "u1", False, now=NOW)
        assert get_settings(connection, "u1")["enabled"] is False


def test_recent_by_kind_returns_latest_active(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        older = write(connection, settings, kind="goal", content="旧目标", now=NOW)
        newer = write(
            connection,
            settings,
            kind="goal",
            content="新目标",
            now=NOW + timedelta(days=1),
        )
        write(connection, settings, kind="fact", content="事实")
        rows = recent_by_kind(connection, user_id="u1", kind="goal", limit=5)
        assert [row["id"] for row in rows] == [newer["id"], older["id"]]
