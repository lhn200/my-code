from __future__ import annotations

from pathlib import Path

import pytest

from app.config.model_router import (
    ModelConfigError,
    ModelRouter,
    RoleConfig,
    has_explicit_proxy,
    load_models_config,
)

_PROXY_NAMES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


VALID_YAML = """
default:
  provider: openai
  model: base-model
  temperature: 0.2
roles:
  supervisor:
    model: sup-model
    temperature: 0
  job_analyst:
    model: analyst-model
    temperature: 0.1
"""


def test_load_applies_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path / "models.yaml", VALID_YAML)
    configs = load_models_config(path, env={})
    assert configs["supervisor"].model == "sup-model"
    assert configs["job_analyst"].model == "analyst-model"
    assert configs["career_coach"].model == "base-model"
    assert configs["career_coach"].temperature == 0.2


def test_env_overrides(tmp_path: Path) -> None:
    path = _write(tmp_path / "models.yaml", VALID_YAML)
    configs = load_models_config(
        path,
        env={"DEFAULT_MODEL": "env-default", "MODEL_RESUME_REVIEWER": "env-reviewer"},
    )
    assert configs["career_coach"].model == "env-default"
    assert configs["resume_reviewer"].model == "env-reviewer"


def test_unknown_role_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "models.yaml",
        VALID_YAML.replace("job_analyst:", "unknown_role:"),
    )
    with pytest.raises(ModelConfigError, match="unknown model role"):
        load_models_config(path, env={})


def test_blank_model_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "models.yaml",
        VALID_YAML.replace("model: sup-model", "model: '   '"),
    )
    with pytest.raises(ModelConfigError):
        load_models_config(path, env={})


def test_temperature_out_of_range_fails(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "models.yaml",
        VALID_YAML.replace("temperature: 0\n", "temperature: 2.5\n"),
    )
    with pytest.raises(ModelConfigError):
        load_models_config(path, env={})


def test_missing_config_fails(tmp_path: Path) -> None:
    with pytest.raises(ModelConfigError, match="not found"):
        load_models_config(tmp_path / "missing.yaml", env={})


def test_router_uses_factory_and_caches(settings) -> None:
    created: list[RoleConfig] = []

    def factory(role: str, config: RoleConfig):
        created.append(config)
        return {"model": config.model}

    router = ModelRouter(
        Path("unused.yaml"),
        configs={"supervisor": RoleConfig(model="a", temperature=0)},
        model_factory=factory,
    )
    first = router.get_model("supervisor")
    second = router.get_model("supervisor")
    assert first is second
    assert len(created) == 1
    with pytest.raises(ModelConfigError):
        router.get_model("unknown")


def _proxy_router(*, respect_env_proxy: bool = True) -> ModelRouter:
    return ModelRouter(
        Path("unused.yaml"),
        configs={"supervisor": RoleConfig(model="kimi-k3", temperature=0.0)},
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        respect_env_proxy=respect_env_proxy,
    )


def test_has_explicit_proxy_only_reads_env(monkeypatch) -> None:
    for name in _PROXY_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert has_explicit_proxy(env={}) is False
    assert has_explicit_proxy(env={"HTTPS_PROXY": "  "}) is False
    assert has_explicit_proxy(env={"https_proxy": "http://127.0.0.1:7890"}) is True


def test_model_bypasses_system_proxy_without_explicit_config(monkeypatch) -> None:
    for name in _PROXY_NAMES:
        monkeypatch.delenv(name, raising=False)
    model = _proxy_router().get_model("supervisor")
    assert model.http_client.trust_env is False
    assert model.http_async_client.trust_env is False


def test_explicit_env_proxy_takes_priority(monkeypatch) -> None:
    for name in _PROXY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    model = _proxy_router().get_model("supervisor")
    assert model.http_client is None
    assert model.http_async_client is None


def test_respect_env_proxy_can_be_disabled(monkeypatch) -> None:
    for name in _PROXY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    model = _proxy_router(respect_env_proxy=False).get_model("supervisor")
    assert model.http_client.trust_env is False
    assert model.http_async_client.trust_env is False
