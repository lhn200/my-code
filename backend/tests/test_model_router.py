from __future__ import annotations

from pathlib import Path

import pytest

from app.config.model_router import ModelConfigError, ModelRouter, RoleConfig, load_models_config


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
