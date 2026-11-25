from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.db import connect, init_db
from app.memory.repository import (
    archive_expired,
    delete_memory,
    set_enabled,
    update_memory,
    upsert_memory,
)
from app.memory.retrieval import (
    INJECTION_MAX_CHARS,
    extract_keywords,
    filter_for_role,
    retrieve_memories,
)
from app.memory.token_budget import count_tokens

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    config = Settings(
        checkpoint_db_path=tmp_path / "career.sqlite3", context_memory_tokens=200
    )
    init_db(config.checkpoint_db_path)
    return config


def write(connection, settings: Settings, content: str, **overrides):
    payload = {
        "user_id": "u1",
        "kind": "fact",
        "content": content,
        "confidence": 0.9,
        "settings": settings,
        "now": NOW,
    }
    payload.update(overrides)
    return upsert_memory(connection, **payload)


def test_extract_keywords_limits_and_bigrams() -> None:
    keywords = extract_keywords("熟悉 Python 与数据分析岗位")
    assert "python" in keywords
    assert "数据" in keywords
    assert len(keywords) <= 8
    assert extract_keywords("") == []


def test_disabled_memory_returns_nothing(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        write(connection, settings, "熟练使用 Python 做数据分析")
        assert retrieve_memories(connection, user_id="u1", query="Python", settings=settings) == []


def test_relevance_ordering(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True, now=NOW)
        best = write(connection, settings, "熟练使用 Python 做数据分析")
        partial = write(connection, settings, "熟悉 Python 开发", now=NOW + timedelta(days=1))
        write(connection, settings, "擅长团队沟通", now=NOW + timedelta(days=2))
        rows = retrieve_memories(
            connection, user_id="u1", query="Python 数据分析", settings=settings, now=NOW
        )
        assert [row["id"] for row in rows][:2] == [best["id"], partial["id"]]


def test_recency_breaks_ties_without_keywords(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True, now=NOW)
        older = write(connection, settings, "旧的事实", now=NOW)
        newer = write(connection, settings, "新的事实", now=NOW + timedelta(days=10))
        rows = retrieve_memories(connection, user_id="u1", query=None, settings=settings, now=NOW)
        assert [row["id"] for row in rows] == [newer["id"], older["id"]]


def test_top_k_and_hard_cap(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True, now=NOW)
        for index in range(10):
            write(connection, settings, f"事实编号 {index}")
        rows = retrieve_memories(connection, user_id="u1", query=None, settings=settings, now=NOW)
        assert len(rows) == settings.memory_top_k
        capped = retrieve_memories(
            connection,
            user_id="u1",
            query=None,
            settings=settings,
            now=NOW,
            top_k=99,
        )
        assert len(capped) == settings.memory_max_top_k


def test_token_budget_clips_items(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True, now=NOW)
        for index in range(6):
            write(connection, settings, f"{index}" + "长内容" * 60)
        rows = retrieve_memories(connection, user_id="u1", query=None, settings=settings, now=NOW)
        assert 0 < len(rows) < 6
        assert sum(count_tokens(row["content"]) for row in rows) <= settings.context_memory_tokens
        assert all(len(row["content"]) <= INJECTION_MAX_CHARS for row in rows)


def test_excludes_pending_archived_expired_deleted_and_other_users(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True, now=NOW)
        kept = write(connection, settings, "保留的长期事实")
        pending = write(connection, settings, "待确认偏好", confidence=0.5)
        archived = write(connection, settings, "已归档事实")
        update_memory(
            connection,
            user_id="u1",
            memory_id=archived["id"],
            settings=settings,
            status="archived",
        )
        expired = write(connection, settings, "会过期事实", now=NOW - timedelta(days=365))
        archive_expired(connection, now=NOW + timedelta(days=1))
        deleted = write(connection, settings, "已删除事实")
        delete_memory(connection, user_id="u1", memory_id=deleted["id"])
        write(connection, settings, "别人的事实", user_id="u2")
        rows = retrieve_memories(connection, user_id="u1", query=None, settings=settings, now=NOW)
        ids = {row["id"] for row in rows}
        assert ids == {kept["id"]}
        assert pending["id"] not in ids and expired["id"] not in ids


def test_fts_path_and_fallback(settings: Settings) -> None:
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True, now=NOW)
        row = write(connection, settings, "proficient in python analytics")
        fts = retrieve_memories(
            connection,
            user_id="u1",
            query="python",
            settings=settings,
            now=NOW,
            fts_enabled=True,
        )
        like = retrieve_memories(
            connection,
            user_id="u1",
            query="python",
            settings=settings,
            now=NOW,
            fts_enabled=False,
        )
        assert [item["id"] for item in fts] == [row["id"]]
        assert [item["id"] for item in like] == [row["id"]]


def test_filter_for_role_whitelist() -> None:
    memories = [
        {"id": "1", "kind": "preference"},
        {"id": "2", "kind": "fact"},
    ]
    assert [item["id"] for item in filter_for_role(memories, "resume_optimizer")] == ["1"]
    assert filter_for_role(memories, "job_analyst") == []
    assert len(filter_for_role(memories, "unknown_role")) == 0
