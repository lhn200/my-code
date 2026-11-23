"""Offline prompt regression evaluation and A/B comparison.

Usage (from the repository root)::

    python -m evals.run
    python -m evals.run --prompt-version <hash>
    python -m evals.run --ab-prompts-dir path/to/other/prompts

The evaluator never imports the FastAPI app, never opens a checkpoint database
and never writes to ``data/uploads``. Reports are written to ``evals/reports/``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:  # allow `python -m evals.run` from the repo root
    sys.path.insert(0, str(BACKEND_DIR))

from pydantic import BaseModel, Field, ValidationError  # noqa: E402

from app.config import Settings  # noqa: E402
from app.config.model_router import ModelRouter, RoleConfig, load_models_config  # noqa: E402
from app.graph.job_analysis import JobAnalysisOutput  # noqa: E402
from app.llm import extract_json, message_text  # noqa: E402
from app.prompts.loader import PromptBundle, build_messages, load_prompts  # noqa: E402
from app.state import compute_review_score, normalize_dimensions  # noqa: E402

EVAL_TEMPERATURE = 0.0
# Wall-clock latency varies between runs, so it is reported but never used to
# decide an A/B winner.
NON_COMPARABLE_METRICS: frozenset[str] = frozenset({"avg_latency_ms"})
DEFAULT_REPORTS_DIR = ROOT / "evals" / "reports"
DEFAULT_DATASETS_DIR = ROOT / "evals" / "datasets"
DEFAULT_BASELINE_PATH = ROOT / "evals" / "baseline.json"


class EvalError(RuntimeError):
    """Raised when datasets, prompts or baselines are unusable."""


class ReviewEvalOutput(BaseModel):
    dimensions: dict[str, Any] = Field(default_factory=dict)
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class OptimizerEvalOutput(BaseModel):
    variant_text: str = ""
    changes: list[str] = Field(default_factory=list)
    remaining_gaps: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class TaskSpec:
    name: str
    role: str
    schema: type[BaseModel]
    recall_output_field: str
    expected_recall_key: str
    hallucination_fields: tuple[str, ...]
    score_aware: bool = False


TASK_SPECS: dict[str, TaskSpec] = {
    "job_analysis": TaskSpec(
        name="job_analysis",
        role="job_analyst",
        schema=JobAnalysisOutput,
        recall_output_field="must_have",
        expected_recall_key="must_have",
        hallucination_fields=("must_have", "nice_to_have", "keywords", "responsibilities"),
    ),
    "resume_review": TaskSpec(
        name="resume_review",
        role="resume_reviewer",
        schema=ReviewEvalOutput,
        recall_output_field="missing",
        expected_recall_key="missing",
        hallucination_fields=("matched",),
        score_aware=True,
    ),
    "resume_optimization": TaskSpec(
        name="resume_optimization",
        role="resume_optimizer",
        schema=OptimizerEvalOutput,
        recall_output_field="remaining_gaps",
        expected_recall_key="remaining_gaps",
        hallucination_fields=("variant_text", "changes"),
    ),
}


@dataclass(frozen=True)
class Dataset:
    task: str
    version: str
    samples: tuple[dict[str, Any], ...]


def load_datasets(directory: Path | str) -> list[Dataset]:
    """Load every ``*.json`` dataset and require all three task types."""
    paths = sorted(Path(directory).glob("*.json"))
    if not paths:
        raise EvalError(f"no dataset files found in {directory}")
    datasets: list[Dataset] = []
    seen: set[str] = set()
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvalError(f"invalid dataset JSON: {path}: {exc}") from exc
        task = raw.get("task")
        if task not in TASK_SPECS:
            raise EvalError(f"unknown task {task!r} in {path}")
        if task in seen:
            raise EvalError(f"duplicate dataset for task {task!r}")
        seen.add(task)
        samples = raw.get("samples")
        if not isinstance(samples, list) or not samples:
            raise EvalError(f"dataset {path} must contain a non-empty 'samples' list")
        for sample in samples:
            if not isinstance(sample, dict) or not sample.get("id"):
                raise EvalError(f"dataset {path} has a sample without an id")
            if not isinstance(sample.get("input"), dict):
                raise EvalError(f"sample {sample.get('id')} in {path} requires an 'input' object")
            if not isinstance(sample.get("expected"), dict):
                raise EvalError(f"sample {sample.get('id')} in {path} requires an 'expected' object")
        datasets.append(
            Dataset(task=task, version=str(raw.get("version", "unversioned")), samples=tuple(samples))
        )
    missing = set(TASK_SPECS) - seen
    if missing:
        raise EvalError(f"datasets must cover all tasks; missing: {', '.join(sorted(missing))}")
    return sorted(datasets, key=lambda item: item.task)


def dataset_fingerprint(datasets: Sequence[Dataset]) -> str:
    payload = [
        {"task": item.task, "version": item.version, "samples": list(item.samples)}
        for item in datasets
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> str:
    return " ".join(str(value).lower().replace("，", ",").split())


def _recall(expected: Sequence[Any], produced: Sequence[Any]) -> float | None:
    if not expected:
        return None
    hits = 0
    for wanted in expected:
        target = _normalize(wanted)
        if not target:
            continue
        if any(
            target in _normalize(item) or _normalize(item) in target
            for item in produced
            if _normalize(item)
        ):
            hits += 1
    return hits / len(expected)


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_flatten(item) for item in value)
    if isinstance(value, Mapping):
        return "\n".join(_flatten(item) for item in value.values())
    return "" if value is None else str(value)


def _usage_tokens(response: Any, text: str) -> int:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, Mapping):
        for key in ("total_tokens", "total_token_count"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, Mapping) and isinstance(metadata.get("token_usage"), Mapping):
        total = metadata["token_usage"].get("total_tokens")
        if isinstance(total, (int, float)) and total > 0:
            return int(total)
    return max(1, len(text) // 4)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_metrics(records: Sequence[dict[str, Any]]) -> dict[str, float]:
    recalls = [item["missing_recall"] for item in records if item.get("missing_recall") is not None]
    score_errors = [item["score_error"] for item in records if item.get("score_error") is not None]
    metrics: dict[str, float] = {
        "schema_pass_rate": round(_mean([1.0 if item["schema_ok"] else 0.0 for item in records]), 4),
        "hallucination_rate": round(
            _mean([1.0 if item["hallucinated"] else 0.0 for item in records]), 4
        ),
        "avg_latency_ms": round(_mean([item["latency_ms"] for item in records]), 2),
        "avg_tokens": round(_mean([item["tokens"] for item in records]), 2),
    }
    if recalls:
        metrics["missing_recall"] = round(_mean(recalls), 4)
    if score_errors:
        metrics["score_mae"] = round(_mean(score_errors), 4)
    return metrics


async def evaluate(
    datasets: Sequence[Dataset],
    prompts: PromptBundle,
    router: ModelRouter,
) -> dict[str, Any]:
    """Run every sample in dataset order and return per-sample plus per-role metrics."""
    records: list[dict[str, Any]] = []
    by_role: dict[str, list[dict[str, Any]]] = {}

    for dataset in datasets:
        spec = TASK_SPECS[dataset.task]
        model = router.get_model(spec.role)
        for sample in dataset.samples:
            expected = sample.get("expected") or {}
            started = time.perf_counter()
            record: dict[str, Any] = {
                "id": sample["id"],
                "task": dataset.task,
                "role": spec.role,
                "schema_ok": False,
                "missing_recall": None,
                "hallucinated": False,
                "score_error": None,
                "latency_ms": 0.0,
                "tokens": 0,
                "error": None,
            }
            try:
                messages = build_messages(spec.role, prompts, sample.get("input") or {})
                response = await model.ainvoke(messages)
                text = message_text(response)
                record["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                record["tokens"] = _usage_tokens(response, text)
                payload = extract_json(text)
                parsed = spec.schema.model_validate(payload)
            except Exception as exc:  # single-sample failures must not abort the run
                record["latency_ms"] = record["latency_ms"] or round(
                    (time.perf_counter() - started) * 1000, 2
                )
                record["error"] = f"{type(exc).__name__}: {exc}"
            else:
                record["schema_ok"] = True
                produced = getattr(parsed, spec.recall_output_field, None) or []
                record["missing_recall"] = _recall(
                    expected.get(spec.expected_recall_key) or [], produced
                )
                guard = [token for token in expected.get("hallucination_guard") or [] if token]
                if guard:
                    searchable = _flatten(
                        [getattr(parsed, field, None) for field in spec.hallucination_fields]
                    ).lower()
                    record["hallucinated"] = any(token.lower() in searchable for token in guard)
                if spec.score_aware and "score" in expected:
                    dimensions = normalize_dimensions(getattr(parsed, "dimensions", None))
                    score = compute_review_score(dimensions)
                    record["score"] = score
                    record["score_error"] = abs(score - int(expected["score"]))
            by_role.setdefault(spec.role, []).append(record)
            records.append(record)

    roles: dict[str, dict[str, Any]] = {}
    for role, role_records in by_role.items():
        spec = TASK_SPECS[role_records[0]["task"]]
        roles[role] = {
            "task": spec.name,
            "sample_count": len(role_records),
            "metrics": aggregate_metrics(role_records),
        }
    return {
        "roles": roles,
        "metrics": {role: info["metrics"] for role, info in roles.items()},
        "samples": records,
    }


async def run_evaluation(
    datasets: Sequence[Dataset],
    prompts: PromptBundle,
    router: ModelRouter,
    *,
    mode: str = "baseline",
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one evaluation pass and attach provenance plus optional gate results."""
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    result = await evaluate(datasets, prompts, router)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    used_roles = set(result["metrics"])
    report: dict[str, Any] = {
        "mode": mode,
        "prompt_version": prompts.version,
        "prompt_versions": dict(prompts.versions),
        "model_names": {
            role: config.model for role, config in router.configs.items() if role in used_roles
        },
        "temperature": EVAL_TEMPERATURE,
        "dataset_hash": dataset_fingerprint(datasets),
        "dataset_versions": {item.task: item.version for item in datasets},
        "started_at": started_at.isoformat(),
        "duration_ms": duration_ms,
        "roles": result["roles"],
        "metrics": result["metrics"],
        "samples": result["samples"],
    }
    if baseline is not None:
        violations = check_gate(result["metrics"], baseline)
        report["gate"] = {"passed": not violations, "violations": violations}
    return report


def check_gate(
    metrics: Mapping[str, Mapping[str, float | None]],
    baseline: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return every metric that dropped below its baseline tolerance."""
    violations: list[dict[str, Any]] = []
    baseline_metrics = baseline.get("metrics") or {}
    for role, rules in baseline_metrics.items():
        actual_metrics = metrics.get(role) or {}
        for name, rule in (rules or {}).items():
            actual = actual_metrics.get(name)
            if actual is None:
                continue
            base = float(rule.get("baseline", 0.0))
            tolerance = float(rule.get("tolerance", 0.0))
            higher_is_better = bool(rule.get("higher_is_better", True))
            allowed = base - tolerance if higher_is_better else base + tolerance
            if higher_is_better:
                failed = actual < allowed - 1e-9
            else:
                failed = actual > allowed + 1e-9
            if failed:
                violations.append(
                    {
                        "role": role,
                        "metric": name,
                        "baseline": round(base, 4),
                        "tolerance": round(tolerance, 4),
                        "allowed": round(allowed, 4),
                        "actual": round(float(actual), 4),
                        "delta": round(float(actual) - base, 4),
                    }
                )
    return violations


def compare_runs(
    a_report: Mapping[str, Any],
    b_report: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
    *,
    epsilon: float = 1e-9,
) -> dict[str, Any]:
    """Compare two evaluation runs metric by metric and derive a verdict."""
    deltas: list[dict[str, Any]] = []
    wins_a = wins_b = ties = 0

    a_metrics = a_report.get("metrics") or {}
    b_metrics = b_report.get("metrics") or {}
    baseline_metrics = (baseline or {}).get("metrics") or {}

    for role in sorted(set(a_metrics) & set(b_metrics)):
        for name in sorted(set(a_metrics[role]) & set(b_metrics[role])):
            if name in NON_COMPARABLE_METRICS:
                continue
            a_value = a_metrics[role][name]
            b_value = b_metrics[role][name]
            if a_value is None or b_value is None:
                continue
            rule = (baseline_metrics.get(role) or {}).get(name) or {}
            higher_is_better = bool(rule.get("higher_is_better", True))
            delta = float(b_value) - float(a_value)
            if abs(delta) <= epsilon:
                winner = "tie"
                ties += 1
            elif (delta > 0) == higher_is_better:
                winner = "B"
                wins_b += 1
            else:
                winner = "A"
                wins_a += 1
            deltas.append(
                {
                    "role": role,
                    "metric": name,
                    "higher_is_better": higher_is_better,
                    "a": a_value,
                    "b": b_value,
                    "delta": round(delta, 4),
                    "winner": winner,
                }
            )

    if not deltas or (wins_a == 0 and wins_b == 0):
        verdict = "no significant difference"
        winner = "none"
    elif wins_b and not wins_a:
        verdict = "B is better"
        winner = "B"
    elif wins_a and not wins_b:
        verdict = "A is better"
        winner = "A"
    else:
        verdict = "mixed results; review the metric deltas"
        winner = "mixed"

    comparison: dict[str, Any] = {
        "deltas": deltas,
        "wins": {"A": wins_a, "B": wins_b, "ties": ties},
        "winner": winner,
        "verdict": verdict,
    }
    if baseline is not None:
        comparison["gate"] = {
            "a": check_gate(a_metrics, baseline),
            "b": check_gate(b_metrics, baseline),
        }
    return comparison


def build_router(settings: Settings) -> ModelRouter:
    """Build a router whose models always use the fixed evaluation temperature."""
    config_path = Path(settings.models_config_path)
    configs = load_models_config(config_path)
    frozen: dict[str, RoleConfig] = {
        role: config.model_copy(update={"temperature": EVAL_TEMPERATURE})
        for role, config in configs.items()
    }
    return ModelRouter(
        config_path,
        configs=frozen,
        api_key=settings.llm_api_key or None,
        base_url=settings.llm_base_url,
    )


def write_report(report: Mapping[str, Any], reports_dir: Path | str, mode: str) -> Path:
    directory = Path(reports_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"report-{stamp}-{mode}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_summary(report: Mapping[str, Any]) -> str:
    lines = [
        f"mode={report.get('mode')} prompt_version={report.get('prompt_version')} "
        f"dataset_hash={str(report.get('dataset_hash'))[:12]}"
    ]
    for role, info in sorted((report.get("roles") or {}).items()):
        metrics = info.get("metrics") or {}
        rendered = ", ".join(
            f"{name}={value}" for name, value in sorted(metrics.items()) if value is not None
        )
        lines.append(f"- {role} ({info.get('task')}, n={info.get('sample_count')}): {rendered}")
    gate = report.get("gate")
    if gate:
        lines.append(f"gate: {'passed' if gate['passed'] else 'FAILED'}")
        for violation in gate.get("violations") or []:
            lines.append(
                f"  ! {violation['role']}.{violation['metric']} actual={violation['actual']} "
                f"allowed={violation['allowed']} delta={violation['delta']}"
            )
    return "\n".join(lines)


def _load_baseline(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    baseline_path = Path(path)
    if not baseline_path.exists():
        raise EvalError(f"baseline not found: {baseline_path}")
    return json.loads(baseline_path.read_text(encoding="utf-8"))


def _verify_prompt_version(prompts: PromptBundle, requested: str | None) -> None:
    if requested and requested != prompts.version:
        raise EvalError(
            f"prompt version mismatch: requested {requested}, loaded {prompts.version}"
        )


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    datasets = load_datasets(args.datasets_dir)
    baseline = None if args.no_gate else _load_baseline(args.baseline)

    prompts_a = load_prompts(args.prompts_dir)
    _verify_prompt_version(prompts_a, args.prompt_version)
    router = build_router(settings)

    report_a = await run_evaluation(
        datasets, prompts_a, router, mode="ab-a" if args.ab_prompts_dir else "baseline",
        baseline=baseline,
    )

    if args.ab_prompts_dir:
        prompts_b = load_prompts(args.ab_prompts_dir)
        report_b = await run_evaluation(
            datasets, prompts_b, router, mode="ab-b", baseline=baseline
        )
        comparison = compare_runs(report_a, report_b, baseline)
        combined = {
            "mode": "ab",
            "dataset_hash": report_a["dataset_hash"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "temperature": EVAL_TEMPERATURE,
            "a": report_a,
            "b": report_b,
            "comparison": comparison,
        }
        path = write_report(combined, args.reports_dir, "ab")
        print(format_summary(report_a))
        print(f"A/B verdict: {comparison['verdict']} (wins {comparison['wins']})")
        print(f"report: {path}")
        candidate_gate = (comparison.get("gate") or {}).get("b") or []
        return 0 if not candidate_gate else 1

    path = write_report(report_a, args.reports_dir, "baseline")
    print(format_summary(report_a))
    print(f"report: {path}")
    if report_a.get("gate") and not report_a["gate"]["passed"]:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline prompt regression evaluation")
    parser.add_argument("--datasets-dir", default=str(DEFAULT_DATASETS_DIR))
    parser.add_argument("--prompts-dir", default=None, help="prompt set to evaluate (A)")
    parser.add_argument(
        "--prompt-version",
        default=None,
        help="assert the loaded prompt set matches this version hash",
    )
    parser.add_argument(
        "--ab-prompts-dir", default=None, help="second prompt set for A/B comparison (B)"
    )
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE_PATH))
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR))
    parser.add_argument("--no-gate", action="store_true", help="skip the baseline gate")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.prompts_dir is None:
        args.prompts_dir = str(Settings().prompts_dir)
    try:
        return asyncio.run(_run(args))
    except EvalError as exc:
        print(f"eval failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
