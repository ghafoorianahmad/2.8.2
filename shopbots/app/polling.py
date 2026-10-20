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
from .platforms import BotApiError, PlatformAdapter
from .store import Store

logger = logging.getLogger("shopbots.polling")

MAX_BACKOFF = 60.0
#: While a platform stays unreachable, repeat the error line every N failures.
ERROR_LOG_EVERY = 20
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
    failures = 0
    try:
        while not stop_event.is_set():
            try:
                offset = store.get_last_update_id(platform) + 1
                updates = await adapter.get_updates(offset=offset, timeout=settings.poll_timeout)
                if failures:
                    logger.info(
                        "platform=%s connection restored after %s failed attempts / "
                        "اتصال دوباره برقرار شد", platform, failures,
                    )
                failures = 0
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
                failures += 1
                if failures == 1 or failures % ERROR_LOG_EVERY == 0:
                    _log_poll_error(platform, exc, error, failures, backoff)
                health.mark_error(platform, error)
                await sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
    finally:
        health.mark_stopped(platform)
    logger.info("platform=%s stopped", platform)


def _log_poll_error(platform: str, exc: Exception, error: str, failures: int,
                    backoff: float) -> None:
    """One clear English + Persian line; never a URL, never the token."""
    if isinstance(exc, BotApiError) and exc.network:
        logger.error(
            "platform=%s cannot reach the Bot API (%s); retrying with backoff up to %ss "
            "[attempt %s] / %s در دسترس نیست (پروکسی یا اینترنت)؛ تلاش دوباره خودکار",
            platform, error, int(MAX_BACKOFF), failures, platform,
        )
    elif isinstance(exc, BotApiError) and "409" in exc.description:
        logger.error(
            "platform=%s poll_error=%s - another copy of this bot (or a webhook) is using "
            "the same token / نمونهٔ دیگری از ربات با همین توکن در حال اجراست",
            platform, error,
        )
    elif isinstance(exc, BotApiError) and "401" in exc.description:
        logger.error(
            "platform=%s poll_error=%s - the bot token is wrong or revoked / توکن ربات نامعتبر است",
            platform, error,
        )
    else:
        logger.warning("platform=%s poll_error=%s [attempt %s]", platform, error, failures)


async def events_loop(
    *,
    engine: BotEngine,
    settings: Settings,
    stop_event: asyncio.Event,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    """v2.8.2: ShopAdmin -> customer within seconds. The feed is read every
    ``EVENTS_POLL_SECONDS`` (cheap: only events after the saved cursor); before,
    it was read only with the 30-second admin sweep."""
    while not stop_event.is_set():
        try:
            await engine.notify_customers_from_events()
        except Exception as exc:
            logger.warning("events_error=%s", _safe_error(exc))
        await sleep(settings.events_poll_seconds)


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
