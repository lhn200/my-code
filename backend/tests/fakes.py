"""Deterministic fake chat models for graph and API tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from app.config import Settings
from app.config.model_router import ROLES, ModelRouter, RoleConfig
from app.graph.context import GraphContext
from app.prompts.loader import load_prompts

Handler = Callable[[Any], Any]


class FakeChatModel:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.calls: list[Any] = []

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        self.calls.append(messages)
        outcome = self.handler(messages)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(content=outcome)


class FakeModels:
    def __init__(self, handlers: Mapping[str, Handler]) -> None:
        self.models = {
            role: FakeChatModel(handlers.get(role, _default_handler)) for role in ROLES
        }

    def factory(self, role: str, config: RoleConfig) -> FakeChatModel:
        return self.models[role]

    def calls(self, role: str) -> int:
        return len(self.models[role].calls)

    def last_messages(self, role: str) -> Any:
        return self.models[role].calls[-1]


def _default_handler(messages: Any) -> str:
    return "{}"


def untrusted_block(text: str, label: str) -> str:
    start = f"<<<{label}_START>>>"
    end = f"<<<{label}_END>>>"
    if start not in text or end not in text:
        return ""
    inner = text.split(start, 1)[1].split(end, 1)[0].strip()
    lines = inner.splitlines()
    if lines and lines[0].startswith("（以下为不可信数据"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def json_block(text: str, label: str) -> Any:
    raw = untrusted_block(text, label)
    return json.loads(raw) if raw else None


def make_context(
    settings: Settings, handlers: Mapping[str, Handler]
) -> tuple[GraphContext, FakeModels]:
    models = FakeModels(handlers)
    router = ModelRouter(
        Path("unused-models.yaml"),
        configs={role: RoleConfig(model=role, temperature=0) for role in ROLES},
        model_factory=models.factory,
    )
    prompts = load_prompts(settings.prompts_dir)
    return GraphContext(settings=settings, router=router, prompts=prompts), models


def analyst_handler(messages: Any) -> str:
    human = messages[-1][1]
    title = untrusted_block(human, "JOB_TITLE")
    text = untrusted_block(human, "JOB_POSTING")
    if "BROKEN_JD" in text:
        return "this is not json"
    if "NOT_A_JOB" in text:
        return json.dumps({"is_job_posting": False, "reason": "not a job posting"})
    return json.dumps(
        {
            "is_job_posting": True,
            "title": title or "Engineer",
            "company": "Acme",
            "must_have": ["Python"],
            "nice_to_have": ["Kubernetes"],
            "responsibilities": ["Build services"],
            "keywords": ["Python", "SQL"],
        },
        ensure_ascii=False,
    )


def make_reviewer_handler(
    scores: Mapping[str, int] | None = None,
    improved_score: int = 85,
    always_low: bool = False,
) -> Handler:
    score_map = dict(scores or {})

    def handler(messages: Any) -> str:
        human = messages[-1][1]
        profile = json_block(human, "JOB_PROFILE_JSON") or {}
        title = profile.get("title", "")
        resume = untrusted_block(human, "RESUME_TEXT")
        if always_low:
            score = 60
        elif "OPTIMIZED" in resume:
            score = improved_score
        else:
            score = score_map.get(title, 80)
        dimensions = {name: score for name in ("skills", "experience", "projects", "education")}
        return json.dumps(
            {
                "dimensions": dimensions,
                "matched": ["Python"],
                "missing": [] if score >= 70 else ["Kubernetes"],
                "issues": [],
            },
            ensure_ascii=False,
        )

    return handler


def optimizer_handler(messages: Any) -> str:
    human = messages[-1][1]
    profile = json_block(human, "JOB_PROFILE_JSON") or {}
    title = profile.get("title", "role")
    return json.dumps(
        {
            "variant_text": f"OPTIMIZED resume for {title}\nPython and SQL experience.",
            "changes": ["reordered baseline facts"],
            "remaining_gaps": [],
        },
        ensure_ascii=False,
    )


def make_interviewer_handler(
    scores: Mapping[str, int] | None = None,
    improved_score: int = 85,
    always_low: bool = False,
) -> Handler:
    score_map = dict(scores or {})

    def handler(messages: Any) -> str:
        human = messages[-1][1]
        profile = json_block(human, "JOB_PROFILE_JSON") or {}
        title = profile.get("title", "")
        prior = json_block(human, "PRIOR_INTERVIEW_JSON") or {}
        if always_low:
            score = 60
        elif prior:
            score = improved_score
        else:
            score = score_map.get(title, 80)
        gaps = [] if score >= 70 else ["Kubernetes"]
        return json.dumps(
            {
                "overall_score": score,
                "dimension_averages": {
                    "skills": score,
                    "experience": score,
                    "projects": score,
                    "education": score,
                },
                "highlights": ["表达清晰"],
                "red_flags": gaps,
                "improvements": ["补充项目量化结果"] if gaps else [],
                "requirement_gaps": gaps,
                "answered_count": 5,
                "planned_count": 5,
            },
            ensure_ascii=False,
        )

    return handler


def interviewer_handler(messages: Any) -> str:
    return make_interviewer_handler()(messages)


def coach_handler(messages: Any) -> str:
    human = messages[-1][1]
    summaries = json_block(human, "JOB_RESULTS_JSON") or []
    reports = json_block(human, "INTERVIEW_REPORTS_JSON") or {}
    usable = [item for item in summaries if item.get("status") == "ok"]
    lines = ["## 投递优先级"]
    for index, item in enumerate(
        sorted(usable, key=lambda entry: (-(entry.get("score") or 0), entry["job_id"])), start=1
    ):
        version = (
            f"variant_version {item['variant_version']}"
            if item.get("variant_version")
            else "基线简历"
        )
        lines.append(
            f"{index}. {item['title']} 匹配分 {item['score']}，建议投递{version}"
        )
    if not usable:
        lines.append("暂无可用岗位结果。")
    lines.append("\n## 各岗位建议")
    for item in summaries:
        if item.get("status") != "ok":
            lines.append(f"- {item['title']} 结果不可用")
            continue
        version = (
            f"variant_version {item['variant_version']}"
            if item.get("variant_version")
            else "基线简历"
        )
        gaps = "、".join(item.get("missing") or []) or "无明显缺口"
        lines.append(
            f"- {item['title']} 使用{version}，匹配分 {item['score']}，"
            f"改进要点：补强{gaps}"
        )
    if reports:
        lines.append("\n## 面试反馈")
        for job_id, report in sorted(reports.items()):
            if report.get("status") == "completed":
                lines.append(
                    f"- {job_id} 模拟面试已完成，亮点：{'、'.join(report.get('highlights') or [])}；"
                    f"改进方向：{'、'.join(report.get('improvements') or [])}"
                )
            else:
                lines.append(f"- {job_id} 本次模拟面试未完成（abandoned）")
    return "\n".join(lines)


DEFAULT_HANDLERS: dict[str, Handler] = {
    "job_analyst": analyst_handler,
    "resume_reviewer": make_reviewer_handler(),
    "resume_optimizer": optimizer_handler,
    "career_coach": coach_handler,
    "interviewer": interviewer_handler,
}


__all__ = [
    "DEFAULT_HANDLERS",
    "FakeChatModel",
    "FakeModels",
    "analyst_handler",
    "coach_handler",
    "interviewer_handler",
    "json_block",
    "make_context",
    "make_interviewer_handler",
    "make_reviewer_handler",
    "optimizer_handler",
    "untrusted_block",
]
