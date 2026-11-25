"""Operational cleanup for legacy checkpoints and expired trash sessions.

Usage (from `backend/`):
    python -m scripts.cleanup_legacy_checkpoints
    python -m scripts.cleanup_legacy_checkpoints --yes
    python -m scripts.cleanup_legacy_checkpoints --purge-expired-trash --yes
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.checkpoint.sqlite import delete_thread
from app.config import Settings
from app.db.connection import connect, transaction
from app.db.runs import delete_expired_trash, expired_trash


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(settings.checkpoint_db_path))
    parser.add_argument("--older-than-days", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--yes", action="store_true", default=False)
    parser.add_argument(
        "--audit-log", default=str(Path("data/audit/legacy_cleanup.log"))
    )
    parser.add_argument("--purge-expired-trash", action="store_true")
    return parser.parse_args(argv)


def checkpoint_time(checkpoint_id: str) -> datetime | None:
    """Best-effort timestamp from time-ordered checkpoint ids (UUID v1/v6)."""
    try:
        parsed = uuid.UUID(checkpoint_id)
    except (ValueError, AttributeError):
        return None
    if parsed.version not in (1, 6):
        return None
    seconds = (parsed.time - 0x01B21DD213814000) / 10_000_000
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def find_legacy_threads(
    connection: Any, older_than_days: int, now: datetime | None = None
) -> list[str]:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "checkpoints" not in tables:
        return []
    owned = {row[0] for row in connection.execute("SELECT thread_id FROM runs")}
    latest = connection.execute(
        "SELECT thread_id, MAX(checkpoint_id) AS latest FROM checkpoints GROUP BY thread_id"
    ).fetchall()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=older_than_days)
    selected: list[str] = []
    for row in latest:
        thread_id = row[0]
        if thread_id in owned:
            continue
        if older_than_days > 0:
            created = checkpoint_time(row[1] or "")
            if created is None or created > cutoff:
                continue
        selected.append(thread_id)
    return sorted(selected)


def _append_audit(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_cleanup(
    *,
    db_path: Path | str,
    older_than_days: int = 30,
    batch_size: int = 500,
    dry_run: bool = True,
    audit_log: Path | str = Path("data/audit/legacy_cleanup.log"),
    purge_expired_trash: bool = False,
    trash_retention_days: int = 30,
) -> dict[str, int]:
    db_path = Path(db_path)
    audit_path = Path(audit_log)
    with connect(db_path) as connection:
        candidates = find_legacy_threads(connection, older_than_days)

    deleted = 0
    failed = 0
    batches = 0
    for index in range(0, len(candidates), max(1, batch_size)):
        chunk = candidates[index : index + batch_size]
        batches += 1
        if dry_run:
            _append_audit(
                audit_path,
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "mode": "dry-run",
                    "batch": batches,
                    "batch_size": len(chunk),
                    "deleted": 0,
                    "failed": 0,
                },
            )
            continue
        try:
            with transaction(db_path) as connection:
                for thread_id in chunk:
                    delete_thread(connection, thread_id)
            deleted += len(chunk)
        except Exception:
            failed += len(chunk)
        _append_audit(
            audit_path,
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "mode": "delete",
                "batch": batches,
                "batch_size": len(chunk),
                "deleted": len(chunk) if failed == 0 else 0,
                "failed": failed,
            },
        )

    expired = 0
    if purge_expired_trash and not dry_run:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=trash_retention_days)
        ).isoformat()
        with connect(db_path) as connection:
            expired = len(expired_trash(connection, cutoff))
        if expired:
            delete_expired_trash(db_path, cutoff, batch_size=batch_size)
            _append_audit(
                audit_path,
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "mode": "purge-expired-trash",
                    "batch_size": expired,
                    "deleted": expired,
                    "failed": 0,
                },
            )

    return {
        "candidates": len(candidates),
        "batches": batches,
        "deleted": deleted,
        "failed": failed,
        "expired_trash": expired,
        "dry_run": int(dry_run),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings()
    summary = run_cleanup(
        db_path=args.db,
        older_than_days=args.older_than_days,
        batch_size=args.batch_size,
        dry_run=not args.yes,
        audit_log=args.audit_log,
        purge_expired_trash=args.purge_expired_trash,
        trash_retention_days=settings.trash_retention_days,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["checkpoint_time", "find_legacy_threads", "main", "run_cleanup"]
