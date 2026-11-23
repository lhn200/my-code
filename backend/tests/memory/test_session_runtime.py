from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.memory.session_runtime import update_session_memory, run_turn_input
from tests.fakes import make_context


class FakeGraph:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = dict(values)
        self.updates: list[dict[str, Any]] = []

    async def aget_state(self, _config: Any) -> Any:
        return SimpleNamespace(values=dict(self.values))

    async def aupdate_state(self, _config: Any, values: dict[str, Any]) -> None:
        self.updates.append(dict(values))
        self.values.update(values)


def summary_handler(_messages: Any) -> str:
    return json.dumps(
        {
            "facts": ["用户关注数据分析岗位"],
            "open_questions": [],
            "preferences": [],
            "constraints": [],
            "decisions": [],
        },
        ensure_ascii=False,
    )


def make_app(settings, values: dict[str, Any], handler=summary_handler):
    context, models = make_context(settings, {"summarizer": handler})
    graph = FakeGraph(values)
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=settings,
            context=context,
            graph=graph,
            summary_locks={},
        )
    )
    return app, graph, models


def run_state(**overrides) -> dict[str, Any]:
    state: dict[str, Any] = {
        "goal": "转数据分析岗",
        "jobs": [{"job_id": "job-1", "title": "数据分析师"}],
        "advice": "先补 SQL 项目",
        "session_turns": [],
        "summarized_through_turn": 0,
        "session_summary_version": 0,
    }
    state.update(overrides)
    return state


def test_run_turn_input_describes_goal_and_jobs() -> None:
    text = run_turn_input(run_state())

    assert "目标：转数据分析岗" in text
    assert "岗位：数据分析师" in text


async def test_run_end_appends_one_turn(settings) -> None:
    app, graph, models = make_app(settings, run_state())

    await update_session_memory(app, user_id="u1", thread_id="t1", state=graph.values)

    assert len(graph.values["session_turns"]) == 1
    turn = graph.values["session_turns"][0]
    assert turn["turn"] == 1
    assert "转数据分析岗" in turn["user"]
    assert turn["assistant"] == "先补 SQL 项目"
    assert models.calls("summarizer") == 0


async def test_run_end_skips_duplicate_turn(settings) -> None:
    existing = {
        "turn": 1,
        "user": "目标：转数据分析岗\n岗位：数据分析师",
        "assistant": "先补 SQL 项目",
    }
    app, graph, _models = make_app(settings, run_state(session_turns=[existing]))

    await update_session_memory(app, user_id="u1", thread_id="t1", state=graph.values)

    assert graph.values["session_turns"] == [existing]
    assert graph.updates == []


async def test_run_end_summarizes_when_due(settings) -> None:
    turns = [
        {"turn": number, "user": f"输入{number}", "assistant": f"输出{number}"}
        for number in range(1, settings.summary_trigger_turns)
    ]
    app, graph, models = make_app(settings, run_state(session_turns=turns))

    await update_session_memory(app, user_id="u1", thread_id="t1", state=graph.values)

    assert models.calls("summarizer") == 1
    assert graph.values["session_summary_version"] == 1
    assert graph.values["summarized_through_turn"] == 6
    assert graph.values["session_summary"]["facts"] == ["用户关注数据分析岗位"]


async def test_run_end_summary_failure_does_not_raise(settings) -> None:
    turns = [
        {"turn": number, "user": f"输入{number}", "assistant": f"输出{number}"}
        for number in range(1, settings.summary_trigger_turns)
    ]

    def broken(_messages: Any) -> str:
        raise RuntimeError("model down")

    app, graph, _models = make_app(settings, run_state(session_turns=turns), broken)

    await update_session_memory(app, user_id="u1", thread_id="t1", state=graph.values)

    assert graph.values["session_summary_version"] == 0
    assert len(graph.values["session_turns"]) == settings.summary_trigger_turns


async def test_run_end_swallows_state_errors(settings) -> None:
    app, graph, _models = make_app(settings, run_state())

    async def boom(_config: Any) -> Any:
        raise RuntimeError("checkpoint unavailable")

    graph.aget_state = boom  # type: ignore[method-assign]

    await update_session_memory(app, user_id="u1", thread_id="t1", state=run_state())
