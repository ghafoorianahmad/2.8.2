"""Per-user sliding-window rate limiter (in memory, single process)."""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        max_events: int = 20,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_events = int(max_events)
        self.window = float(window)
        self._clock = clock
        self._buckets: dict[tuple[str, str], deque[float]] = {}

    def allow(self, platform: str, chat_id: str | int) -> bool:
        key = (platform, str(chat_id))
        now = self._clock()
        bucket = self._buckets.setdefault(key, deque())
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.max_events:
            return False
        bucket.append(now)
        return True

    def reset(self, platform: str | None = None, chat_id: str | int | None = None) -> None:
        if platform is None:
            self._buckets.clear()
            return
        self._buckets.pop((platform, str(chat_id)), None)
