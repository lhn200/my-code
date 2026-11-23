from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.memory.context_assembler import (
    SUMMARY_LABELS,
    ContextOverflow,
    assemble_context,
    truncate_message,
)
from app.memory.token_budget import count_tokens


def _settings(settings: Settings, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret="test-secret-key",
        checkpoint_db_path=Path(settings.checkpoint_db_path),
        upload_dir=Path(settings.upload_dir),
        **overrides,
    )


def _summary(facts: list[str], **overrides) -> dict:
    body: dict[str, list[str]] = {key: [] for key, _label in SUMMARY_LABELS}
    body["facts"] = facts
    body.update(overrides)
    return body


def _turn(number: int, text: str) -> dict:
    return {
        "turn": number,
        "role": "user" if number % 2 else "assistant",
        "content": text,
    }


def _joined(messages: list[tuple[str, str]]) -> str:
    return "\n".join(content for _role, content in messages)


def test_empty_session_uses_default_budget(settings: Settings) -> None:
    result = assemble_context({}, settings, "现在开始评估")

    assert result.messages == [("human", "现在开始评估")]
    assert result.meta["budget"] == {
        "total": 8000,
        "memory": 800,
        "summary": 1200,
        "recent_turns": 4800,
        "current_input": 1200,
    }
    assert result.meta["tokens"]["total"] == count_tokens("现在开始评估")
    assert result.meta["turn_count"] == 0
    assert result.meta["memory_count"] == 0
    assert result.meta["truncated"] is False
    assert "现在开始评估" not in json.dumps(result.meta, ensure_ascii=False)


def test_summary_and_recent_turns_do_not_duplicate(settings: Settings) -> None:
    state = {
        "session_turns": [
            _turn(1, "第 1 轮内容"),
            _turn(2, "第 2 轮内容"),
            _turn(3, "第 3 轮内容"),
            _turn(4, "第 4 轮内容"),
        ],
        "session_summary": _summary(["摘要事实"]),
        "summarized_through_turn": 2,
    }

    result = assemble_context(state, settings, "当前问题")
    text = _joined(result.messages)

    assert "摘要事实" in text
    assert "第 3 轮内容" in text
    assert "第 4 轮内容" in text
    assert "第 1 轮内容" not in text
    assert "第 2 轮内容" not in text
    assert result.meta["turn_count"] == 2


def test_all_turns_kept_before_summary_exists(settings: Settings) -> None:
    state = {"session_turns": [_turn(n, f"第 {n} 轮内容") for n in range(1, 4)]}

    result = assemble_context(state, settings, "当前问题")
    text = _joined(result.messages)

    assert all(f"第 {n} 轮内容" in text for n in range(1, 4))
    assert result.meta["turn_count"] == 3


def test_all_pending_turns_kept_before_first_summary(settings: Settings) -> None:
    state = {"session_turns": [_turn(n, f"第 {n} 轮内容") for n in range(1, 11)]}

    result = assemble_context(state, settings, "当前问题")
    text = _joined(result.messages)

    assert result.meta["turn_count"] == 10
    assert result.meta["dropped_turns"] == 0
    assert "第 1 轮内容" in text
    assert "第 10 轮内容" in text


def test_summary_window_keeps_only_latest_turns(settings: Settings) -> None:
    state = {
        "session_turns": [_turn(n, f"第 {n} 轮内容") for n in range(1, 11)],
        "session_summary": _summary(["摘要事实"]),
        "summarized_through_turn": 4,
    }

    result = assemble_context(state, settings, "当前问题")
    text = _joined(result.messages)

    assert "摘要事实" in text
    assert result.meta["turn_count"] == settings.recent_turns_keep
    assert result.meta["dropped_turns"] == 0
    assert "第 5 轮内容" in text
    assert "第 10 轮内容" in text
    assert "第 4 轮内容" not in text


def test_memory_is_trimmed_before_turns(settings: Settings) -> None:
    state = {
        "session_turns": [_turn(1, "最近一轮内容")],
        "memory_context": [
            {"kind": "preference", "content": "偏好" * 200},
            {"kind": "goal", "content": "目标" * 200},
            {"kind": "constraint", "content": "约束" * 200},
        ],
    }
    baseline = assemble_context(state, settings, "当前问题")
    tokens = baseline.meta["tokens"]
    parts = {
        "context_memory_tokens": 1,
        "context_summary_tokens": max(1, tokens["summary"]),
        "context_recent_turns_tokens": max(1, tokens["recent_turns"]),
        "context_current_input_tokens": max(1, tokens["current_input"]),
    }
    tight = _settings(
        settings,
        session_context_budget=sum(parts.values()) + 1,
        **parts,
    )

    result = assemble_context(state, tight, "当前问题")

    assert result.meta["memory_count"] == 0
    assert result.meta["dropped_memory"] == 3
    assert result.meta["turn_count"] == 1
    assert result.meta["dropped_turns"] == 0
    assert result.meta["truncated"] is True
    assert "最近一轮内容" in _joined(result.messages)


def test_oldest_turns_are_dropped_to_minimum(settings: Settings) -> None:
    turns = [_turn(n, f"第 {n} 轮" + "内容" * 5) for n in range(1, 5)]
    state = {"session_turns": turns}
    turn_tokens = count_tokens(turns[0]["content"])
    current_tokens = count_tokens("当前问题")
    parts = {
        "context_memory_tokens": 1,
        "context_summary_tokens": 1,
        "context_recent_turns_tokens": turn_tokens * 2,
        "context_current_input_tokens": max(1, current_tokens),
    }
    tight = _settings(
        settings,
        session_context_budget=sum(parts.values()) + 1,
        **parts,
    )

    result = assemble_context(state, tight, "当前问题")
    text = _joined(result.messages)

    assert result.meta["turn_count"] == 2
    assert result.meta["dropped_turns"] == 2
    assert "第 3 轮" in text or "第 4 轮" in text
    assert "第 1 轮" not in text
    assert "第 2 轮" not in text


def test_summary_is_compressed_as_last_resort(settings: Settings) -> None:
    state = {
        "session_turns": [_turn(1, "第一轮"), _turn(2, "第二轮")],
        "session_summary": _summary(["很长的摘要内容" * 40]),
        "summarized_through_turn": 0,
    }
    turn_tokens = count_tokens("第一轮") + count_tokens("第二轮")
    current_tokens = count_tokens("当前问题")
    parts = {
        "context_memory_tokens": 1,
        "context_summary_tokens": 70,
        "context_recent_turns_tokens": max(1, turn_tokens),
        "context_current_input_tokens": max(1, current_tokens),
    }
    tight = _settings(
        settings,
        session_context_budget=sum(parts.values()),
        **parts,
    )

    result = assemble_context(state, tight, "当前问题")
    text = _joined(result.messages)

    assert result.meta["summary_compressed"] is True
    assert "[摘要已压缩]" in text
    assert result.meta["turn_count"] == 2
    assert result.meta["tokens"]["total"] <= tight.session_context_budget


def test_current_input_overflow_raises(settings: Settings) -> None:
    tight = _settings(
        settings,
        session_context_budget=5,
        context_memory_tokens=1,
        context_summary_tokens=1,
        context_recent_turns_tokens=1,
        context_current_input_tokens=1,
    )

    with pytest.raises(ContextOverflow) as raised:
        assemble_context({}, tight, "这是一个明显超过预算的当前输入")

    assert raised.value.meta["reason"] == "current_input_exceeds_budget"


def test_budget_exhausted_after_trimming_raises(settings: Settings) -> None:
    state = {
        "session_turns": [_turn(1, "第一轮"), _turn(2, "第二轮")],
        "session_summary": _summary(["摘要事实"]),
    }
    parts = {
        "context_memory_tokens": 1,
        "context_summary_tokens": 1,
        "context_recent_turns_tokens": 1,
        "context_current_input_tokens": 1,
    }
    tight = _settings(settings, session_context_budget=4, **parts)

    with pytest.raises(ContextOverflow) as raised:
        assemble_context(state, tight, "当前问题")

    assert raised.value.meta["reason"] == "budget_exceeded"


def test_memory_disabled_skips_memory(settings: Settings) -> None:
    state = {
        "memory_context": [{"kind": "preference", "content": "偏好远程"}],
    }

    result = assemble_context(state, settings, "当前问题", memory_enabled=False)

    assert result.meta["memory_count"] == 0
    assert "偏好远程" not in _joined(result.messages)


def test_truncate_message_keeps_head_tail_and_marker() -> None:
    original = "甲" * 150 + "乙" * 150

    clipped, omitted = truncate_message(original, 100)

    assert omitted == 200
    assert clipped.startswith("甲" * 70)
    assert clipped.endswith("乙" * 30)
    assert "已截断 200 字" in clipped
    assert len(original) == 300


def test_assembly_does_not_mutate_state(settings: Settings) -> None:
    state = {
        "session_turns": [_turn(1, "第一轮")],
        "session_summary": _summary(["摘要事实"]),
        "memory_context": [{"kind": "fact", "content": "事实内容"}],
    }
    snapshot = copy.deepcopy(state)

    assemble_context(state, settings, "当前问题")

    assert state == snapshot


def test_count_tokens_handles_empty_and_odd_input() -> None:
    assert count_tokens("") == 0
    assert count_tokens(None) == 0  # type: ignore[arg-type]
    assert count_tokens(123) > 0  # type: ignore[arg-type]
    assert count_tokens("你好") > 0


def test_meta_never_contains_content(settings: Settings) -> None:
    state = {
        "session_turns": [_turn(1, "轮次正文")],
        "session_summary": _summary(["摘要正文"]),
        "memory_context": [{"kind": "fact", "content": "记忆正文"}],
    }

    result = assemble_context(state, settings, "当前输入正文")
    serialized = json.dumps(result.meta, ensure_ascii=False)

    assert "轮次正文" not in serialized
    assert "摘要正文" not in serialized
    assert "记忆正文" not in serialized
    assert "当前输入正文" not in serialized
