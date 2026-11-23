"""Shared graph execution context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..config.model_router import ModelRouter
from ..prompts.loader import PromptBundle, build_messages


@dataclass
class GraphContext:
    settings: Settings
    router: ModelRouter
    prompts: PromptBundle
    semaphore: asyncio.Semaphore | None = field(default=None)

    def __post_init__(self) -> None:
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(self.settings.max_concurrent_jobs)

    def model(self, role: str) -> Any:
        return self.router.get_model(role)

    def messages(self, role: str, values: dict[str, Any] | None = None) -> Any:
        return build_messages(role, self.prompts, values)


__all__ = ["GraphContext"]
