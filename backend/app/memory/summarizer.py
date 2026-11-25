"""Summarizer adapter used by the session memory service."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, Field

from app.llm import ChatModel, call_json
from app.prompts.loader import PromptBundle, build_messages


class SummaryOutput(BaseModel):
    facts: list[str] = Field(...)
    open_questions: list[str] = Field(...)
    preferences: list[str] = Field(...)
    constraints: list[str] = Field(...)
    decisions: list[str] = Field(...)


def _run_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class ModelSummarizer:
    """Synchronous summarizer facade; the memory service runs it in a worker thread."""

    def __init__(self, model: ChatModel, prompts: PromptBundle) -> None:
        self._model = model
        self._prompts = prompts

    def summarize(self, existing: dict[str, Any] | None, turns: list[dict[str, Any]]) -> dict[str, Any]:
        messages = build_messages(
            "summarizer",
            self._prompts,
            {"existing_summary_json": existing or {}, "turns_json": turns},
        )
        payload = _run_sync(call_json(self._model, messages, SummaryOutput, attempts=2))
        return payload.model_dump()


__all__ = ["ModelSummarizer", "SummaryOutput"]
