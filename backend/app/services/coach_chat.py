"""AI coach chat: multi-turn conversation grounded in an analysis session."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from ..checkpoint.sqlite import thread_config
from ..config import Settings
from ..db import connect, transaction
from ..db.coach import (
    append_message,
    create_session as insert_session,
    delete_session as delete_session_row,
    get_session,
    list_messages,
    list_sessions as list_session_rows,
    message_to_dict,
    new_session_id,
    session_to_dict,
    update_session as update_session_row,
)
from ..db.runs import get_run
from ..graph.context import GraphContext
from ..graph.nodes import current_review
from ..llm import LLMCallError, call_text
from ..memory.digest import build_resume_digest
from ..memory.retrieval import retrieve_memories
from ..prompts.loader import build_messages

logger = logging.getLogger(__name__)

_UNSET = object()


class CoachError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _owned_session(connection: Any, user_id: str, session_id: str) -> Any:
    row = get_session(connection, session_id)
    if row is None or row["user_id"] != user_id:
        raise CoachError(404, "coach_session_not_found", "教练会话不存在或已失效")
    return row


def _validate_thread(connection: Any, user_id: str, thread_id: str | None) -> None:
    if thread_id is None:
        return
    if get_run(connection, thread_id, user_id) is None:
        raise CoachError(404, "coach_analysis_not_found", "分析会话不存在或已删除")


def _payload(connection: Any, row: Any) -> dict[str, Any]:
    return {
        "session": session_to_dict(row),
        "messages": [
            message_to_dict(item) for item in list_messages(connection, row["id"])
        ],
    }


def _clip_resume(text: str, settings: Settings) -> str:
    text = (text or "").strip()
    if len(text) <= settings.max_message_chars:
        return text
    try:
        return build_resume_digest(text).text
    except Exception:  # pragma: no cover - digest fallback must never block chat
        return text[: settings.max_message_chars]


def _strings(values: Any, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item) for item in values if str(item).strip()][:limit]


def _analysis_context(
    values: Mapping[str, Any], settings: Settings
) -> dict[str, Any] | None:
    """Summarize the bound analysis into coach-friendly facts."""
    if not values:
        return None
    jobs = values.get("jobs") or []
    profiles = values.get("job_profiles") or {}
    reports = values.get("interview_reports") or {}

    job_items: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        profile = profiles.get(job_id) or {}
        item: dict[str, Any] = {
            "job_id": job_id,
            "title": str(job.get("title") or profile.get("title") or job_id),
        }
        if profile.get("status") == "ok":
            item["must_have"] = _strings(profile.get("must_have"), 6)
            item["keywords"] = _strings(profile.get("keywords"), 6)
        review = current_review(values, job_id)
        if review:
            item["review_score"] = review.get("score")
            item["dimensions"] = review.get("dimensions") or {}
            item["missing"] = _strings(review.get("missing"), 8)
            item["issues"] = _strings(review.get("issues"), 5)
        report = reports.get(job_id)
        if report:
            item["interview"] = {
                "status": report.get("status"),
                "overall_score": report.get("overall_score"),
                "improvements": _strings(report.get("improvements"), 5),
                "requirement_gaps": _strings(report.get("requirement_gaps"), 5),
            }
        job_items.append(item)

    return {
        "goal": str(values.get("goal") or ""),
        "resume_excerpt": _clip_resume(str(values.get("resume_text") or ""), settings),
        "jobs": job_items,
    }


def _auto_title(history: list[dict[str, Any]], text: str) -> str:
    source = text
    for item in history:
        if item["role"] == "user" and str(item["content"]).strip():
            source = str(item["content"])
            break
    return " ".join(source.split())[:40] or "新的教练会话"


def _compose_messages(
    context: GraphContext,
    coach_context: dict[str, Any],
    history: list[dict[str, Any]],
    text: str,
    settings: Settings,
) -> list[tuple[str, str]]:
    base = build_messages(
        "coach_chat",
        context.prompts,
        {"coach_context_json": coach_context, "user_message": text},
    )
    limit = max(0, settings.recent_turns_keep * 2)
    recent = history[-limit:] if limit else []
    messages: list[tuple[str, str]] = [base[0]]
    for item in recent:
        role = "human" if item["role"] == "user" else "ai"
        messages.append((role, str(item["content"])))
    messages.append(base[1])
    return messages


def create_session(
    db_path: Any, user_id: str, thread_id: str | None, title: str
) -> dict[str, Any]:
    thread_id = (thread_id or "").strip() or None
    with connect(db_path) as connection:
        _validate_thread(connection, user_id, thread_id)
        session_id = new_session_id()
        insert_session(
            connection,
            session_id=session_id,
            user_id=user_id,
            thread_id=thread_id,
            title=(title or "").strip(),
        )
        row = get_session(connection, session_id)
        return _payload(connection, row)


def list_sessions(
    db_path: Any, user_id: str, thread_id: str | None
) -> list[dict[str, Any]]:
    thread_id = (thread_id or "").strip() or None
    with connect(db_path) as connection:
        _validate_thread(connection, user_id, thread_id)
        return [session_to_dict(row) for row in list_session_rows(connection, user_id, thread_id)]


def get_session_payload(db_path: Any, user_id: str, session_id: str) -> dict[str, Any]:
    with connect(db_path) as connection:
        row = _owned_session(connection, user_id, session_id)
        return _payload(connection, row)


def update_session(
    db_path: Any,
    user_id: str,
    session_id: str,
    *,
    title: str | None = None,
    thread_id: Any = _UNSET,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        row = _owned_session(connection, user_id, session_id)
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title.strip()
        if thread_id is not _UNSET:
            normalized = (thread_id or "").strip() or None
            _validate_thread(connection, user_id, normalized)
            fields["thread_id"] = normalized
        if fields:
            update_session_row(connection, session_id, **fields)
            connection.commit()
            row = get_session(connection, session_id)
        return _payload(connection, row)


def delete_session(db_path: Any, user_id: str, session_id: str) -> None:
    with transaction(db_path) as connection:
        _owned_session(connection, user_id, session_id)
        delete_session_row(connection, session_id)


async def send_message(
    graph: Any,
    context: GraphContext,
    db_path: Any,
    user_id: str,
    session_id: str,
    content: str,
) -> dict[str, Any]:
    settings = context.settings
    text = (content or "").strip()
    if not text:
        raise CoachError(422, "coach_message_blank", "消息内容不能为空")
    if len(text) > settings.max_message_chars:
        raise CoachError(
            422,
            "coach_message_too_long",
            f"消息过长，请控制在 {settings.max_message_chars} 字以内",
        )

    with connect(db_path) as connection:
        row = _owned_session(connection, user_id, session_id)
        history = [message_to_dict(item) for item in list_messages(connection, session_id)]
        memories = retrieve_memories(
            connection, user_id=user_id, query=text, settings=settings
        )

    analysis = None
    if row["thread_id"]:
        try:
            snapshot = await graph.aget_state(thread_config(row["thread_id"]))
            analysis = _analysis_context(dict(snapshot.values or {}), settings)
        except Exception:  # pragma: no cover - analysis is optional context
            logger.warning(
                "coach analysis context unavailable session=%s thread=%s",
                session_id,
                row["thread_id"],
                exc_info=True,
            )

    coach_context = {
        "analysis": analysis,
        "memories": [
            {"kind": item["kind"], "content": item["content"]} for item in memories
        ],
    }
    messages = _compose_messages(context, coach_context, history, text, settings)

    try:
        async with context.semaphore:  # type: ignore[union-attr]
            reply = await call_text(
                context.model("coach_chat"), messages, attempts=2
            )
    except LLMCallError as exc:
        logger.warning("coach chat failed session=%s: %s", session_id, exc)
        raise CoachError(
            502, "coach_reply_failed", "教练暂时无法回复，请稍后重试"
        ) from exc

    reply = reply.strip()[: settings.max_message_chars]
    if not reply:
        raise CoachError(502, "coach_reply_failed", "教练没有返回有效回复，请稍后重试")

    with transaction(db_path) as connection:
        current = get_session(connection, session_id)
        if current is None or current["user_id"] != user_id:
            raise CoachError(404, "coach_session_not_found", "教练会话不存在或已失效")
        append_message(connection, session_id=session_id, role="user", content=text)
        append_message(connection, session_id=session_id, role="coach", content=reply)
        fields: dict[str, Any] = {}
        if not (current["title"] or "").strip():
            fields["title"] = _auto_title(history, text)
        update_session_row(connection, session_id, **fields)
        fresh = get_session(connection, session_id)
        return _payload(connection, fresh)


__all__ = [
    "CoachError",
    "create_session",
    "delete_session",
    "get_session_payload",
    "list_sessions",
    "send_message",
    "update_session",
]
