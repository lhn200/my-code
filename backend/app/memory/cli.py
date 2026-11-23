"""Command line entry points for memory maintenance."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Sequence

from app.config import Settings

from .repository import archive_expired_memories


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.memory.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    expire = subparsers.add_parser("expire", help="archive memories past their TTL")
    expire.add_argument(
        "--now",
        help="override the archive cutoff time (ISO8601); defaults to the current time",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    now = None
    if args.now:
        now = datetime.fromisoformat(args.now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    if args.command == "expire":
        count = archive_expired_memories(settings.checkpoint_db_path, now=now)
        print(f"archived {count} expired memories")
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
