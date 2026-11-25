"""Memory extraction pipeline: run results -> structured user-level memories."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from typing import Any

from pydantic import BaseModel, Field

from app.config import Settings
from app.db import connect
from app.llm import call_json
from app.prompts.loader import PromptBundle, build_messages

from .content import KINDS, MemoryContentError, SensitiveContentError, detect_sensitive
from .repository import (
    MemoryConflict,
    apply_operation,
    is_enabled,
    recent_by_kind,
)

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 5
RECENT_PER_KIND = 5


class MemoryCandidate(BaseModel):
    op: str = "skip"
    kind: str = ""
    content: str = ""
    confidence: float = 0.0
    target_id: str | None = None


class ExtractionOutput(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)


class ModelMemoryExtractor:
    """Calls the memory_extractor role and returns raw candidate dictionaries."""

    def __init__(self, context: Any) -> None:
        self._context = context

    async def extract(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        messages = self._context.messages("memory_extractor", values)
        result = await call_json(
            self._context.model("memory_extractor"),
            messages,
            ExtractionOutput,
            attempts=1,
        )
        return [candidate.model_dump() for candidate in result.candidates[:MAX_CANDIDATES]]


class MemoryWritePipeline:
    """Extracts and persists memories after a completed or partial run."""

    def __init__(
        self,
        settings: Settings,
        extractor: ModelMemoryExtractor,
        *,
        retry_delays: tuple[float, ...] = (1.0, 3.0),
    ) -> None:
        self._settings = settings
        self._extractor = extractor
        self._retry_delays = retry_delays
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        with self._guard:
            return self._locks.setdefault(user_id, asyncio.Lock())

    async def run(
        self, *, user_id: str, thread_id: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            async with self._lock_for(user_id):
                return await self._run(user_id=user_id, thread_id=thread_id, state=state)
        except Exception:  # pragma: no cover - background task must never break the run
            logger.warning(
                "memory extraction failed thread_id=%s user_id=%s", thread_id, user_id, exc_info=True
            )
            return {"written": 0, "failed": True}

    async def _run(
        self, *, user_id: str, thread_id: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        if state.get("run_status") not in {"succeeded", "partial"}:
            return {"written": 0, "skipped": "run_status"}

        db_path = self._settings.checkpoint_db_path
        with connect(db_path) as connection:
            if not is_enabled(
                connection, user_id, default_enabled=self._settings.memory_enabled_default
            ):
                return {"written": 0, "skipped": "disabled"}
            existing = self._existing_memories(connection, user_id)

        values = self._build_values(state, existing)
        candidates = await self._extract_with_retry(values)
        return self._persist(user_id=user_id, thread_id=thread_id, candidates=candidates)

    def _existing_memories(
        self, connection: sqlite3.Connection, user_id: str
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for kind in KINDS:
            for row in recent_by_kind(
                connection, user_id=user_id, kind=kind, limit=RECENT_PER_KIND
            ):
                collected.append(
                    {"id": row["id"], "kind": row["kind"], "content": row["content"]}
                )
        return collected

    def _build_values(
        self, state: dict[str, Any], existing: list[dict[str, Any]]
    ) -> dict[str, Any]:
        job_summaries: list[dict[str, Any]] = []
        for job in state.get("jobs") or []:
            if not isinstance(job, dict):
                continue
            review = job.get("review") or {}
            job_summaries.append(
                {
                    "title": job.get("title"),
                    "status": job.get("status"),
                    "error": job.get("error"),
                    "review_score": review.get("score"),
                    "missing": list(review.get("missing") or [])[:5],
                }
            )
        return {
            "goal": state.get("goal") or "",
            "job_summaries_json": job_summaries,
            "session_summary_json": state.get("session_summary") or {},
            "advice": state.get("advice") or "",
            "existing_memories_json": existing,
        }

    async def _extract_with_retry(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        attempts = len(self._retry_delays) + 1
        last_error: Exception | None = None
        for index in range(attempts):
            try:
                return await self._extractor.extract(values)
            except Exception as exc:
                last_error = exc
                if index < len(self._retry_delays):
                    await asyncio.sleep(self._retry_delays[index])
        raise RuntimeError(f"memory extraction failed: {last_error}")

    def _persist(
        self,
        *,
        user_id: str,
        thread_id: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        written = skipped = rejected = 0
        with connect(self._settings.checkpoint_db_path) as connection:
            for candidate in candidates[:MAX_CANDIDATES]:
                kind = str(candidate.get("kind") or "")
                content = str(candidate.get("content") or "")
                if kind not in KINDS:
                    rejected += 1
                    continue
                if detect_sensitive(content):
                    rejected += 1
                    continue
                try:
                    outcome = apply_operation(
                        connection,
                        user_id=user_id,
                        candidate=candidate,
                        settings=self._settings,
                        source_type="run",
                        source_thread_id=thread_id,
                    )
                except (MemoryContentError, MemoryConflict, sqlite3.Error):
                    rejected += 1
                    continue
                if outcome["action"] in {"created", "updated"}:
                    written += 1
                else:
                    skipped += 1
        return {"written": written, "skipped": skipped, "rejected": rejected}


__all__ = [
    "MAX_CANDIDATES",
    "ExtractionOutput",
    "MemoryCandidate",
    "MemoryWritePipeline",
    "ModelMemoryExtractor",
]
