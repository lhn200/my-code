"""Application runtime wiring: prompts, model router and graph context."""

from __future__ import annotations

from typing import Any, Callable

from .config import Settings
from .config.model_router import ModelRouter, RoleConfig
from .graph.context import GraphContext
from .prompts.loader import load_prompts


def create_context(
    settings: Settings,
    model_factory: Callable[[str, RoleConfig], Any] | None = None,
) -> GraphContext:
    prompts = load_prompts(settings.prompts_dir)
    router = ModelRouter(
        settings.models_config_path,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        respect_env_proxy=settings.llm_respect_env_proxy,
        model_factory=model_factory,
    )
    return GraphContext(settings=settings, router=router, prompts=prompts)


__all__ = ["create_context"]
