"""Entry point: run the bots (Bale, and Telegram when configured).

    python -m app.main            # run the bot (BALE_TOKEN must be set)
    python -m app.main --dry-run  # start the adapter, no network calls
    python -m app.main --check    # print a token-free configuration summary
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .config import Settings
from .engine import BotEngine
from .logging_setup import configure_logging, silence_noisy_loggers
from .platforms import BaleAdapter, PlatformAdapter
from .polling import admin_sweep_loop, events_loop, poll_platform, staff_alerts_loop
from .shopapi import ShopApiClient
from .store import Store

logger = logging.getLogger("shopbots")

# Applied at import time: httpx logs request URLs at INFO and those URLs contain
# the bot token, so they must never be emitted (see logging_setup).
silence_noisy_loggers()


def build_adapters(settings: Settings) -> dict[str, PlatformAdapter]:
    """One adapter per configured platform. Only the base URL and flags differ."""
    adapters: dict[str, PlatformAdapter] = {}
    timeout = settings.poll_timeout + 10
    if settings.bale_token:
        adapters["bale"] = BaleAdapter(
            token=settings.bale_token, api_base=settings.bale_api_base, timeout=timeout
        )
    if settings.telegram_configured:
        try:
            adapters["telegram"] = build_telegram_adapter(settings)
        except ImportError as exc:
            logger.error(
                "TELEGRAM_BOT_TOKEN is set but Telethon / shop-tgproxy is not installed (%s) - "
                "Telegram channel disabled / کتابخانهٔ تلگرام نصب نیست", type(exc).__name__,
            )
    return adapters


def build_telegram_adapter(settings: Settings) -> PlatformAdapter:
    """Telethon bot through the proxy pool. Imported here so Bale-only installs
    (and their tests) never need Telethon."""
    from .platforms.telegram import TelethonBotAdapter
    from .platforms.tg_pool import ProxyPool

    pool = ProxyPool(
        base_url=settings.shopapi_base_url,
        worker_api_key=settings.worker_api_key,
        ca_file=settings.shopapi_ca_file,
        local_proxies=settings.tg_proxies,
        allow_direct=settings.tg_allow_direct,
    )
    return TelethonBotAdapter(
        bot_token=settings.telegram_bot_token,
        api_id=settings.tg_api_id,
        api_hash=settings.tg_api_hash,
        pool=pool,
        session_path=settings.tg_session_file,
        connect_timeout=settings.tg_connect_timeout_sec,
        health_interval=settings.tg_health_interval_sec,
    )


async def run(
    settings: Settings,
    *,
    dry_run: bool = False,
    stop_event: asyncio.Event | None = None,
    sleep=asyncio.sleep,
    adapters: dict[str, PlatformAdapter] | None = None,
    store: Store | None = None,
    api: ShopApiClient | None = None,
) -> dict:
    store = store if store is not None else Store(settings.sqlite_path)
    api = api if api is not None else ShopApiClient(settings)
    adapters = adapters if adapters is not None else build_adapters(settings)
    engine = BotEngine(settings, store, api, adapters)
    stop = stop_event if stop_event is not None else asyncio.Event()

    tasks = [
        asyncio.create_task(
            poll_platform(
                platform=platform,
                adapter=adapter,
                engine=engine,
                store=store,
                settings=settings,
                stop_event=stop,
                dry_run=dry_run,
                sleep=sleep,
            )
        )
        for platform, adapter in adapters.items()
    ]
    if not dry_run and adapters:
        tasks.append(
            asyncio.create_task(
                admin_sweep_loop(
                    engine=engine, settings=settings, stop_event=stop, sleep=sleep
                )
            )
        )
        if settings.events_poll_seconds:
            tasks.append(asyncio.create_task(events_loop(
                engine=engine, settings=settings, stop_event=stop, sleep=sleep)))
        if settings.staff_alerts_seconds:
            tasks.append(asyncio.create_task(staff_alerts_loop(
                engine=engine, settings=settings, stop_event=stop, sleep=sleep)))
    try:
        await asyncio.gather(*tasks)
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {"platforms": sorted(adapters), "dry_run": dry_run}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shopbots", description="Bale bot for shopapi")
    parser.add_argument("--dry-run", action="store_true", help="start adapters without network calls")
    parser.add_argument("--check", action="store_true", help="validate configuration and exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    configure_logging(args.log_level)
    settings = Settings.from_env()

    if args.check:
        platforms = ",".join(settings.enabled_platforms()) or "none"
        print(f"shopapi={settings.shopapi_base_url}")
        print(f"platforms={platforms}")
        print(f"admin_chats={len(settings.admin_entries())}")
        return 0

    if not settings.enabled_platforms():
        print("No bot configured. Set BALE_TOKEN or TELEGRAM_BOT_TOKEN + TG_API_ID + TG_API_HASH (see .env.example).")
        return 2

    asyncio.run(run(settings, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
