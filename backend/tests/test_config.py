import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_are_valid() -> None:
    settings = Settings(_env_file=None)
    assert settings.session_context_budget == 8000
    assert settings.recent_turns_keep == 6
    assert settings.memory_enabled_default is False


def test_ttl_days_for_each_kind() -> None:
    settings = Settings(_env_file=None)
    assert settings.ttl_days_for("fact") == 180
    assert settings.ttl_days_for("goal") == 365
    assert settings.ttl_days_for("preference") == 0
    assert settings.ttl_days_for("constraint") == 0
    with pytest.raises(ValueError):
        settings.ttl_days_for("unknown")


def test_budget_parts_cannot_exceed_total() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, context_memory_tokens=9000)


def test_top_k_cannot_exceed_max() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, memory_top_k=9)


def test_pending_confidence_must_be_lower() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, memory_pending_confidence=0.8)


def test_min_recent_turns_cannot_exceed_keep() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, min_recent_turns=7)


def test_negative_ttl_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, memory_ttl_days_fact=-1)


def test_ttl_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_TTL_DAYS_FACT", "0")
    settings = Settings(_env_file=None)
    assert settings.ttl_days_for("fact") == 0
