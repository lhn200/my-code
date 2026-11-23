from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db import connect, init_db
from app.memory.pipeline import MemoryWritePipeline, ModelMemoryExtractor
from app.memory.repository import get_memory, list_memories, set_enabled, upsert_memory
from app.memory.retrieval import retrieve_memories
from tests.fakes import FakeModels, make_context


def candidate(**overrides):
    payload = {
        "op": "add",
        "kind": "goal",
        "content": "半年内转入数据分析岗位",
        "confidence": 0.9,
        "target_id": None,
    }
    payload.update(overrides)
    return payload


def handler_for(candidates):
    def handler(_messages):
        return json.dumps({"candidates": candidates}, ensure_ascii=False)

    return handler


def build(tmp_path: Path, candidates, *, delays=()):
    settings = Settings(checkpoint_db_path=tmp_path / "career.sqlite3")
    init_db(settings.checkpoint_db_path)
    context, models = make_context(
        settings, {"memory_extractor": handler_for(candidates)}
    )
    pipeline = MemoryWritePipeline(
        settings, ModelMemoryExtractor(context), retry_delays=delays
    )
    return settings, models, pipeline


def state(status: str = "succeeded") -> dict:
    return {
        "goal": "转数据岗",
        "run_status": status,
        "advice": "建议补充 SQL 项目",
        "session_summary": {"facts": ["目前做运营"]},
        "jobs": [
            {
                "title": "数据分析师",
                "status": "ok",
                "review": {"score": 72, "missing": ["SQL"]},
            }
        ],
    }


async def test_disabled_memory_skips_extraction(tmp_path: Path) -> None:
    settings, models, pipeline = build(tmp_path, [candidate()])
    result = await pipeline.run(user_id="u1", thread_id="t1", state=state())
    assert result == {"written": 0, "skipped": "disabled"}
    assert models.calls("memory_extractor") == 0


async def test_completed_run_writes_at_most_five(tmp_path: Path) -> None:
    candidates = [
        candidate(content=f"稳定事实 {index}", kind="fact") for index in range(6)
    ]
    settings, models, pipeline = build(tmp_path, candidates)
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True)
    result = await pipeline.run(user_id="u1", thread_id="t1", state=state())
    assert result["written"] == 5
    with connect(settings.checkpoint_db_path) as connection:
        rows = list_memories(connection, "u1")
    assert len(rows) == 5
    assert models.calls("memory_extractor") == 1


async def test_low_confidence_and_pending_are_not_retrievable(tmp_path: Path) -> None:
    candidates = [
        candidate(content="低置信度目标", confidence=0.2),
        candidate(content="可能是偏好", kind="preference", confidence=0.5),
        candidate(content="确定目标", confidence=0.9),
    ]
    settings, models, pipeline = build(tmp_path, candidates)
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True)
    result = await pipeline.run(user_id="u1", thread_id="t1", state=state())
    assert result["written"] == 2
    with connect(settings.checkpoint_db_path) as connection:
        listed = list_memories(connection, "u1")
        pending = list_memories(connection, "u1", status="pending_confirmation")
        retrieved = retrieve_memories(
            connection, user_id="u1", query=None, settings=settings
        )
    assert {row["content"] for row in listed} == {"确定目标", "可能是偏好"}
    assert [row["content"] for row in pending] == ["可能是偏好"]
    assert [row["content"] for row in retrieved] == ["确定目标"]


async def test_sensitive_candidate_is_rejected(tmp_path: Path) -> None:
    settings, models, pipeline = build(
        tmp_path, [candidate(content="手机号 13800138000", kind="fact")]
    )
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True)
    result = await pipeline.run(user_id="u1", thread_id="t1", state=state())
    assert result["rejected"] == 1
    with connect(settings.checkpoint_db_path) as connection:
        assert list_memories(connection, "u1") == []


async def test_failed_run_does_not_extract(tmp_path: Path) -> None:
    settings, models, pipeline = build(tmp_path, [candidate()])
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True)
    result = await pipeline.run(user_id="u1", thread_id="t1", state=state("failed"))
    assert result == {"written": 0, "skipped": "run_status"}
    assert models.calls("memory_extractor") == 0


async def test_extractor_failure_is_contained(tmp_path: Path) -> None:
    settings = Settings(checkpoint_db_path=tmp_path / "career.sqlite3")
    init_db(settings.checkpoint_db_path)

    def boom(_messages):
        raise RuntimeError("provider down")

    context, models = make_context(settings, {"memory_extractor": boom})
    pipeline = MemoryWritePipeline(
        settings, ModelMemoryExtractor(context), retry_delays=(0, 0)
    )
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True)
    result = await pipeline.run(user_id="u1", thread_id="t1", state=state())
    assert result["failed"] is True
    assert models.calls("memory_extractor") == 3


async def test_update_operation_uses_target_id(tmp_path: Path) -> None:
    settings, models, pipeline = build(tmp_path, [])
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True)
        existing = upsert_memory(
            connection,
            user_id="u1",
            kind="goal",
            content="想转产品岗",
            confidence=0.5,
            settings=settings,
        )
    candidates = [
        candidate(
            op="update",
            kind="goal",
            content="想转数据分析岗",
            confidence=0.95,
            target_id=existing["id"],
        )
    ]
    pipeline = MemoryWritePipeline(
        settings,
        ModelMemoryExtractor(context_for(settings, candidates)),
        retry_delays=(),
    )
    result = await pipeline.run(user_id="u1", thread_id="t1", state=state())
    assert result["written"] == 1
    with connect(settings.checkpoint_db_path) as connection:
        row = get_memory(connection, "u1", existing["id"])
        assert row["content"] == "想转数据分析岗"
        assert row["status"] == "active"
        active = retrieve_memories(
            connection, user_id="u1", query=None, settings=settings
        )
        assert [item["id"] for item in active] == [existing["id"]]


def context_for(settings: Settings, candidates):
    context, _models = make_context(
        settings, {"memory_extractor": handler_for(candidates)}
    )
    return context


def test_fake_models_has_all_roles() -> None:
    models = FakeModels({})
    assert set(models.models) >= {"summarizer", "memory_extractor", "interviewer"}
