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


class WarnOnce:
    """At most one "slow down" message per chat and window (v2.6.0: a flood of
    taps used to get the warning once per refused update)."""

    def __init__(self, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.window = float(window)
        self._clock = clock
        self._last: dict[tuple[str, str], float] = {}

    def should_warn(self, platform: str, chat_id: str | int) -> bool:
        key = (platform, str(chat_id))
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self.window:
            return False
        self._last[key] = now
        if len(self._last) > 5000:
            self._last = {k: v for k, v in self._last.items() if now - v < self.window}
        return True
