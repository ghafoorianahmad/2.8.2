"""Per-platform long polling and the admin sweep loop.

Every platform runs in its own asyncio task with exponential backoff, so a
failure or downtime of one platform never stops the other.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from . import health
from .config import Settings
from .engine import BotEngine, _safe_error
from .platforms import PlatformAdapter
from .store import Store

logger = logging.getLogger("shopbots.polling")

MAX_BACKOFF = 60.0
# Long polling normally blocks on the server, but an immediate empty answer must
# not turn the loop into a busy spin (it would starve the other platform's task).
IDLE_POLL_SLEEP = 0.5
SleepFn = Callable[[float], Awaitable[None]]


async def poll_platform(
    *,
    platform: str,
    adapter: PlatformAdapter,
    engine: BotEngine,
    store: Store,
    settings: Settings,
    stop_event: asyncio.Event,
    dry_run: bool = False,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    if dry_run:
        logger.info("platform=%s started dry_run=true", platform)
        return
    logger.info("platform=%s started", platform)
    health.mark_started(platform)
    backoff = 1.0
    try:
        while not stop_event.is_set():
            try:
                offset = store.get_last_update_id(platform) + 1
                updates = await adapter.get_updates(offset=offset, timeout=settings.poll_timeout)
                backoff = 1.0
                health.mark_ok(platform)
                if not updates:
                    # Always yield, even when the server answered immediately.
                    await sleep(IDLE_POLL_SLEEP)
                    continue
                for update in updates:
                    if stop_event.is_set():
                        break
                    await engine.handle_update(platform, update)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = _safe_error(exc)
                logger.warning("platform=%s poll_error=%s", platform, error)
                health.mark_error(platform, error)
                await sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
    finally:
        health.mark_stopped(platform)
    logger.info("platform=%s stopped", platform)


async def admin_sweep_loop(
    *,
    engine: BotEngine,
    settings: Settings,
    stop_event: asyncio.Event,
    sleep: SleepFn = asyncio.sleep,
    run_immediately: bool = True,
) -> None:
    async def once() -> None:
        try:
            await engine.admin_sweep()
        except Exception as exc:
            logger.warning("admin_sweep_error=%s", _safe_error(exc))

    if run_immediately:
        await once()
    while not stop_event.is_set():
        await sleep(settings.admin_sweep_seconds)
        if stop_event.is_set():
            break
        await once()
