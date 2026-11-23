from __future__ import annotations

import statistics
import time
from datetime import datetime, timezone

from app.config import Settings
from app.db import connect, init_db
from app.memory.repository import set_enabled, upsert_memory
from app.memory.retrieval import retrieve_memories

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
KINDS = ("fact", "goal", "preference", "constraint")


def test_retrieval_p95_stays_fast_with_1000_memories(tmp_path) -> None:
    settings = Settings(checkpoint_db_path=tmp_path / "perf.sqlite3")
    init_db(settings.checkpoint_db_path)
    with connect(settings.checkpoint_db_path) as connection:
        set_enabled(connection, "u1", True, now=NOW)
        for index in range(1000):
            upsert_memory(
                connection,
                user_id="u1",
                kind=KINDS[index % len(KINDS)],
                content=f"熟悉 Python 与数据分析岗位，累计经验 {index} 个项目",
                confidence=0.8,
                settings=settings,
                now=NOW,
            )

        samples: list[float] = []
        for _ in range(30):
            started = time.perf_counter()
            results = retrieve_memories(
                connection,
                user_id="u1",
                query="Python 数据分析 项目",
                settings=settings,
            )
            samples.append(time.perf_counter() - started)
            assert results

    measured = samples[5:]
    p95 = sorted(measured)[max(0, int(len(measured) * 0.95) - 1)]
    assert statistics.median(measured) < 0.05
    assert p95 < 0.05
