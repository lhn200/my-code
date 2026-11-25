from __future__ import annotations

from app.memory.retrieval import allows_session_history, role_memory_kinds
from app.prompts.loader import SAFETY_PREFIX
from app.state import ensure_memory_defaults

MEMORY = {"kind": "preference", "content": "用户偏好远程办公", "confidence": 0.9}
SECRET_SUMMARY = {"facts": ["用户有三年运营经验"], "open_questions": [], "preferences": [], "constraints": [], "decisions": []}


def _session_state() -> dict:
    return {
        "session_turns": [
            {
                "turn": 1,
                "messages": [
                    {"role": "user", "content": "第一轮用户输入"},
                    {"role": "assistant", "content": "第一轮助手输出"},
                ],
            }
        ],
        "session_summary": SECRET_SUMMARY,
        "summarized_through_turn": 1,
        "memory_context": [MEMORY],
    }


def _joined(messages) -> str:
    return "\n".join(content for _role, content in messages)


def test_long_resume_is_digested_and_original_is_untouched(fake, settings) -> None:
    context, _models = fake
    resume = "技能：Python、FastAPI、SQLite\n" + "".join(
        f"工作经历第{index}段：负责服务模块{index}的接口开发，性能提升 {index}%。\n"
        for index in range(400)
    )
    assert len(resume) > settings.max_message_chars
    values = {"goal": "转后端", "profile_json": {}, "resume_text": resume}

    messages, meta = context.prepare("resume_reviewer", {}, values)

    assert values["resume_text"] == resume
    assert meta["digests"]["resume"]["original_chars"] >= settings.max_message_chars
    assert meta["digests"]["resume"]["original_chars"] <= len(resume)
    assert meta["digests"]["resume"]["fallback"] is False
    assert "【技能】" in _joined(messages[1:])


def test_long_job_description_is_digested(fake, settings) -> None:
    context, _models = fake
    jd = "".join(f"负责交易模块{index}的设计与开发。\n" for index in range(500))
    jd += "任职要求：熟悉 Python 与 FastAPI。"

    messages, meta = context.prepare(
        "job_analyst", {"memory_context": []}, {"job_title": "后端工程师", "job_text": jd}
    )

    assert meta["digests"]["jd"]["original_chars"] == len(jd)
    assert "【职责】" in _joined(messages[1:])
    assert "任职要求" in _joined(messages[1:])


def test_job_analyst_gets_no_memory_summary_or_turns(fake) -> None:
    context, _models = fake

    messages, meta = context.prepare(
        "job_analyst",
        _session_state(),
        {"job_title": "后端工程师", "job_text": "负责接口开发。"},
    )
    text = _joined(messages)

    assert meta["memory_count"] == 0
    assert "用户偏好远程办公" not in text
    assert "用户有三年运营经验" not in text
    assert "第一轮用户输入" not in text


def test_reviewer_gets_summary_but_no_long_term_memory(fake) -> None:
    context, _models = fake

    messages, meta = context.prepare(
        "resume_reviewer",
        _session_state(),
        {"goal": "转后端", "profile_json": {}, "resume_text": "熟练使用 Python。"},
    )
    text = _joined(messages)

    assert meta["memory_count"] == 0
    assert "用户偏好远程办公" not in text
    assert "用户有三年运营经验" in text


def test_coach_gets_whitelisted_memory_and_summary(fake) -> None:
    context, _models = fake

    messages, meta = context.prepare(
        "career_coach",
        _session_state(),
        {"goal": "转后端", "job_summaries_json": [], "interview_reports_json": {}},
    )
    text = _joined(messages)

    assert meta["memory_count"] == 1
    assert "用户偏好远程办公" in text
    assert "用户有三年运营经验" in text


def test_system_prompt_never_contains_memory_or_summary(fake) -> None:
    context, _models = fake

    messages, _meta = context.prepare(
        "career_coach",
        _session_state(),
        {"goal": "转后端", "job_summaries_json": [], "interview_reports_json": {}},
    )
    system = messages[0][1]

    assert system.startswith(SAFETY_PREFIX)
    assert "用户偏好远程办公" not in system
    assert "用户有三年运营经验" not in system
    assert system.endswith(context.prompts.system_prompt("career_coach"))


def test_old_state_without_memory_fields_still_assembles(fake) -> None:
    context, _models = fake
    old_state = {"goal": "转后端", "jobs": [{"job_id": "job-1"}]}

    messages, meta = context.prepare(
        "career_coach",
        old_state,
        {"goal": "转后端", "job_summaries_json": [], "interview_reports_json": {}},
    )

    assert len(messages) >= 2
    assert meta["digests"] == {}
    assert meta["turn_count"] == 0
    defaults = ensure_memory_defaults(old_state)
    assert defaults["memory_context"] == []
    assert defaults["session_summary"] is None


def test_role_boundaries_are_explicit() -> None:
    assert role_memory_kinds("job_analyst") == frozenset()
    assert allows_session_history("job_analyst") is False
    assert allows_session_history("career_coach") is True
    assert "preference" in role_memory_kinds("career_coach")
