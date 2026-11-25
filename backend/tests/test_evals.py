"""Tests for the offline prompt evaluation harness (evals/run.py)."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.config.model_router import ROLES, ModelRouter, RoleConfig
from app.prompts.loader import load_prompts

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.run import (  # noqa: E402
    EVAL_TEMPERATURE,
    EvalError,
    check_gate,
    compare_runs,
    dataset_fingerprint,
    evaluate,
    load_datasets,
    run_evaluation,
)
from tests.fakes import FakeModels  # noqa: E402

REAL_DATASETS_DIR = ROOT / "evals" / "datasets"


def _handlers(
    *,
    analyst_output: str | None = None,
    reviewer_missing: tuple[str, ...] = ("Kubernetes",),
):
    def analyst(messages):
        if analyst_output is not None:
            return analyst_output
        return json.dumps({"title": "Backend Engineer", "must_have": ["Python"], "keywords": ["Python"]})

    def reviewer(messages):
        dimensions = {name: 80 for name in ("skills", "experience", "projects", "education")}
        return json.dumps(
            {
                "dimensions": dimensions,
                "matched": ["Python"],
                "missing": list(reviewer_missing),
                "issues": [],
            }
        )

    def optimizer(messages):
        return json.dumps(
            {
                "variant_text": "Python backend engineer with REST API experience.",
                "changes": ["reordered baseline facts"],
                "remaining_gaps": ["Kubernetes"],
            }
        )

    return {"job_analyst": analyst, "resume_reviewer": reviewer, "resume_optimizer": optimizer}


def _router(handlers) -> ModelRouter:
    models = FakeModels(handlers)
    return ModelRouter(
        Path("unused-models.yaml"),
        configs={role: RoleConfig(model=role, temperature=EVAL_TEMPERATURE) for role in ROLES},
        model_factory=models.factory,
    )


def _write_datasets(directory: Path) -> None:
    samples = {
        "job_analysis": {
            "version": "1.0.0",
            "task": "job_analysis",
            "samples": [
                {
                    "id": "ja-1",
                    "input": {"job_title": "Backend Engineer", "job_text": "Python backend role"},
                    "expected": {"must_have": ["Python"], "hallucination_guard": []},
                }
            ],
        },
        "resume_review": {
            "version": "1.0.0",
            "task": "resume_review",
            "samples": [
                {
                    "id": "rr-1",
                    "input": {
                        "goal": "后端",
                        "profile_json": {"title": "Backend Engineer"},
                        "resume_text": "Python backend engineer",
                    },
                    "expected": {
                        "missing": ["Kubernetes"],
                        "score": 80,
                        "hallucination_guard": [],
                    },
                }
            ],
        },
        "resume_optimization": {
            "version": "1.0.0",
            "task": "resume_optimization",
            "samples": [
                {
                    "id": "ro-1",
                    "input": {
                        "goal": "后端",
                        "profile_json": {"title": "Backend Engineer"},
                        "review_json": {"missing": ["Kubernetes"]},
                        "baseline_resume": "Python backend engineer",
                    },
                    "expected": {
                        "remaining_gaps": ["Kubernetes"],
                        "hallucination_guard": ["Kubernetes"],
                    },
                }
            ],
        },
    }
    for task, payload in samples.items():
        (directory / f"{task}.json").write_text(json.dumps(payload), encoding="utf-8")


def _baseline(tmp_path: Path) -> dict:
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "metrics": {
                    "job_analyst": {
                        "schema_pass_rate": {"baseline": 1.0, "tolerance": 0.0},
                        "missing_recall": {"baseline": 1.0, "tolerance": 0.0},
                        "hallucination_rate": {
                            "baseline": 0.0,
                            "tolerance": 0.0,
                            "higher_is_better": False,
                        },
                        "avg_tokens": {
                            "baseline": 10000,
                            "tolerance": 10000,
                            "higher_is_better": False,
                        },
                    },
                    "resume_reviewer": {
                        "schema_pass_rate": {"baseline": 1.0, "tolerance": 0.0},
                        "missing_recall": {"baseline": 1.0, "tolerance": 0.0},
                        "hallucination_rate": {
                            "baseline": 0.0,
                            "tolerance": 0.0,
                            "higher_is_better": False,
                        },
                        "score_mae": {
                            "baseline": 0.0,
                            "tolerance": 0.0,
                            "higher_is_better": False,
                        },
                    },
                    "resume_optimizer": {
                        "schema_pass_rate": {"baseline": 1.0, "tolerance": 0.0},
                        "missing_recall": {"baseline": 1.0, "tolerance": 0.0},
                        "hallucination_rate": {
                            "baseline": 0.0,
                            "tolerance": 0.0,
                            "higher_is_better": False,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def datasets_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "datasets"
    directory.mkdir()
    _write_datasets(directory)
    return directory


def test_real_datasets_cover_all_three_tasks() -> None:
    datasets = load_datasets(REAL_DATASETS_DIR)
    assert {item.task for item in datasets} == {
        "job_analysis",
        "resume_review",
        "resume_optimization",
    }
    ids = [sample["id"] for item in datasets for sample in item.samples]
    assert len(ids) == len(set(ids))
    for item in datasets:
        for sample in item.samples:
            assert sample["expected"]
        assert item.version


def test_dataset_fingerprint_tracks_version_and_content() -> None:
    datasets = load_datasets(REAL_DATASETS_DIR)
    original = dataset_fingerprint(datasets)
    assert original == dataset_fingerprint(load_datasets(REAL_DATASETS_DIR))

    bumped = [replace(datasets[0], version="9.9.9"), *datasets[1:]]
    assert dataset_fingerprint(bumped) != original


def test_dataset_missing_task_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "partial"
    directory.mkdir()
    (directory / "job_analysis.json").write_text(
        json.dumps(
            {
                "version": "1",
                "task": "job_analysis",
                "samples": [
                    {"id": "ja-1", "input": {}, "expected": {"must_have": []}}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvalError):
        load_datasets(directory)


async def test_evaluation_reports_metrics_in_dataset_order(datasets_dir: Path, settings) -> None:
    datasets = load_datasets(datasets_dir)
    prompts = load_prompts(settings.prompts_dir)
    result = await evaluate(datasets, prompts, _router(_handlers()))

    assert [sample["id"] for sample in result["samples"]] == ["ja-1", "ro-1", "rr-1"]
    assert result["metrics"]["job_analyst"]["schema_pass_rate"] == 1.0
    assert result["metrics"]["job_analyst"]["missing_recall"] == 1.0
    assert result["metrics"]["resume_reviewer"]["score_mae"] == 0.0
    assert result["metrics"]["resume_optimizer"]["hallucination_rate"] == 0.0


async def test_baseline_gate_passes(datasets_dir: Path, settings, tmp_path: Path) -> None:
    datasets = load_datasets(datasets_dir)
    prompts = load_prompts(settings.prompts_dir)
    report = await run_evaluation(
        datasets, prompts, _router(_handlers()), baseline=_baseline(tmp_path)
    )
    assert report["gate"] == {"passed": True, "violations": []}
    assert report["prompt_version"] == prompts.version
    assert report["dataset_hash"] == dataset_fingerprint(datasets)
    assert report["temperature"] == 0.0
    assert report["model_names"]["job_analyst"] == "job_analyst"


async def test_regression_below_tolerance_is_flagged(datasets_dir: Path, settings, tmp_path: Path) -> None:
    datasets = load_datasets(datasets_dir)
    prompts = load_prompts(settings.prompts_dir)
    report = await run_evaluation(
        datasets,
        prompts,
        _router(_handlers(reviewer_missing=("Go",))),
        baseline=_baseline(tmp_path),
    )
    violations = report["gate"]["violations"]
    assert report["gate"]["passed"] is False
    assert [item["metric"] for item in violations] == ["missing_recall"]
    assert violations[0]["role"] == "resume_reviewer"
    assert violations[0]["actual"] == 0.0
    assert violations[0]["allowed"] == 1.0


async def test_schema_failure_does_not_abort_other_samples(datasets_dir: Path, settings) -> None:
    datasets = load_datasets(datasets_dir)
    prompts = load_prompts(settings.prompts_dir)
    result = await evaluate(datasets, prompts, _router(_handlers(analyst_output="not json")))

    assert result["metrics"]["job_analyst"]["schema_pass_rate"] == 0.0
    assert result["samples"][0]["schema_ok"] is False
    assert result["samples"][0]["error"]
    assert result["metrics"]["resume_reviewer"]["schema_pass_rate"] == 1.0
    assert len(result["samples"]) == 3


async def test_ab_with_identical_prompts_is_reproducible(datasets_dir: Path, settings) -> None:
    datasets = load_datasets(datasets_dir)
    prompts = load_prompts(settings.prompts_dir)

    first = await run_evaluation(datasets, prompts, _router(_handlers()), mode="ab-a")
    second = await run_evaluation(datasets, prompts, _router(_handlers()), mode="ab-b")
    comparison = compare_runs(first, second)

    assert EVAL_TEMPERATURE == 0.0
    assert all(item["a"] == item["b"] for item in comparison["deltas"])
    assert comparison["winner"] == "none"
    assert comparison["verdict"] == "no significant difference"


def test_check_gate_respects_metric_direction() -> None:
    baseline = {
        "metrics": {
            "resume_reviewer": {
                "hallucination_rate": {
                    "baseline": 0.1,
                    "tolerance": 0.05,
                    "higher_is_better": False,
                },
                "missing_recall": {"baseline": 0.8, "tolerance": 0.1},
            }
        }
    }
    assert check_gate({"resume_reviewer": {"hallucination_rate": 0.14, "missing_recall": 0.7}}, baseline) == []

    violations = check_gate(
        {"resume_reviewer": {"hallucination_rate": 0.4, "missing_recall": 0.5}}, baseline
    )
    assert {item["metric"] for item in violations} == {"hallucination_rate", "missing_recall"}
