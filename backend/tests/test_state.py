from app.state import MEMORY_STATE_FIELDS, ensure_memory_defaults


def test_ensure_defaults_fills_all_memory_fields() -> None:
    merged = ensure_memory_defaults({"goal": "转数据方向"})
    for field in MEMORY_STATE_FIELDS:
        assert field in merged
    assert merged["goal"] == "转数据方向"
    assert merged["session_turns"] == []
    assert merged["session_summary"] is None
    assert merged["session_summary_version"] == 0
    assert merged["summarized_through_turn"] == 0
    assert merged["memory_context"] == []
    assert merged["memory_context_meta"] == {}
    assert merged["context_budget_meta"] == {}


def test_ensure_defaults_preserves_existing_values() -> None:
    merged = ensure_memory_defaults(
        {
            "session_turns": [{"turn": 1}],
            "session_summary_version": 3,
            "summarized_through_turn": 12,
            "memory_context": [{"id": "m1"}],
        }
    )
    assert merged["session_turns"] == [{"turn": 1}]
    assert merged["session_summary_version"] == 3
    assert merged["summarized_through_turn"] == 12
    assert merged["memory_context"] == [{"id": "m1"}]


def test_ensure_defaults_does_not_mutate_input() -> None:
    state: dict = {}
    ensure_memory_defaults(state)
    assert state == {}


def test_ensure_defaults_returns_fresh_containers() -> None:
    first = ensure_memory_defaults({})
    first["session_turns"].append({"turn": 1})
    second = ensure_memory_defaults({})
    assert second["session_turns"] == []
