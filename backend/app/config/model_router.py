"""Role-based model configuration and chat model construction."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

ROLES: tuple[str, ...] = (
    "supervisor",
    "job_analyst",
    "resume_reviewer",
    "resume_optimizer",
    "career_coach",
)


class ModelConfigError(ValueError):
    """Raised when the model configuration is invalid; startup must abort."""


class RoleConfig(BaseModel):
    provider: str = "openai"
    model: str
    temperature: float = Field(default=0.2, ge=0, le=2)

    @field_validator("provider")
    @classmethod
    def _provider_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider must not be blank")
        return value.strip()

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("model must not be blank")
        return value.strip()


def _role_to_env(role: str) -> str:
    return f"MODEL_{role.upper()}"


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def load_models_config(path: Path, env: Mapping[str, str] | None = None) -> dict[str, RoleConfig]:
    """Load and validate models.yaml, applying environment overrides."""
    path = Path(path)
    if not path.exists():
        raise ModelConfigError(f"model config not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ModelConfigError(f"invalid model config YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelConfigError("model config root must be a mapping")

    raw_roles = raw.get("roles") or {}
    if not isinstance(raw_roles, dict):
        raise ModelConfigError("'roles' must be a mapping")

    unknown = sorted(set(raw_roles) - set(ROLES))
    if unknown:
        raise ModelConfigError(f"unknown model role(s): {', '.join(unknown)}")

    try:
        default = RoleConfig.model_validate(raw.get("default") or {})
    except ValidationError as exc:
        raise ModelConfigError(f"invalid default model config: {exc}") from exc

    environment = _env(env)
    if environment.get("DEFAULT_MODEL"):
        default = default.model_copy(update={"model": environment["DEFAULT_MODEL"].strip()})

    resolved: dict[str, RoleConfig] = {}
    for role in ROLES:
        base = raw_roles.get(role)
        if base is None:
            config = default.model_copy()
        else:
            try:
                config = RoleConfig.model_validate(base)
            except ValidationError as exc:
                raise ModelConfigError(f"invalid model config for role '{role}': {exc}") from exc
        override = environment.get(_role_to_env(role))
        if override:
            config = config.model_copy(update={"model": override.strip()})
        if not config.model.strip():
            raise ModelConfigError(f"role '{role}' has a blank model name")
        resolved[role] = config
    return resolved


class ModelRouter:
    """Maps a workflow role to a configured chat model instance."""

    def __init__(
        self,
        config_path: Path,
        env: Mapping[str, str] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model_factory: Callable[[str, RoleConfig], Any] | None = None,
        configs: dict[str, RoleConfig] | None = None,
    ) -> None:
        self._configs = configs or load_models_config(config_path, env=env)
        self.api_key = api_key
        self.base_url = base_url
        self._model_factory = model_factory
        self._cache: dict[str, Any] = {}

    @property
    def configs(self) -> dict[str, RoleConfig]:
        return dict(self._configs)

    def config_for(self, role: str) -> RoleConfig:
        try:
            return self._configs[role]
        except KeyError as exc:
            raise ModelConfigError(f"unknown model role: {role}") from exc

    def get_model(self, role: str) -> Any:
        """Return the chat model for a role, constructing it on first use."""
        if role in self._cache:
            return self._cache[role]
        config = self.config_for(role)
        if self._model_factory is not None:
            model = self._model_factory(role, config)
        else:
            model = self._build_openai_model(config)
        self._cache[role] = model
        return model

    def _build_openai_model(self, config: RoleConfig) -> Any:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ModelConfigError(
                "langchain-openai is required to build chat models; install it first"
            ) from exc
        kwargs: dict[str, Any] = {
            "model": config.model,
            "temperature": config.temperature,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return ChatOpenAI(**kwargs)


__all__ = [
    "ROLES",
    "ModelConfigError",
    "ModelRouter",
    "RoleConfig",
    "load_models_config",
]
