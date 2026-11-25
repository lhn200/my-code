"""Shared graph execution context."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..config import Settings
from ..config.model_router import ModelRouter
from ..memory.context_assembler import assemble_context
from ..memory.digest import (
    Digest,
    build_jd_digest,
    build_resume_digest,
    digest_meta,
)
from ..memory.retrieval import allows_session_history, filter_for_role
from ..prompts.loader import PromptBundle, build_messages

logger = logging.getLogger(__name__)

_DIGEST_FIELDS: tuple[str, ...] = ("resume_text", "baseline_resume")


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

    def prepare(
        self,
        role: str,
        state: Mapping[str, Any],
        values: Mapping[str, Any],
        *,
        job_profile: Mapping[str, Any] | None = None,
    ) -> tuple[list[tuple[str, str]], dict[str, Any]]:
        """Render one node's prompt with protected digests and session context.

        Long JD/resume inputs are replaced by their digest (original state keeps
        the full text). Memory is filtered by the role whitelist before assembly,
        so e.g. ``resume_reviewer`` never receives long-term memory.
        """
        rendered, digests = self._digest_values(values, job_profile)
        messages = build_messages(role, self.prompts, rendered)
        system_message = messages[0]
        human_message = messages[1][1]

        filtered = filter_for_role(state.get("memory_context") or [], role)
        scoped = {**dict(state), "memory_context": filtered}
        if not allows_session_history(role):
            scoped.update(
                {
                    "session_summary": None,
                    "session_turns": [],
                    "summarized_through_turn": 0,
                }
            )
        assembled = assemble_context(scoped, self.settings, human_message)

        meta: dict[str, Any] = {"role": role, **assembled.meta, **digest_meta(*digests)}
        meta["memory_count"] = min(len(filtered), self.settings.memory_top_k)
        if assembled.meta.get("truncated"):
            logger.info(
                "context truncated role=%s dropped_turns=%s dropped_memory=%s",
                role,
                assembled.meta.get("dropped_turns"),
                assembled.meta.get("dropped_memory"),
            )
        return [system_message, *assembled.messages], meta

    def _digest_values(
        self,
        values: Mapping[str, Any],
        job_profile: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], list[Digest]]:
        rendered = dict(values)
        digests: list[Digest] = []
        job_text = rendered.get("job_text")
        if isinstance(job_text, str) and len(job_text) > self.settings.max_message_chars:
            digest = build_jd_digest(job_text, profile=job_profile)
            rendered["job_text"] = digest.text
            digests.append(digest)
        for key in _DIGEST_FIELDS:
            text = rendered.get(key)
            if not isinstance(text, str) or len(text) <= self.settings.max_message_chars:
                continue
            digest = build_resume_digest(text)
            rendered[key] = digest.text
            digests.append(digest)
        return rendered, digests


__all__ = ["GraphContext"]
