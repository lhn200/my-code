"""Interactive practice interviews: ask, answer, follow up and evaluate.

The drill is deliberately independent from the main graph: each user turn makes
exactly one model call, and the session is persisted in its own tables so a page
refresh can resume the conversation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from ..checkpoint.sqlite import thread_config
from ..config import Settings
from ..db import connect, transaction
from ..db.interviews import (
    append_message,
    create_session as insert_session,
    get_open_session,
    get_session,
    list_messages,
    list_sessions,
    load_json,
    message_to_dict,
    new_session_id,
    session_to_dict,
    update_session,
)
from ..db.runs import get_run
from ..graph.context import GraphContext
from ..graph.nodes import current_review, current_variant
from ..llm import LLMCallError, call_json
from ..memory.digest import build_resume_digest
from ..prompts.loader import build_messages
from ..state import InterviewReportSummary
from .interview_reports import InterviewReportError, attach_interview_report

logger = logging.getLogger(__name__)


class InterviewSessionError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class TurnOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    feedback: str = ""
    score: int | None = None
    done: bool = False
    next_question: str = ""
    dimension: str = ""
    focus: str = ""
    is_followup: bool = False


class EvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    overall_score: float = Field(default=0, ge=0, le=100)
    dimension_averages: dict[str, float] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    requirement_gaps: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _clip_resume(text: str, settings: Settings) -> str:
    text = (text or "").strip()
    if len(text) <= settings.max_message_chars:
        return text
    try:
        return build_resume_digest(text).text
    except Exception:  # pragma: no cover - digest fallback must never block a drill
        return text[: settings.max_message_chars]


def _owned_session(connection: Any, user_id: str, session_id: str) -> Any:
    row = get_session(connection, session_id)
    if row is None or row["user_id"] != user_id:
        raise InterviewSessionError(404, "interview_not_found", "面试演练会话不存在")
    if get_run(connection, row["thread_id"], user_id) is None:
        raise InterviewSessionError(404, "interview_not_found", "来源会话不存在或已失效")
    return row


def _transcript(messages: list[Any]) -> list[dict[str, Any]]:
    """Turn a chronological message list into question/answer/feedback entries."""
    entries: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        kind = message["kind"]
        if role == "interviewer" and kind in ("question", "followup"):
            entries.append(
                {
                    "question_no": int(message["question_no"]),
                    "kind": kind,
                    "question": message["content"],
                    "answer": "",
                    "feedback": "",
                    "score": None,
                }
            )
        elif role == "interviewer" and kind == "feedback":
            if entries:
                entries[-1]["feedback"] = message["content"]
                entries[-1]["score"] = message["score"]
        elif role == "candidate" and kind == "answer":
            if entries:
                entries[-1]["answer"] = message["content"]
    return entries


def _session_meta(row: Any, **extra: Any) -> dict[str, Any]:
    meta = {
        "planned_count": int(row["planned_count"]),
        "asked_count": int(row["asked_count"]),
        "current_question_no": int(row["current_question_no"]),
        "followups_used": int(row["followups_used"]),
        "max_followups": int(row["max_followups"]),
        "can_follow_up": (
            int(row["followups_used"]) < int(row["max_followups"])
            and int(row["asked_count"]) < int(row["planned_count"])
        ),
    }
    meta.update(extra)
    return meta


def _payload(connection: Any, row: Any) -> dict[str, Any]:
    return {
        "session": session_to_dict(row),
        "messages": [message_to_dict(item) for item in list_messages(connection, row["id"])],
        "report": load_json(row["report_json"], None),
    }


def _prompt_values(row: Any, meta: Mapping[str, Any], transcript: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "goal": row["goal"],
        "profile_json": load_json(row["job_profile_json"], {}),
        "resume_text": row["resume_text"],
        "session_meta_json": dict(meta),
        "transcript_json": transcript,
    }


async def _ask_questioner(
    context: GraphContext,
    row: Any,
    meta: Mapping[str, Any],
    transcript: list[dict[str, Any]],
) -> TurnOutput:
    messages = build_messages(
        "interview_questioner", context.prompts, _prompt_values(row, meta, transcript)
    )
    try:
        async with context.semaphore:  # type: ignore[union-attr]
            return await call_json(
                context.model("interview_questioner"), messages, TurnOutput, attempts=2
            )
    except LLMCallError as exc:
        logger.warning("interview questioner failed session=%s: %s", row["id"], exc)
        raise InterviewSessionError(
            502, "interview_generation_failed", "面试官暂时无法生成下一个问题，请稍后重试"
        ) from exc


async def _evaluate(
    context: GraphContext,
    row: Any,
    meta: Mapping[str, Any],
    transcript: list[dict[str, Any]],
) -> EvaluationOutput:
    messages = build_messages(
        "interview_evaluator", context.prompts, _prompt_values(row, meta, transcript)
    )
    try:
        async with context.semaphore:  # type: ignore[union-attr]
            return await call_json(
                context.model("interview_evaluator"), messages, EvaluationOutput, attempts=2
            )
    except LLMCallError as exc:
        logger.warning("interview evaluator failed session=%s: %s", row["id"], exc)
        raise InterviewSessionError(
            502, "interview_report_failed", "评估报告生成失败，请稍后重试"
        ) from exc


async def create_session(
    graph: Any,
    context: GraphContext,
    db_path: Any,
    user_id: str,
    thread_id: str,
    job_id: str,
) -> dict[str, Any]:
    settings = context.settings
    with connect(db_path) as connection:
        if get_run(connection, thread_id, user_id) is None:
            raise InterviewSessionError(404, "interview_not_found", "来源会话不存在或已失效")
        existing = get_open_session(connection, user_id, thread_id, job_id)
        if existing is not None:
            return _payload(connection, existing)

    snapshot = await graph.aget_state(thread_config(thread_id))
    values = dict(snapshot.values or {})
    if not values:
        raise InterviewSessionError(404, "interview_not_found", "来源会话不存在或已失效")

    jobs = {str(job.get("job_id")): job for job in values.get("jobs") or []}
    job = jobs.get(job_id)
    profile = (values.get("job_profiles") or {}).get(job_id) or {}
    if job is None or profile.get("status") != "ok":
        raise InterviewSessionError(422, "interview_job_not_ready", "该岗位尚未完成分析，无法开始演练")
    review = current_review(values, job_id)
    if not review or review.get("status") != "ok":
        raise InterviewSessionError(422, "interview_job_not_ready", "该岗位缺少可用的简历评审结果")

    variant = current_variant(values, job_id)
    resume_text = variant["text"] if variant else str(values.get("resume_text") or "")
    variant_version = int(variant.get("variant_version", 0)) if variant else 0
    resume_snapshot = _clip_resume(resume_text, settings)

    session_id = new_session_id()
    draft = {
        "id": session_id,
        "goal": str(values.get("goal") or ""),
        "job_profile_json": json.dumps(profile, ensure_ascii=False),
        "resume_text": resume_snapshot,
        "planned_count": settings.interview_planned_count,
        "asked_count": 0,
        "current_question_no": 0,
        "followups_used": 0,
        "max_followups": settings.interview_followup_limit,
    }
    output = await _ask_questioner(
        context, draft, _session_meta(draft, answered_count=0), []
    )
    question = output.next_question.strip()
    if not question:
        raise InterviewSessionError(
            502, "interview_generation_failed", "面试官未能生成有效问题，请稍后重试"
        )
    question = question[: settings.max_message_chars]

    with connect(db_path) as connection:
        insert_session(
            connection,
            session_id=session_id,
            user_id=user_id,
            thread_id=thread_id,
            job_id=job_id,
            job_title=str(job.get("title") or profile.get("title") or job_id),
            goal=draft["goal"],
            job_profile=profile,
            resume_text=resume_snapshot,
            variant_version=variant_version,
            planned_count=settings.interview_planned_count,
            max_followups=settings.interview_followup_limit,
        )
        update_session(
            connection, session_id, asked_count=1, current_question_no=1, followups_used=0
        )
        append_message(
            connection,
            session_id=session_id,
            role="interviewer",
            kind="question",
            question_no=1,
            content=question,
        )
        connection.commit()
        row = get_session(connection, session_id)
        return _payload(connection, row)


async def submit_answer(
    graph: Any,
    context: GraphContext,
    db_path: Any,
    user_id: str,
    session_id: str,
    answer: str,
) -> dict[str, Any]:
    settings = context.settings
    answer = (answer or "").strip()
    if not answer:
        raise InterviewSessionError(422, "interview_answer_blank", "回答内容不能为空")
    if len(answer) > settings.interview_answer_max_chars:
        raise InterviewSessionError(
            422,
            "interview_answer_too_long",
            f"回答过长，请控制在 {settings.interview_answer_max_chars} 字以内",
        )

    with connect(db_path) as connection:
        row = _owned_session(connection, user_id, session_id)
        if row["status"] != "active":
            raise InterviewSessionError(409, "interview_closed", "该演练已结束，无法继续作答")
        messages = list_messages(connection, session_id)

    if (
        not messages
        or messages[-1]["role"] != "interviewer"
        or messages[-1]["kind"] not in ("question", "followup")
    ):
        raise InterviewSessionError(409, "interview_waiting_question", "请等待面试官提问后再作答")

    transcript = _transcript(messages)
    transcript[-1]["answer"] = answer
    meta = _session_meta(row, answered_count=sum(1 for item in messages if item["role"] == "candidate"))
    output = await _ask_questioner(context, row, meta, transcript)

    planned = int(row["planned_count"])
    asked = int(row["asked_count"])
    current_no = int(row["current_question_no"])
    followups_used = int(row["followups_used"])
    max_followups = int(row["max_followups"])

    feedback = output.feedback.strip()[: settings.interview_answer_max_chars]
    score = None if output.score is None else int(_clamp(output.score))
    done = asked >= planned

    new_asked = asked
    new_no = current_no
    new_followups = followups_used
    next_kind = ""
    next_text = ""
    if not done:
        candidate = output.next_question.strip()
        if not candidate:
            raise InterviewSessionError(
                502, "interview_generation_failed", "面试官未能生成下一个问题，请稍后重试"
            )
        next_text = candidate[: settings.max_message_chars]
        if bool(output.is_followup) and followups_used < max_followups:
            next_kind = "followup"
            new_followups = followups_used + 1
        else:
            next_kind = "question"
            new_asked = asked + 1
            new_no = current_no + 1
            new_followups = 0

    with transaction(db_path) as connection:
        current = get_session(connection, session_id)
        if current is None or current["user_id"] != user_id:
            raise InterviewSessionError(404, "interview_not_found", "面试演练会话不存在")
        if current["status"] != "active":
            raise InterviewSessionError(409, "interview_closed", "该演练已结束，无法继续作答")

        append_message(
            connection,
            session_id=session_id,
            role="candidate",
            kind="answer",
            question_no=current_no,
            content=answer,
        )
        if feedback:
            append_message(
                connection,
                session_id=session_id,
                role="interviewer",
                kind="feedback",
                question_no=current_no,
                content=feedback,
                score=score,
            )
        if done:
            update_session(
                connection,
                session_id,
                status="ready_to_finish",
                asked_count=new_asked,
                current_question_no=new_no,
                followups_used=new_followups,
            )
        else:
            append_message(
                connection,
                session_id=session_id,
                role="interviewer",
                kind=next_kind,
                question_no=new_no,
                content=next_text,
            )
            update_session(
                connection,
                session_id,
                asked_count=new_asked,
                current_question_no=new_no,
                followups_used=new_followups,
            )
        row = get_session(connection, session_id)
        return _payload(connection, row)


async def finish_session(
    graph: Any,
    context: GraphContext,
    db_path: Any,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        row = _owned_session(connection, user_id, session_id)
        if row["status"] == "completed":
            return _payload(connection, row)
        if row["status"] not in ("active", "ready_to_finish"):
            raise InterviewSessionError(409, "interview_closed", "该演练当前状态无法生成报告")
        messages = list_messages(connection, session_id)

    answers = [item for item in messages if item["role"] == "candidate" and item["kind"] == "answer"]
    if not answers:
        raise InterviewSessionError(422, "interview_no_answers", "请至少回答一道题后再生成报告")

    transcript = _transcript(messages)
    meta = _session_meta(row, answered_count=len(answers))
    output = await _evaluate(context, row, meta, transcript)

    dimensions = {
        str(key): _clamp(value)
        for key, value in output.dimension_averages.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    report = InterviewReportSummary(
        job_id=row["job_id"],
        interview_thread_id=f"practice-{session_id}",
        status="completed" if row["status"] == "ready_to_finish" else "abandoned",
        generated_at=_now(),
        variant_version=int(row["variant_version"]),
        source="practice",
        session_id=session_id,
        dimension_averages=dimensions,
        overall_score=_clamp(output.overall_score),
        highlights=output.highlights,
        red_flags=output.red_flags,
        improvements=output.improvements,
        requirement_gaps=output.requirement_gaps,
        answered_count=len(answers),
        planned_count=int(row["planned_count"]),
    )

    try:
        attached = await attach_interview_report(
            graph, context, row["thread_id"], row["job_id"], report.model_dump()
        )
    except InterviewReportError as exc:
        raise InterviewSessionError(exc.status_code, exc.code, exc.message) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("attach practice report failed session=%s", session_id)
        raise InterviewSessionError(
            502, "interview_report_failed", f"报告写入失败：{exc}"
        ) from exc

    if not attached.get("written") and not attached.get("idempotent"):
        raise InterviewSessionError(
            502, "interview_report_failed", attached.get("error") or "报告写入失败"
        )

    with connect(db_path) as connection:
        update_session(
            connection,
            session_id,
            status="completed",
            report_json=json.dumps(report.model_dump(), ensure_ascii=False),
            completed_at=_now(),
        )
        connection.commit()
        row = get_session(connection, session_id)
        return _payload(connection, row)


def get_session_payload(db_path: Any, user_id: str, session_id: str) -> dict[str, Any]:
    with connect(db_path) as connection:
        row = _owned_session(connection, user_id, session_id)
        return _payload(connection, row)


def list_session_payloads(db_path: Any, user_id: str, thread_id: str) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        if get_run(connection, thread_id, user_id) is None:
            raise InterviewSessionError(404, "interview_not_found", "来源会话不存在或已失效")
        rows = list_sessions(connection, user_id, thread_id)
        return [_payload(connection, row) for row in rows]


__all__ = [
    "EvaluationOutput",
    "InterviewSessionError",
    "TurnOutput",
    "create_session",
    "finish_session",
    "get_session_payload",
    "list_session_payloads",
    "submit_answer",
]
