from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from app.db import init_db
from scripts.cleanup_legacy_checkpoints import (
    checkpoint_time,
    find_legacy_threads,
    run_cleanup,
)

OLD_UUID = "c232ab00-9414-11ec-b3c8-9f6bdeced846"


def _ensure_checkpoint_tables(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            );
            CREATE TABLE IF NOT EXISTS writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                type TEXT,
                value BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
            );
            """
        )


def _insert_checkpoint(
    db_path: Path, thread_id: str, checkpoint_id: str
) -> None:
    _ensure_checkpoint_tables(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO checkpoints "
            "(thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) "
            "VALUES (?, '', ?, NULL, 'msgpack', ?, ?)",
            (thread_id, checkpoint_id, b"", b""),
        )
        connection.commit()


def _count(db_path: Path, table: str, thread_id: str) -> int:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE thread_id = ?", (thread_id,)
        ).fetchone()[0]


def test_checkpoint_time_parses_version_1_ids() -> None:
    parsed = checkpoint_time(OLD_UUID)
    assert parsed is not None
    assert parsed.year == 2022
    assert checkpoint_time("not-a-uuid") is None


def test_legacy_threads_exclude_owned_and_respect_age(settings) -> None:
    init_db(settings.checkpoint_db_path)
    _insert_checkpoint(settings.checkpoint_db_path, "legacy-old", OLD_UUID)
    _insert_checkpoint(settings.checkpoint_db_path, "legacy-new", str(uuid.uuid1()))
    with sqlite3.connect(settings.checkpoint_db_path) as connection:
        connection.execute(
            "INSERT INTO runs (thread_id, user_id, title, status, created_at, updated_at, deleted_at) "
            "VALUES ('owned', 'user-1', 'owned', 'completed', '2020-01-01', '2020-01-01', NULL)"
        )
        connection.commit()
    _insert_checkpoint(settings.checkpoint_db_path, "owned", OLD_UUID)

    with sqlite3.connect(settings.checkpoint_db_path) as connection:
        assert find_legacy_threads(connection, 0) == ["legacy-new", "legacy-old"]
        assert find_legacy_threads(connection, 30) == ["legacy-old"]


def test_dry_run_keeps_checkpoints_and_logs(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite3"
    init_db(db_path)
    _insert_checkpoint(db_path, "legacy-1", OLD_UUID)
    audit = tmp_path / "audit.log"

    summary = run_cleanup(
        db_path=db_path,
        older_than_days=0,
        dry_run=True,
        audit_log=audit,
    )
    assert summary["candidates"] == 1
    assert summary["deleted"] == 0
    assert _count(db_path, "checkpoints", "legacy-1") == 1
    record = json.loads(audit.read_text(encoding="utf-8").strip())
    assert record["mode"] == "dry-run"
    assert "resume" not in audit.read_text(encoding="utf-8").lower()


def test_delete_is_idempotent_and_batched(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite3"
    init_db(db_path)
    for index in range(5):
        _insert_checkpoint(db_path, f"legacy-{index}", OLD_UUID)
    audit = tmp_path / "audit.log"

    first = run_cleanup(
        db_path=db_path, older_than_days=0, batch_size=2, dry_run=False, audit_log=audit
    )
    assert first["deleted"] == 5
    assert first["batches"] == 3
    for index in range(5):
        assert _count(db_path, "checkpoints", f"legacy-{index}") == 0

    second = run_cleanup(
        db_path=db_path, older_than_days=0, batch_size=2, dry_run=False, audit_log=audit
    )
    assert second["deleted"] == 0
    assert second["candidates"] == 0


def test_orphan_checkpoint_is_invisible_and_untouched(fake_client, settings) -> None:
    _insert_checkpoint(settings.checkpoint_db_path, "orphan", OLD_UUID)
    assert fake_client.get("/api/sessions").json()["total"] == 0
    assert fake_client.get("/api/runs/orphan").status_code == 404
    assert fake_client.post("/api/runs/orphan/resume").status_code == 404
    assert fake_client.get("/api/runs/orphan/snapshots").status_code == 404
    assert fake_client.delete("/api/sessions/orphan").status_code == 404
    assert fake_client.delete("/api/sessions/orphan/purge").status_code == 404
    assert _count(settings.checkpoint_db_path, "checkpoints", "orphan") == 1


def test_purge_expired_trash(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite3"
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO runs (thread_id, user_id, title, status, created_at, updated_at, deleted_at) "
            "VALUES ('trashed', 'user-1', 'old', 'completed', '2020-01-01', '2020-01-01', "
            "'2020-01-01T00:00:00+00:00')"
        )
        connection.commit()
    _insert_checkpoint(db_path, "trashed", OLD_UUID)

    summary = run_cleanup(
        db_path=db_path,
        older_than_days=0,
        dry_run=False,
        audit_log=tmp_path / "audit.log",
        purge_expired_trash=True,
        trash_retention_days=30,
    )
    assert summary["expired_trash"] == 1
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert rows == 0
    assert _count(db_path, "checkpoints", "trashed") == 0
