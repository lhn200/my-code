from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.checkpoint.sqlite import new_thread_id, open_checkpointer, thread_config
from app.graph.main import build_initial_state, build_main_graph
from app.main import create_app
from tests.auth_utils import authenticate
from tests.fakes import (
    DEFAULT_HANDLERS,
    FakeModels,
    analyst_handler,
    make_context,
    make_reviewer_handler,
)

JOBS = [
    {"job_id": "job-1", "title": "Backend Engineer", "original_position_text": "Python"},
    {"job_id": "job-2", "title": "Data Engineer", "original_position_text": "SQL"},
]


def _create_run(client: TestClient, goal: str = "后端") -> str:
    response = client.post(
        "/api/runs",
        json={"goal": goal, "resume_text": "Python SQL", "jobs": JOBS},
    )
    assert response.status_code == 200
    return response.json()["thread_id"]


def test_state_query_next_node_and_snapshot_read(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        thread_id = _create_run(client)
        current = client.get(f"/api/runs/{thread_id}")
        assert current.status_code == 200
        body = current.json()
        assert body["next"] == []
        assert body["state"]["goal"] == "后端"
        assert len(body["result"]["jobs"]) == 2

        listed = client.get(f"/api/runs/{thread_id}/snapshots")
        assert listed.status_code == 200
        snapshots = listed.json()["snapshots"]
        assert len(snapshots) >= 3
        steps = [item["step"] for item in snapshots]
        assert steps == sorted(steps)

        before = len(snapshots)
        snapshot_id = snapshots[0]["checkpoint_id"]
        historical = client.get(f"/api/runs/{thread_id}/snapshots/{snapshot_id}")
        assert historical.status_code == 200
        assert historical.json()["state"]["goal"] == "后端"

        after = client.get(f"/api/runs/{thread_id}/snapshots").json()["snapshots"]
        assert len(after) == before


def test_checkpoint_from_other_thread_returns_404(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        first = _create_run(client, "后端")
        second = _create_run(client, "前端")
        snapshot_id = client.get(f"/api/runs/{second}/snapshots").json()["snapshots"][-1][
            "checkpoint_id"
        ]
        response = client.get(f"/api/runs/{first}/snapshots/{snapshot_id}")
        assert response.status_code == 404


def test_state_survives_app_restart(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        thread_id = _create_run(client)
    restarted_models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=restarted_models.factory)) as client:
        authenticate(client)
        response = client.get(f"/api/runs/{thread_id}")
        assert response.status_code == 200
        assert response.json()["result"]["run_status"] == "succeeded"
    assert restarted_models.calls("job_analyst") == 0


def test_resume_completed_run_does_not_repeat_work(settings) -> None:
    models = FakeModels(DEFAULT_HANDLERS)
    with TestClient(create_app(settings, model_factory=models.factory)) as client:
        authenticate(client)
        thread_id = _create_run(client)
        analyst_calls = models.calls("job_analyst")
        reviewer_calls = models.calls("resume_reviewer")
        response = client.post(f"/api/runs/{thread_id}/resume")
        assert response.status_code == 200
        assert models.calls("job_analyst") == analyst_calls
        assert models.calls("resume_reviewer") == reviewer_calls


def test_variants_survive_app_restart(settings) -> None:
    handlers = {
        **DEFAULT_HANDLERS,
        "resume_reviewer": make_reviewer_handler({"Backend Engineer": 60}),
    }
    with TestClient(create_app(settings, model_factory=FakeModels(handlers).factory)) as client:
        authenticate(client)
        thread_id = _create_run(client)

    with TestClient(
        create_app(settings, model_factory=FakeModels(DEFAULT_HANDLERS).factory)
    ) as client:
        authenticate(client)
        body = client.get(f"/api/runs/{thread_id}").json()

    jobs = {job["job_id"]: job for job in body["result"]["jobs"]}
    backend = jobs["job-1"]
    assert backend["resume_source"] == "variant"
    assert backend["current_variant_version"] == 1
    assert "OPTIMIZED" in backend["resume_text"]
    assert [item["variant_version"] for item in backend["variants"]] == [1]


async def test_resume_after_interruption_does_not_duplicate_jobs(settings) -> None:
    async with open_checkpointer(settings.checkpoint_db_path) as saver:
        context, models = make_context(
            settings, {**DEFAULT_HANDLERS, "job_analyst": analyst_handler}
        )
        graph = build_main_graph(context, checkpointer=saver, interrupt_after=["analyze_job"])
        thread_id = new_thread_id()
        config = thread_config(thread_id)
        config["recursion_limit"] = 200

        await graph.ainvoke(build_initial_state("目标", "Python SQL", JOBS), config=config)
        interrupted = await graph.aget_state(config)
        assert interrupted.next

        await graph.ainvoke(None, config=config)
        final = await graph.aget_state(config)
        assert not final.next
        assert models.calls("job_analyst") == 2
        assert set(final.values["job_profiles"]) == {"job-1", "job-2"}


async def test_two_threads_do_not_pollute_each_other(settings) -> None:
    async with open_checkpointer(settings.checkpoint_db_path) as saver:
        context, _ = make_context(settings, DEFAULT_HANDLERS)
        graph = build_main_graph(context, checkpointer=saver)
        first, second = new_thread_id(), new_thread_id()
        config_a = thread_config(first)
        config_b = thread_config(second)

        await asyncio.gather(
            graph.ainvoke(build_initial_state("后端", "Python SQL", JOBS[:1]), config=config_a),
            graph.ainvoke(build_initial_state("前端", "Vue TS", JOBS[1:]), config=config_b),
        )
        state_a = await graph.aget_state(config_a)
        state_b = await graph.aget_state(config_b)
        assert state_a.values["goal"] == "后端"
        assert state_b.values["goal"] == "前端"
        assert set(state_a.values["job_profiles"]) == {"job-1"}
        assert set(state_b.values["job_profiles"]) == {"job-2"}
