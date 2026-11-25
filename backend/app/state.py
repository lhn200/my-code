"""Graph state contract shared with the career assistant workflows."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping, TypedDict

from pydantic import BaseModel, ConfigDict, Field

DIMENSION_WEIGHTS: dict[str, float] = {
    "skills": 0.4,
    "experience": 0.3,
    "projects": 0.2,
    "education": 0.1,
}


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class JobInput(_Model):
    job_id: str
    title: str
    original_position_text: str


class JobProfile(_Model):
    job_id: str
    title: str = ""
    company: str = ""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    status: Literal["ok", "failed"] = "ok"
    error: str | None = None


class ReviewResult(_Model):
    job_id: str
    variant_version: int = 0
    score: int = Field(default=0, ge=0, le=100)
    dimensions: dict[str, int] = Field(default_factory=dict)
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    status: Literal["ok", "failed"] = "ok"
    error: str | None = None


class ResumeVariant(_Model):
    job_id: str
    variant_version: int
    text: str
    base_version: int = 0


class OptimizationRound(_Model):
    job_id: str
    round: int
    variant_version: int
    score_before: int
    score_after: int | None = None
    summary: str = ""


class InterviewReportSummary(_Model):
    job_id: str
    interview_thread_id: str
    status: Literal["completed", "abandoned"]
    generated_at: str
    variant_version: int = 0
    source: Literal["offline", "practice"] = "offline"
    session_id: str = ""
    dimension_averages: dict[str, float] = Field(default_factory=dict)
    overall_score: float | None = None
    highlights: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    requirement_gaps: list[str] = Field(default_factory=list)
    answered_count: int = 0
    planned_count: int = 0


class JobResult(_Model):
    job_id: str
    title: str
    status: Literal["ok", "failed"] = "ok"
    error: str | None = None
    profile: JobProfile | None = None
    resume_source: Literal["baseline", "variant"] = "baseline"
    current_variant_version: int = 0
    resume_text: str = ""
    review: ReviewResult | None = None
    variants: list[ResumeVariant] = Field(default_factory=list)
    optimization_history: list[OptimizationRound] = Field(default_factory=list)


class RunResult(_Model):
    run_status: Literal["running", "succeeded", "partial", "failed"]
    thread_id: str = ""
    advice: str = ""
    jobs: list[JobResult] = Field(default_factory=list)
    interview_reports: dict[str, InterviewReportSummary] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reducers
# ---------------------------------------------------------------------------


def merge_by_job_id(
    left: Mapping[str, Any] | None, right: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Merge job-keyed mappings, keeping the newest write per job."""
    merged: dict[str, Any] = dict(left or {})
    merged.update(right or {})
    return merged


def review_key(job_id: str, variant_version: int) -> str:
    return f"{job_id}::{variant_version}"


def merge_by_review_key(
    left: Mapping[str, Any] | None, right: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Merge review mappings keyed by ``job_id::variant_version``."""
    merged: dict[str, Any] = dict(left or {})
    merged.update(right or {})
    return merged


def _variant_version(item: Any) -> int:
    if isinstance(item, Mapping):
        return int(item.get("variant_version", 0))
    return int(getattr(item, "variant_version", 0))


def merge_variants(
    left: Mapping[str, list[Any]] | None, right: Mapping[str, list[Any]] | None
) -> dict[str, list[Any]]:
    """Merge per-job variants by version without cross-job overwrites."""
    merged: dict[str, list[Any]] = {job: list(items) for job, items in (left or {}).items()}
    for job_id, incoming in (right or {}).items():
        by_version: dict[int, Any] = {
            _variant_version(item): item for item in merged.get(job_id, [])
        }
        for item in incoming:
            by_version[_variant_version(item)] = item
        merged[job_id] = [by_version[version] for version in sorted(by_version)]
    return merged


def _round_key(item: Any) -> tuple[str, int]:
    if isinstance(item, Mapping):
        return str(item.get("job_id", "")), int(item.get("round", 0))
    return str(getattr(item, "job_id", "")), int(getattr(item, "round", 0))


def _score_after(item: Any) -> int | None:
    if isinstance(item, Mapping):
        return item.get("score_after")
    return getattr(item, "score_after", None)


def merge_rounds(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """Merge optimization rounds by ``(job_id, round)``, preferring scored rounds."""
    by_key: dict[tuple[str, int], Any] = {_round_key(item): item for item in (left or [])}
    for item in right or []:
        key = _round_key(item)
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
        elif _score_after(item) is not None or _score_after(current) is None:
            by_key[key] = item
    return [by_key[key] for key in sorted(by_key)]


def merge_attempts(
    left: Mapping[str, int] | None, right: Mapping[str, int] | None
) -> dict[str, int]:
    merged: dict[str, int] = dict(left or {})
    for job_id, count in (right or {}).items():
        merged[job_id] = max(merged.get(job_id, 0), int(count))
    return merged


def merge_context_meta(
    left: Mapping[str, Any] | None, right: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Merge per-node context budget metadata without cross-node overwrites."""
    merged: dict[str, Any] = dict(left or {})
    merged.update(right or {})
    return merged


def _error_key(item: Any) -> tuple[str, str, str]:
    if isinstance(item, Mapping):
        return (
            str(item.get("stage", "")),
            str(item.get("job_id", "")),
            str(item.get("message", "")),
        )
    return ("", "", str(item))


def merge_errors(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """Append structured errors while keeping the merge deterministic."""
    merged: dict[tuple[str, str, str], Any] = {_error_key(item): item for item in (left or [])}
    for item in right or []:
        merged.setdefault(_error_key(item), item)
    return list(merged.values())


def _report_thread(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("interview_thread_id", ""))
    return str(getattr(item, "interview_thread_id", ""))


def _report_generated_at(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("generated_at", ""))
    return str(getattr(item, "generated_at", ""))


def merge_interview_reports(
    left: Mapping[str, Any] | None, right: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Keep the latest report per job; identical interview threads are idempotent."""
    merged: dict[str, Any] = dict(left or {})
    for job_id, item in (right or {}).items():
        current = merged.get(job_id)
        if current is not None and _report_thread(current) == _report_thread(item):
            continue
        if current is not None and _report_generated_at(item) < _report_generated_at(current):
            continue
        merged[job_id] = item
    return merged


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    goal: str
    resume_text: str
    resume_file_id: str | None
    resume_file_url: str | None
    jobs: list[dict[str, Any]]
    threshold: int
    max_rounds: int

    job_profiles: Annotated[dict[str, Any], merge_by_job_id]
    reviews: Annotated[dict[str, Any], merge_by_review_key]
    resume_variants: Annotated[dict[str, list[Any]], merge_variants]
    optimization_history: Annotated[list[Any], merge_rounds]
    optimization_attempts: Annotated[dict[str, int], merge_attempts]
    interview_reports: Annotated[dict[str, Any], merge_interview_reports]
    interview_attempts: Annotated[dict[str, int], merge_attempts]
    advice: str
    errors: Annotated[list[Any], merge_errors]
    run_status: str
    prompt_versions: dict[str, str]

    session_turns: list[dict[str, Any]]
    session_summary: dict[str, Any] | None
    session_summary_version: int
    session_summary_updated_at: str | None
    summarized_through_turn: int
    memory_context: list[dict[str, Any]]
    memory_context_meta: dict[str, Any]
    context_budget_meta: Annotated[dict[str, Any], merge_context_meta]


MEMORY_STATE_DEFAULTS: dict[str, Any] = {
    "session_turns": [],
    "session_summary": None,
    "session_summary_version": 0,
    "session_summary_updated_at": None,
    "summarized_through_turn": 0,
    "memory_context": [],
    "memory_context_meta": {},
    "context_budget_meta": {},
}

MEMORY_STATE_FIELDS: tuple[str, ...] = tuple(MEMORY_STATE_DEFAULTS)


def ensure_memory_defaults(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of state with missing memory fields filled by defaults."""
    merged = dict(state)
    for field, default in MEMORY_STATE_DEFAULTS.items():
        if field not in merged or merged[field] is None:
            merged[field] = default.copy() if isinstance(default, (list, dict)) else default
    return merged


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def normalize_dimensions(raw: Mapping[str, Any] | None) -> dict[str, int]:
    dimensions: dict[str, int] = {}
    for name in DIMENSION_WEIGHTS:
        value = (raw or {}).get(name, 0)
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            number = 0
        dimensions[name] = max(0, min(100, number))
    return dimensions


def compute_review_score(dimensions: Mapping[str, int]) -> int:
    """Compute the weighted score so it always matches dimension scores."""
    total = sum(DIMENSION_WEIGHTS[name] * dimensions.get(name, 0) for name in DIMENSION_WEIGHTS)
    return max(0, min(100, int(round(total))))


def make_review_result(payload: Mapping[str, Any], job_id: str, variant_version: int) -> ReviewResult:
    dimensions = normalize_dimensions(payload.get("dimensions"))
    return ReviewResult(
        job_id=job_id,
        variant_version=variant_version,
        score=compute_review_score(dimensions),
        dimensions=dimensions,
        matched=[str(item) for item in payload.get("matched") or []],
        missing=[str(item) for item in payload.get("missing") or []],
        issues=[str(item) for item in payload.get("issues") or []],
    )


__all__ = [
    "AgentState",
    "DIMENSION_WEIGHTS",
    "InterviewReportSummary",
    "JobInput",
    "JobProfile",
    "JobResult",
    "MEMORY_STATE_DEFAULTS",
    "MEMORY_STATE_FIELDS",
    "OptimizationRound",
    "ResumeVariant",
    "ReviewResult",
    "RunResult",
    "compute_review_score",
    "ensure_memory_defaults",
    "make_review_result",
    "merge_attempts",
    "merge_by_job_id",
    "merge_by_review_key",
    "merge_context_meta",
    "merge_errors",
    "merge_interview_reports",
    "merge_rounds",
    "merge_variants",
    "normalize_dimensions",
    "review_key",
]
