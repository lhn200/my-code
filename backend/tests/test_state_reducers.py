from __future__ import annotations

from app.state import (
    compute_review_score,
    merge_by_job_id,
    merge_by_review_key,
    merge_errors,
    merge_interview_reports,
    merge_rounds,
    merge_variants,
    normalize_dimensions,
    review_key,
)


def test_merge_by_job_id_keeps_latest() -> None:
    merged = merge_by_job_id({"a": 1, "b": 2}, {"b": 3, "c": 4})
    assert merged == {"a": 1, "b": 3, "c": 4}


def test_merge_by_review_key_isolates_versions() -> None:
    left = {review_key("job-1", 0): {"score": 60}}
    right = {review_key("job-1", 1): {"score": 80}}
    merged = merge_by_review_key(left, right)
    assert set(merged) == {review_key("job-1", 0), review_key("job-1", 1)}


def test_merge_variants_does_not_overwrite_other_jobs() -> None:
    left = {"job-1": [{"job_id": "job-1", "variant_version": 1, "text": "a"}]}
    right = {"job-2": [{"job_id": "job-2", "variant_version": 1, "text": "b"}]}
    merged = merge_variants(left, right)
    assert merged["job-1"][0]["text"] == "a"
    assert merged["job-2"][0]["text"] == "b"


def test_merge_variants_keeps_latest_and_sorts() -> None:
    left = {
        "job-1": [
            {"job_id": "job-1", "variant_version": 2, "text": "old2"},
            {"job_id": "job-1", "variant_version": 1, "text": "old1"},
        ]
    }
    right = {"job-1": [{"job_id": "job-1", "variant_version": 2, "text": "new2"}]}
    merged = merge_variants(left, right)
    assert [item["variant_version"] for item in merged["job-1"]] == [1, 2]
    assert merged["job-1"][1]["text"] == "new2"


def test_merge_rounds_prefers_scored_round() -> None:
    left = [{"job_id": "job-1", "round": 1, "variant_version": 1, "score_before": 60, "score_after": None}]
    right = [{"job_id": "job-1", "round": 1, "variant_version": 1, "score_before": 60, "score_after": 85}]
    merged = merge_rounds(left, right)
    assert len(merged) == 1
    assert merged[0]["score_after"] == 85


def test_merge_interview_reports_keeps_latest_and_is_idempotent() -> None:
    old = {"job-1": {"interview_thread_id": "t1", "generated_at": "2026-01-01", "status": "abandoned"}}
    new = {"job-1": {"interview_thread_id": "t2", "generated_at": "2026-01-02", "status": "completed"}}
    merged = merge_interview_reports(old, new)
    assert merged["job-1"]["interview_thread_id"] == "t2"
    repeated = merge_interview_reports(merged, new)
    assert repeated["job-1"]["interview_thread_id"] == "t2"
    stale = merge_interview_reports(new, old)
    assert stale["job-1"]["interview_thread_id"] == "t2"


def test_merge_errors_deduplicates() -> None:
    left = [{"stage": "a", "job_id": "j", "message": "m"}]
    right = [{"stage": "a", "job_id": "j", "message": "m"}]
    assert len(merge_errors(left, right)) == 1


def test_score_is_weighted_dimensions() -> None:
    dimensions = normalize_dimensions(
        {"skills": 90, "experience": 70, "projects": 50, "education": 10, "extra": 100}
    )
    assert dimensions == {"skills": 90, "experience": 70, "projects": 50, "education": 10}
    assert compute_review_score(dimensions) == int(round(0.4 * 90 + 0.3 * 70 + 0.2 * 50 + 0.1 * 10))
