from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.db import init_db
from app.memory.session_memory import (
    SUMMARY_KEYS,
    SessionMemoryProjection,
    SessionMemoryService,
    SessionNotFound,
    SummaryConflict,
    SummaryFailed,
)
from app.memory.session_store import InMemorySessionStateStore

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW_ISO = "2026-01-01T00:00:00+00:00"
BODY = {
    "facts": ["目标岗位偏数据方向"],
    "open_questions": ["是否接受线上面试"],
    "preferences": ["偏好远程"],
    "constraints": ["三个月内转岗"],
    "decisions": ["优先投递数据岗位"],
}


class FakeSummarizer:
    def __init__(self, result=None, error=None, on_call=None, sleep=0.0) -> None:
        self.result = result
        self.error = error
        self.on_call = on_call
        self.sleep = sleep
        self.calls: list[tuple[dict | None, list[int]]] = []

    def summarize(self, existing, turns):
        self.calls.append((dict(existing) if existing else None, [int(t["turn"]) for t in turns]))
        if self.on_call is not None:
            self.on_call()
        if self.sleep:
            time.sleep(self.sleep)
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return {key: list(value) for key, value in BODY.items()}


def turn(number: int) -> dict:
    return {
        "turn": number,
        "role": "user" if number % 2 else "assistant",
        "content": f"第 {number} 轮内容",
        "created_at": NOW_ISO,
    }


def state_with(
    turns: list[dict],
    summary: dict | None = None,
    version: int = 0,
    through: int = 0,
) -> dict:
    return {
        "session_turns": turns,
        "session_summary": summary,
        "session_summary_version": version,
        "session_summary_updated_at": NOW_ISO if summary else None,
        "summarized_through_turn": through,
        "memory_context": [],
    }


def build_service(
    store: InMemorySessionStateStore,
    settings: Settings,
    summarizer: FakeSummarizer,
    projection: SessionMemoryProjection | None = None,
) -> SessionMemoryService:
    return SessionMemoryService(
        store=store,
        summarizer=summarizer,
        settings=settings,
        projection=projection,
        retry_delays=(0.0, 0.0),
        clock=lambda: NOW,
    )


@pytest.fixture
def projection(settings: Settings) -> SessionMemoryProjection:
    init_db(settings.checkpoint_db_path)
    return SessionMemoryProjection(settings.checkpoint_db_path)


def test_get_summary_without_summary(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1), turn(2)]))
    service = build_service(store, settings, FakeSummarizer())

    view = service.get_summary("t1", "u1")

    assert view.summarized is False
    assert view.version == 0
    assert view.summarized_through_turn == 0
    assert view.summary_status == "idle"
    assert view.summary is None
    assert view.updated_at is None


def test_get_summary_returns_structured_body_only(
    settings: Settings, projection: SessionMemoryProjection
) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)], summary=BODY, version=2, through=12))
    service = build_service(store, settings, FakeSummarizer(), projection)

    view = service.get_summary("t1", "u1")

    assert view.summarized is True
    assert view.version == 2
    assert view.summarized_through_turn == 12
    assert view.summary_status == "ok"
    assert view.summary is not None
    assert set(view.summary) == set(SUMMARY_KEYS)
    assert "第 1 轮内容" not in str(view.summary)

    row = projection.get("t1")
    assert row is not None
    assert (row.summary_version, row.summarized_through_turn, row.summary_status) == (2, 12, "ok")


def test_get_summary_rejects_other_user(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([]))
    service = build_service(store, settings, FakeSummarizer())

    with pytest.raises(SessionNotFound):
        service.get_summary("t1", "u2")


def test_get_summary_rejects_missing_thread(settings: Settings) -> None:
    service = build_service(InMemorySessionStateStore(), settings, FakeSummarizer())
    with pytest.raises(SessionNotFound):
        service.get_summary("missing", "u1")


def test_get_summary_repairs_stale_projection(
    settings: Settings, projection: SessionMemoryProjection
) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([], summary=BODY, version=3, through=18))
    projection.upsert("t1", "u1", 2, 12, "failed", NOW_ISO)
    service = build_service(store, settings, FakeSummarizer(), projection)

    view = service.get_summary("t1", "u1")

    assert view.summary_status == "ok"
    row = projection.get("t1")
    assert row is not None
    assert (row.summary_version, row.summarized_through_turn, row.summary_status) == (3, 18, "ok")


def test_regenerate_uses_existing_summary_and_earliest_six(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed(
        "t1",
        "u1",
        state_with([turn(number) for number in range(1, 21)], summary=BODY, version=2, through=3),
    )
    summarizer = FakeSummarizer()
    service = build_service(store, settings, summarizer)

    outcome = service.regenerate("t1", "u1")

    assert outcome.regenerated is True
    assert outcome.view.version == 3
    assert outcome.view.summarized_through_turn == 9
    assert summarizer.calls[0][0] == BODY
    assert summarizer.calls[0][1] == [4, 5, 6, 7, 8, 9]


def test_regenerate_without_pending_turns_is_noop(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed(
        "t1",
        "u1",
        state_with([turn(number) for number in range(1, 21)], summary=BODY, version=2, through=20),
    )
    summarizer = FakeSummarizer()
    service = build_service(store, settings, summarizer)

    outcome = service.regenerate("t1", "u1")

    assert outcome.regenerated is False
    assert outcome.view.version == 2
    assert outcome.view.summarized_through_turn == 20
    assert summarizer.calls == []


def test_regenerate_expected_version_conflict(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)], summary=BODY, version=2, through=0))
    summarizer = FakeSummarizer()
    service = build_service(store, settings, summarizer)

    with pytest.raises(SummaryConflict):
        service.regenerate("t1", "u1", expected_version=1)
    assert summarizer.calls == []


def test_regenerate_keeps_old_summary_on_model_failure(
    settings: Settings, projection: SessionMemoryProjection
) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)], summary=BODY, version=2, through=0))
    summarizer = FakeSummarizer(error=RuntimeError("boom"))
    service = build_service(store, settings, summarizer, projection)

    with pytest.raises(SummaryFailed):
        service.regenerate("t1", "u1")

    snapshot = store.load("t1", "u1")
    assert snapshot is not None
    assert snapshot.state["session_summary"] == BODY
    assert snapshot.state["session_summary_version"] == 2
    assert snapshot.state["summarized_through_turn"] == 0
    assert len(summarizer.calls) == 3

    view = service.get_summary("t1", "u1")
    assert view.summary_status == "failed"
    assert view.summary == BODY


def test_regenerate_rejects_invalid_structure(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)]))
    summarizer = FakeSummarizer(result={"facts": ["只有一类"]})
    service = build_service(store, settings, summarizer)

    with pytest.raises(SummaryFailed):
        service.regenerate("t1", "u1")
    assert len(summarizer.calls) == 3


def test_regenerate_retries_then_succeeds(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)]))
    summarizer = FakeSummarizer()

    def fail_once() -> None:
        if len(summarizer.calls) == 1:
            raise RuntimeError("transient")

    summarizer.on_call = fail_once
    service = build_service(store, settings, summarizer)

    outcome = service.regenerate("t1", "u1")

    assert outcome.regenerated is True
    assert outcome.view.version == 1
    assert len(summarizer.calls) == 2


def test_regenerate_times_out(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)]))
    summarizer = FakeSummarizer(sleep=0.2)
    service = build_service(
        store,
        settings.model_copy(update={"summary_timeout_seconds": 0.01}),
        summarizer,
    )

    started = time.monotonic()
    with pytest.raises(SummaryFailed):
        service.regenerate("t1", "u1")
    assert time.monotonic() - started < 1.0


def test_regenerate_state_conflict(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)]))
    summarizer = FakeSummarizer()

    def bump_revision() -> None:
        store.save("t1", "u1", state_with([turn(1), turn(2)]), 1)

    summarizer.on_call = bump_revision
    service = build_service(store, settings, summarizer)

    with pytest.raises(SummaryConflict):
        service.regenerate("t1", "u1")


def test_regenerate_respects_char_limit(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)]))
    huge = {key: ["x" * 50, "y" * 50] for key in SUMMARY_KEYS}
    summarizer = FakeSummarizer(result=huge)
    service = build_service(
        store,
        settings.model_copy(update={"summary_max_chars": 40}),
        summarizer,
    )

    outcome = service.regenerate("t1", "u1")

    assert outcome.view.summary is not None
    total = sum(len(item) for values in outcome.view.summary.values() for item in values)
    assert total <= 40


def test_summarize_if_due_waits_for_threshold(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(number) for number in range(1, 12)]))
    summarizer = FakeSummarizer()
    service = build_service(store, settings, summarizer)

    outcome = service.summarize_if_due("t1", "u1")

    assert outcome.regenerated is False
    assert summarizer.calls == []


def test_summarize_if_due_summarizes_six(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(number) for number in range(1, 13)]))
    summarizer = FakeSummarizer()
    service = build_service(store, settings, summarizer)

    outcome = service.summarize_if_due("t1", "u1")

    assert outcome.regenerated is True
    assert outcome.view.version == 1
    assert outcome.view.summarized_through_turn == 6
    assert summarizer.calls[0][1] == [1, 2, 3, 4, 5, 6]


def test_regenerate_rejects_other_user(settings: Settings) -> None:
    store = InMemorySessionStateStore()
    store.seed("t1", "u1", state_with([turn(1)]))
    service = build_service(store, settings, FakeSummarizer())

    with pytest.raises(SessionNotFound):
        service.regenerate("t1", "u2")
