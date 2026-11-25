"""Keyword retrieval and scoring for user-level long-term memories."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from app.config import Settings
from app.db.utils import parse_iso

from .repository import is_enabled
from .token_budget import count_tokens

INJECTION_MAX_CHARS = 150
KEYWORD_LIMIT = 8
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.\-_]*")

KIND_WHITELIST: dict[str, frozenset[str]] = {
    "resume_optimizer": frozenset({"constraint", "preference", "goal"}),
    "career_coach": frozenset({"constraint", "preference", "goal"}),
    "interviewer": frozenset({"constraint", "preference", "goal"}),
    "job_analyst": frozenset(),
    "supervisor": frozenset(),
}


def role_memory_kinds(role: str) -> frozenset[str]:
    """Kinds of long-term memory a role may receive; empty means none."""
    return KIND_WHITELIST.get(role, frozenset())


def allows_session_history(role: str) -> bool:
    """Job analysis and routing must not see summaries, turns or memories."""
    return role not in {"job_analyst", "supervisor"}


def extract_keywords(text: str | None, *, limit: int = KEYWORD_LIMIT) -> list[str]:
    """Extract short search terms; CJK runs become bigrams so trigram FTS is not required."""
    if not text:
        return []
    terms: list[str] = []
    for token in _ASCII_TOKEN.findall(text):
        if len(token) >= 2:
            terms.append(token.lower())
    for run in _CJK_RUN.findall(text):
        if len(run) < 2:
            continue
        if len(run) <= 4:
            terms.append(run)
        else:
            terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        unique.append(term)
        if len(unique) >= limit:
            break
    return unique


def _recency(updated_at: str, now: datetime) -> float:
    try:
        moment = parse_iso(updated_at)
    except (TypeError, ValueError):
        return 0.0
    days = max(0.0, (now - moment).total_seconds() / 86400)
    return 0.5 ** (days / 30)


def _usable_rows(
    connection: sqlite3.Connection, user_id: str, now_iso: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM user_memories
        WHERE user_id = ? AND status = 'active' AND deleted_at IS NULL
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (user_id, now_iso),
    ).fetchall()


def _fts_rows(
    connection: sqlite3.Connection, user_id: str, keywords: Iterable[str], now_iso: str
) -> list[sqlite3.Row]:
    match = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in keywords)
    return connection.execute(
        """
        SELECT m.*, bm25(user_memories_fts) AS rank
        FROM user_memories_fts
        JOIN user_memories AS m ON m.id = user_memories_fts.memory_id
        WHERE user_memories_fts MATCH ?
          AND m.user_id = ? AND m.status = 'active' AND m.deleted_at IS NULL
          AND (m.expires_at IS NULL OR m.expires_at > ?)
        """,
        (match, user_id, now_iso),
    ).fetchall()


def _normalize_ranks(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return [1.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _candidates(
    connection: sqlite3.Connection,
    user_id: str,
    keywords: list[str],
    now: datetime,
    fts_enabled: bool,
) -> list[dict[str, Any]]:
    now_iso = now.isoformat()
    if not keywords:
        return [dict(row) for row in _usable_rows(connection, user_id, now_iso)]

    use_like = (not fts_enabled) or any(len(term) < 3 for term in keywords)
    if not use_like:
        try:
            rows = _fts_rows(connection, user_id, keywords, now_iso)
            scores = _normalize_ranks([-float(row["rank"]) for row in rows])
            candidates: list[dict[str, Any]] = []
            for row, relevance in zip(rows, scores):
                item = dict(row)
                item["relevance"] = relevance
                candidates.append(item)
            return candidates
        except sqlite3.OperationalError:
            pass

    candidates = []
    for row in _usable_rows(connection, user_id, now_iso):
        haystack = str(row["content"]).lower()
        matches = sum(1 for term in keywords if term in haystack)
        if matches == 0:
            continue
        item = dict(row)
        item["relevance"] = matches / len(keywords)
        candidates.append(item)
    return candidates


def _score(item: Mapping[str, Any], now: datetime, *, has_keywords: bool) -> float:
    confidence = float(item["confidence"])
    recency = _recency(str(item["updated_at"]), now)
    if not has_keywords:
        return 0.625 * recency + 0.375 * confidence
    relevance = float(item.get("relevance") or 0.0)
    return 0.6 * relevance + 0.25 * recency + 0.15 * confidence


def _clip(content: str) -> str:
    if len(content) <= INJECTION_MAX_CHARS:
        return content
    return content[: INJECTION_MAX_CHARS - 1].rstrip() + "…"


def retrieve_memories(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    query: str | None,
    settings: Settings,
    now: datetime | None = None,
    fts_enabled: bool = True,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Return the highest-scoring memories within the count and token budget."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if not is_enabled(connection, user_id, default_enabled=settings.memory_enabled_default):
        return []

    keywords = extract_keywords(query)
    candidates = _candidates(connection, user_id, keywords, moment, fts_enabled)
    for item in candidates:
        item["score"] = _score(item, moment, has_keywords=bool(keywords))
    candidates.sort(
        key=lambda item: (item["score"], item["updated_at"], item["id"]), reverse=True
    )

    limit = top_k if top_k is not None else settings.memory_top_k
    limit = max(0, min(int(limit), settings.memory_max_top_k))
    budget = settings.context_memory_tokens
    results: list[dict[str, Any]] = []
    used = 0
    for item in candidates:
        if len(results) >= limit:
            break
        content = _clip(str(item["content"]))
        cost = count_tokens(content)
        if results and used + cost > budget:
            continue
        used += cost
        results.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "content": content,
                "confidence": float(item["confidence"]),
                "score": round(float(item["score"]), 6),
            }
        )
    return results


def filter_for_role(memories: Iterable[Mapping[str, Any]], role: str) -> list[dict[str, Any]]:
    allowed = KIND_WHITELIST.get(role, frozenset())
    return [dict(item) for item in memories if item.get("kind") in allowed]


__all__ = [
    "INJECTION_MAX_CHARS",
    "KIND_WHITELIST",
    "extract_keywords",
    "filter_for_role",
    "retrieve_memories",
]
