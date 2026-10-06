"""Robustness: idempotency, rate limiting, callback validation, isolation, logs."""
from __future__ import annotations

import asyncio
import logging

import pytest

from app import texts
from app.engine import parse_callback
from app.main import build_adapters, run
from app.polling import poll_platform
from app.ratelimit import RateLimiter
from app.shopapi import ShopApiError
from app.store import Store

from .conftest import (
    ADMIN_CHAT,
    BALE_TOKEN,
    CUSTOMER_CHAT,
    TELEGRAM_TOKEN,
    bot_env,
    message_update,
    push_callback,
    push_message,
)


# ---- callback validation (pure) -------------------------------------------
def test_parse_callback_accepts_valid_payloads():
    assert parse_callback("menu") == ("menu", [])
    assert parse_callback("grp:12") == ("grp", [12])
    assert parse_callback("qty:101:3") == ("qty", [101, 3])
    assert parse_callback("adsug:5:7001") == ("adsug", [5, 7001])


def test_parse_callback_rejects_malformed_payloads():
    for bad in (
        None, "", "nope", "grp", "grp:abc", "grp:-1", "grp:1:2",
        "qty:1", "menu:1", "x" * 65, 123, "drop:1",
    ):
        assert parse_callback(bad) is None, bad


def test_malformed_callbacks_are_answered_but_ignored(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        for index, bad in enumerate(["nope", "add:1", "qty:1:2:3", "grp:abc", "x" * 100, ""], 1):
            await push_callback(engine, "bale", index, CUSTOMER_CHAT, bad)
        assert bot_apis["bale"].answered
        assert all(a.get("text") == texts.BAD_CALLBACK for a in bot_apis["bale"].answered)
        # no product screen was opened
        assert not any("کالاها" in t for t in bot_apis["bale"].texts(CUSTOMER_CHAT))

    env(scenario)


# ---- idempotent update handling -------------------------------------------
def test_the_same_update_is_handled_only_once(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        update = message_update(7, CUSTOMER_CHAT, text="/start")
        assert await engine.handle_update("bale", update) is True
        sent = len(bot_apis["bale"].sent)
        assert sent == 1

        assert await engine.handle_update("bale", update) is False       # replay
        assert len(bot_apis["bale"].sent) == sent
        assert await engine.handle_update("bale", message_update(3, CUSTOMER_CHAT, text="/start")) is False
        assert len(bot_apis["bale"].sent) == sent

        await engine.handle_update("bale", message_update(8, CUSTOMER_CHAT, text="/start"))
        assert len(bot_apis["bale"].sent) == sent + 1

    env(scenario)


def test_last_update_id_is_persisted_per_platform(env, settings, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 10, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "telegram", 4, CUSTOMER_CHAT, text="/start")
        assert engine.store.get_last_update_id("bale") == 10
        assert engine.store.get_last_update_id("telegram") == 4
        # a restart keeps the offsets
        fresh = Store(":memory:")
        assert fresh.get_last_update_id("bale") == 0

    env(scenario)


# ---- rate limiting ---------------------------------------------------------
def test_rate_limit_per_user(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    clock = [0.0]
    limiter = RateLimiter(max_events=3, window=60.0, clock=lambda: clock[0])

    async def scenario(engine, adapters, api):
        for index in range(3):
            await push_message(engine, "bale", index + 1, CUSTOMER_CHAT, text="سلام")
        assert texts.RATE_LIMITED not in bot_apis["bale"].texts(CUSTOMER_CHAT)

        await push_message(engine, "bale", 4, CUSTOMER_CHAT, text="سلام")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT) == texts.RATE_LIMITED

        clock[0] = 120.0
        await push_message(engine, "bale", 5, CUSTOMER_CHAT, text="سلام")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT) == texts.MAIN_MENU

    env(scenario, rate_limiter=limiter)


def test_rate_limit_is_per_chat(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    limiter = RateLimiter(max_events=1, window=60.0, clock=lambda: 0.0)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="سلام")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="سلام")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT) == texts.RATE_LIMITED
        # a different chat is unaffected
        await push_message(engine, "bale", 3, "7777", text="سلام")
        assert bot_apis["bale"].last_text("7777") != texts.RATE_LIMITED

    env(scenario, rate_limiter=limiter)


# ---- input handling --------------------------------------------------------
def test_group_chats_are_ignored(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        handled = await push_message(
            engine, "bale", 1, "-100200", text="/start", chat_type="group"
        )
        assert handled is False
        assert bot_apis["bale"].sent == []

    env(scenario)


def test_overlong_input_is_refused(env, settings, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="x" * (settings.max_input_len + 1))
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.TEXT_TOO_LONG

    env(scenario)


# ---- shopapi failures ------------------------------------------------------
def test_shopapi_down_gives_a_persian_message(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.down = True

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SERVICE_UNAVAILABLE

    env(scenario)


def test_shopapi_error_status_is_translated(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        # product 102 has only 5 available
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])
        assert order is not None
        with pytest.raises(ShopApiError):
            await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 102, "qty": 99}])

    env(scenario)


# ---- platform isolation ----------------------------------------------------
def test_one_platform_failing_does_not_stop_the_other(settings, store, shopapi, bot_apis):
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)
    bot_apis["bale"].raise_on = {"getUpdates"}
    bot_apis["telegram"].updates = [message_update(1, CUSTOMER_CHAT, text="/start")]

    async def scenario():
        async with bot_env(settings, store, shopapi, bot_apis) as (engine, adapters, api):
            bale_stop = asyncio.Event()
            sleeps: list[float] = []

            async def bale_sleep(seconds):
                sleeps.append(seconds)
                await asyncio.sleep(0.001)
                if len(sleeps) >= 3:
                    bale_stop.set()

            bale_task = asyncio.create_task(
                poll_platform(
                    platform="bale", adapter=adapters["bale"], engine=engine,
                    store=store, settings=settings, stop_event=bale_stop, sleep=bale_sleep,
                )
            )

            telegram_stop = asyncio.Event()
            telegram_task = asyncio.create_task(
                poll_platform(
                    platform="telegram", adapter=adapters["telegram"], engine=engine,
                    store=store, settings=settings, stop_event=telegram_stop,
                    sleep=lambda seconds: asyncio.sleep(0.001),
                )
            )

            # let both pollers run for a moment
            await asyncio.sleep(0.2)
            assert bot_apis["telegram"].sent, "telegram must keep working while bale is down"
            telegram_stop.set()

            await asyncio.wait_for(telegram_task, timeout=5)
            await asyncio.wait_for(bale_task, timeout=5)

            # telegram kept working while bale was down
            assert bot_apis["telegram"].last_text(CUSTOMER_CHAT) == texts.MAIN_MENU
            # bale backed off exponentially and never stopped the process
            assert sleeps[0] == 1.0
            assert sleeps[1] == 2.0
            assert len(bot_apis["bale"].calls) >= 3

    asyncio.run(scenario())


def test_dry_run_starts_both_adapters_with_fake_tokens(env, settings, store, shopapi, bot_apis):
    real_adapters = build_adapters(settings)
    assert set(real_adapters) == {"bale", "telegram"}
    assert real_adapters["bale"].platform == "bale"
    assert real_adapters["telegram"].platform == "telegram"

    async def scenario(engine, adapters, api):
        result = await run(settings, dry_run=True, adapters=adapters, store=store, api=api)
        assert result == {"platforms": ["bale", "telegram"], "dry_run": True}
        assert bot_apis["bale"].calls == []       # dry run made no network call
        assert bot_apis["telegram"].calls == []

    env(scenario)


def test_proxy_applies_only_to_telegram(settings):
    settings.proxy_url = "socks5://127.0.0.1:1080"
    assert settings.proxy_for("bale") is None
    assert settings.proxy_for("telegram") == "socks5://127.0.0.1:1080"
    adapters = build_adapters(settings)
    assert adapters["telegram"].proxy_url == "socks5://127.0.0.1:1080"
    assert not hasattr(adapters["bale"], "proxy_url")


# ---- privacy ---------------------------------------------------------------
def test_no_token_or_phone_ever_reaches_the_logs(
    env, settings, store, bot_apis, shopapi, caplog
):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="pending", phone="09121234567")
    bot_apis["bale"].raise_on = {"getUpdates"}

    async def scenario(engine, adapters, api):
        # a message that carries a phone number as its text
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="09121234567")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "adap:1")
        stop = asyncio.Event()

        async def fake_sleep(seconds):
            stop.set()
            await asyncio.sleep(0)

        await poll_platform(
            platform="bale", adapter=adapters["bale"], engine=engine, store=store,
            settings=settings, stop_event=stop, sleep=fake_sleep,
        )

    with caplog.at_level(logging.DEBUG):
        env(scenario)

    blob = "\n".join(record.getMessage() for record in caplog.records)
    assert caplog.records, "expected some log output"
    assert BALE_TOKEN not in blob
    assert TELEGRAM_TOKEN not in blob
    assert "09121234567" not in blob
    assert "TELEGRAM_TOKEN" not in blob


def test_bot_api_error_never_contains_the_token(settings, bot_apis, shopapi):
    from app.platforms import BotApiError

    bot_apis["bale"].raise_on = {"sendMessage"}

    async def scenario():
        async with bot_env(settings, Store(":memory:"), shopapi, bot_apis) as (
            engine, adapters, api,
        ):
            with pytest.raises(BotApiError) as info:
                await adapters["bale"].send_text(CUSTOMER_CHAT, "سلام")
            assert BALE_TOKEN not in str(info.value)
            assert "network error" in str(info.value)

    asyncio.run(scenario())


def test_admin_chat_matching_is_platform_aware(settings):
    settings.admin_chat_ids = ("bale:9001", "12345")
    assert settings.is_admin_chat("bale", "9001") is True
    assert settings.is_admin_chat("telegram", "9001") is False
    assert settings.is_admin_chat("telegram", "12345") is True   # unprefixed = any platform
    assert settings.is_admin_chat("bale", "9999") is False
    assert settings.is_admin_chat("bale", ADMIN_CHAT) is True
    assert settings.is_admin_chat("bale", CUSTOMER_CHAT) is False


def test_admin_targets_expand_for_enabled_platforms(settings):
    settings.admin_chat_ids = ("bale:1", "999")
    assert settings.admin_targets(("bale", "telegram")) == [
        ("bale", "1"), ("bale", "999"), ("telegram", "999"),
    ]
    assert settings.admin_targets(("telegram",)) == [("telegram", "999")]


def test_admin_sweep_is_a_noop_without_admins(env, settings, bot_apis, shopapi):
    settings.admin_chat_ids = ()
    shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        assert await engine.admin_sweep() == {"users": 0, "orders": 0}
        assert bot_apis["bale"].sent == []
        assert shopapi.requests == []

    env(scenario)


def test_admin_sweep_survives_shopapi_being_down(env, bot_apis, shopapi):
    shopapi.down = True

    async def scenario(engine, adapters, api):
        # no exception escapes the sweep, so the poller keeps its schedule
        assert await engine.admin_sweep() == {"users": 0, "orders": 0}

    env(scenario)
