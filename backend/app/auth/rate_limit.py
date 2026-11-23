"""In-process fixed-window rate limiting for login attempts."""

from __future__ import annotations

import threading
import time
from typing import Callable


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after


class LoginRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[float, int]] = {}

    def check(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= self.window_seconds:
                window_start, count = now, 0
            if count >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - window_start)))
                raise RateLimitExceeded(retry_after)
            self._buckets[key] = (window_start, count + 1)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


__all__ = ["LoginRateLimiter", "RateLimitExceeded"]
