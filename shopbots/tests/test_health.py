"""Platform health tracking used by the server status page."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app import health
from app.polling import poll_platform


class FlakyAdapter:
    """Fails twice (with a token-bearing URL in the error), then succeeds."""

    def __init__(self, stop: asyncio.Event):
        self.calls = 0
        self.stop = stop

    async def get_updates(self, offset, timeout):
        self.calls += 1
        if self.calls <= 2:
            raise RuntimeError("connect failed https://api.example/bot123:SECRET/getUpdates")
        self.stop.set()
        return []


def test_poll_records_errors_then_ok():
    health.reset()

    async def scenario():
        stop = asyncio.Event()
        adapter = FlakyAdapter(stop)
        store = SimpleNamespace(get_last_update_id=lambda platform: 0)
        settings = SimpleNamespace(poll_timeout=1)

        async def no_sleep(_seconds):
            return None

        await poll_platform(platform="bale", adapter=adapter, engine=None, store=store,
                            settings=settings, stop_event=stop, sleep=no_sleep)

    asyncio.run(scenario())
    state = health.snapshot()["bale"]
    assert state["running"] is False          # stopped cleanly
    assert state["last_ok_at"] is not None
    assert state["last_error_at"] is not None
    assert state["consecutive_errors"] == 0   # reset by the success
    assert "SECRET" not in str(state)          # errors are token-free


def test_snapshot_is_a_copy():
    health.reset()
    health.mark_started("bale")
    snap = health.snapshot()
    snap["bale"]["running"] = False
    assert health.snapshot()["bale"]["running"] is True
