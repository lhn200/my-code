"""Job analysis subgraph: raw JD -> structured job profile."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, field_validator

from ..llm import call_json
from ..state import JobProfile
from .context import GraphContext


class JobAnalysisState(TypedDict, total=False):
    job_id: str
    title: str
    job_text: str
    profile: dict[str, Any]
    error: dict[str, Any] | None


class JobAnalysisOutput(BaseModel):
    is_job_posting: bool = True
    title: str = ""
    company: str = ""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    reason: str = ""

    @field_validator("must_have", "nice_to_have", "responsibilities", "keywords", mode="before")
    @classmethod
    def _clean_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        items = value if isinstance(value, list) else [value]
        return [str(item).strip() for item in items if str(item).strip()]


def failed_profile(job_id: str, title: str, reason: str) -> dict[str, Any]:
    return JobProfile(job_id=job_id, title=title, status="failed", error=reason).model_dump()


def _no_requirements(output: JobAnalysisOutput) -> bool:
    return not (
        output.must_have
        or output.nice_to_have
        or output.responsibilities
        or output.keywords
    )


def build_job_analysis_graph(context: GraphContext):
    """Compile the subgraph. It only sees job_id / title / job_text by design."""

    async def analyze(state: JobAnalysisState) -> dict[str, Any]:
        job_id = state.get("job_id", "")
        title = state.get("title", "")
        job_text = state.get("job_text", "")
        try:
            async with context.semaphore:  # type: ignore[union-attr]
                messages = context.messages(
                    "job_analyst", {"job_title": title, "job_text": job_text}
                )
                output = await call_json(
                    context.model("job_analyst"),
                    messages,
                    JobAnalysisOutput,
                    attempts=2,
                )
        except Exception as exc:
            reason = f"job analysis failed: {exc}"
            return {
                "profile": failed_profile(job_id, title, reason),
                "error": {
                    "stage": "analyze_job",
                    "job_id": job_id,
                    "code": "job_analysis_failed",
                    "message": reason,
                },
            }

        if not output.is_job_posting:
            reason = output.reason or "the text is not recognizable as a job posting"
            return {
                "profile": failed_profile(job_id, title, reason),
                "error": {
                    "stage": "analyze_job",
                    "job_id": job_id,
                    "code": "job_not_recognized",
                    "message": reason,
                },
            }

        if _no_requirements(output):
            reason = "no requirements or responsibilities could be extracted"
            return {
                "profile": failed_profile(job_id, title, reason),
                "error": {
                    "stage": "analyze_job",
                    "job_id": job_id,
                    "code": "job_no_requirements",
                    "message": reason,
                },
            }

        profile = JobProfile(
            job_id=job_id,
            title=output.title.strip() or title,
            company=output.company.strip(),
            must_have=output.must_have,
            nice_to_have=output.nice_to_have,
            responsibilities=output.responsibilities,
            keywords=output.keywords,
            status="ok",
        )
        return {"profile": profile.model_dump(), "error": None}

    builder = StateGraph(JobAnalysisState)
    builder.add_node("analyze", analyze)
    builder.add_edge(START, "analyze")
    builder.add_edge("analyze", END)
    return builder.compile()


__all__ = [
    "JobAnalysisOutput",
    "JobAnalysisState",
    "build_job_analysis_graph",
    "failed_profile",
]
