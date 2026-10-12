"""Phase 7: the Telegram bot channel (Telethon bot through the MTProto proxy pool).

Everything runs against a fake Telethon client, a fake proxy pool / shopapi and the
real engine: no network, no real token. The strings below are obviously fake and
exist so the tests can prove they never reach a log.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging

import httpx
import pytest
from telethon import Button
from telethon.network.connection import (
    ConnectionTcpMTProxyIntermediate,
    ConnectionTcpMTProxyRandomizedIntermediate,
)
from telethon.tl.types import ButtonTypeRequestPhone
from tgproxy import ProxyLink, parse_proxy_link
from tgproxy.faketls import ConnectionTcpMTProxyFakeTLS

from app import texts
from app.config import Settings
from app.engine import BotEngine
from app.main import build_adapters
from app.platforms import BaleAdapter, BotApiError, contact_keyboard, inline_keyboard
from app.platforms.telegram import TelethonBotAdapter, split_text, to_buttons
from app.platforms.tg_pool import ProxyPool
from app.polling import poll_platform
from app.shopapi import ShopApiClient

from .conftest import ADMIN_CHAT, CUSTOMER_CHAT, FakeBotApi, OTHER_CHAT
from .test_phase3 import PHONE
from .test_phase6b import _models
from .tg_fakes import FakePool, FakeWorld

TG_TOKEN = "987654:TESTTOKEN-TELEGRAM-0000000000000000"
TG_HASH = "deadbeefdeadbeefdeadbeefdeadbeef"
SECRET16 = "00112233445566778899aabbccddeeff"
EE_SECRET = "ee" + SECRET16 + b"cdn.example.com".hex()
DD_SECRET = "dd" + SECRET16
UID = int(CUSTOMER_CHAT)


def link(host, port, secret, pool_id=None) -> ProxyLink:
    parsed = parse_proxy_link(f"tg://proxy?server={host}&port={port}&secret={secret}")
    return ProxyLink(parsed.host, parsed.port, parsed.secret, pool_id)


def contact(user_id=UID, phone="+989121234567"):
    from types import SimpleNamespace
    return SimpleNamespace(phone_number=phone, first_name="Ali", last_name="Rezaei", user_id=user_id)


def tg_adapter(world, candidates, *, clock=None, health_interval=180.0, **kw):
    pool = FakePool(candidates)
    adapter = TelethonBotAdapter(
        bot_token=TG_TOKEN, api_id=12345, api_hash=TG_HASH, pool=pool,
        client_factory=world.factory, connect_timeout=2.0, health_interval=health_interval,
        **({"clock": clock} if clock else {}), **kw)
    return adapter, pool


def cb_data(button) -> bytes | None:
    """Callback payload of an inline button (Telethon's new-layer KeyboardInlineButton)."""
    return getattr(getattr(button, "type", None), "data", None)


def is_phone_button(button) -> bool:
    return isinstance(button.button.type, ButtonTypeRequestPhone)


def run(coro):
    return asyncio.run(coro)


# ============================ buttons / texts ================================
def test_split_text_keeps_lines_and_the_limit():
    assert split_text("abc") == ["abc"]
    text = "\n".join(f"line {i:04d} " + "x" * 90 for i in range(100))
    chunks = split_text(text, 4096)
    assert len(chunks) > 1 and all(len(c) <= 4096 for c in chunks)
    assert "\n".join(chunks) == text
    assert [len(c) for c in split_text("y" * 9000, 4096)] == [4096, 4096, 808]


def test_inline_reply_contact_and_remove_keyboards_map_to_telethon_buttons():
    rows = to_buttons(inline_keyboard([[("یک", "grp:1"), ("دو", "grp:2")], [("سه", "orders")]]))
    assert [[b.text for b in r] for r in rows] == [["یک", "دو"], ["سه"]]
    assert cb_data(rows[0][0]) == b"grp:1"

    keyboard = to_buttons(contact_keyboard("📱 اشتراک شماره"))
    assert is_phone_button(keyboard[0][0])

    plain = to_buttons({"keyboard": [[{"text": "منو"}]], "one_time_keyboard": False})
    assert plain[0][0].button.text == "منو" and not is_phone_button(plain[0][0])

    assert to_buttons({"remove_keyboard": True}) is not None
    assert to_buttons(None) is None

    with pytest.raises(BotApiError):                       # Telegram caps callback data at 64 bytes
        to_buttons(inline_keyboard([[("x", "a" * 65)]]))
    assert isinstance(Button.clear(), type(to_buttons({"remove_keyboard": True})))


def test_every_callback_the_engine_builds_fits_telegrams_limit():
    # the longest shapes in engine.py (ids are at most 12 digits)
    for data in ("adsug:123456789012:123456789012", "vadd:123456789012:123456789012:99",
                 "pg:123456789012:9999", "addu:123456789012", "mdl:99"):
        assert len(data.encode()) <= 64


# ============================ connection / proxies ===========================
def test_connects_through_the_best_proxy_with_the_right_connector_and_reports():
    async def scenario():
        world = FakeWorld()
        ee, dd, plain = (link("ee.example", 443, EE_SECRET, 1), link("dd.example", 443, DD_SECRET, 2),
                         link("plain.example", 443, SECRET16, 3))
        world.dead = {("ee.example", 443)}
        adapter, pool = tg_adapter(world, [ee, dd, plain, None])
        assert await adapter.get_updates(timeout=0) == []
        # the ee proxy failed, the next one worked and the rest were never touched
        assert [c.proxy[0] for c in world.clients] == ["ee.example", "dd.example"]
        assert world.clients[0].connection is ConnectionTcpMTProxyFakeTLS
        assert world.clients[1].connection is ConnectionTcpMTProxyRandomizedIntermediate
        assert pool.reports[0][0] == {"id": 1, "ok": False}
        assert pool.reports[0][1]["id"] == 2 and pool.reports[0][1]["ok"] is True
        assert "latency_ms" in pool.reports[0][1]
        # signed in with the bot token (bot login, not a user session), parse mode off
        assert world.signed_in == 1 and world.live.parse_mode is None
        assert world.live.kwargs["receive_updates"] is True
        await adapter.aclose()
        assert pool.closed and not world.clients[-1].connected
    run(scenario())


def test_plain_proxy_uses_the_intermediate_connector_and_direct_is_the_last_resort():
    async def scenario():
        world = FakeWorld()
        world.dead = {("plain.example", 443)}
        adapter, pool = tg_adapter(world, [link("plain.example", 443, SECRET16, 3), None])
        await adapter.get_updates(timeout=0)
        assert world.clients[0].connection is ConnectionTcpMTProxyIntermediate
        assert world.clients[1].proxy is None             # direct, only after the proxy failed
        assert pool.reports[0][0] == {"id": 3, "ok": False}
        assert pool.reports[0][1]["id"] is None and pool.reports[0][1]["ok"] is True
    run(scenario())


def test_failed_ping_drops_the_proxy_and_the_next_call_switches_to_the_next_one():
    async def scenario():
        world = FakeWorld()
        a, b = link("a.example", 443, EE_SECRET, 1), link("b.example", 443, DD_SECRET, 2)
        adapter, pool = tg_adapter(world, [a, b], health_interval=0)
        await adapter.get_updates(timeout=0)              # connected via a (the first ping is ok)
        assert world.clients[-1].proxy[0] == "a.example"
        world.ping_fails = True
        world.dead = {("a.example", 443)}
        with pytest.raises(BotApiError) as err:           # polling's backoff takes it from here
            await adapter.get_updates(timeout=0)
        assert err.value.network and not world.clients[-1].connected
        assert {"id": 1, "ok": False} in [r for rep in pool.reports for r in rep]
        world.ping_fails = False
        await adapter.get_updates(timeout=0)              # reconnects through b
        assert world.clients[-1].proxy[0] == "b.example" and world.clients[-1].connected
    run(scenario())


def test_dropped_socket_switches_proxy():
    async def scenario():
        world = FakeWorld()
        a, b = link("a.example", 443, EE_SECRET, 1), link("b.example", 443, DD_SECRET, 2)
        adapter, pool = tg_adapter(world, [a, b])
        await adapter.get_updates(timeout=0)
        world.live.connected = False                      # Telethon gave up reconnecting
        world.dead = {("a.example", 443)}
        with pytest.raises(BotApiError):
            await adapter.get_updates(timeout=0)
        await adapter.get_updates(timeout=0)
        assert world.clients[-1].proxy[0] == "b.example"
    run(scenario())


def test_all_proxies_dead_is_a_network_error_and_it_recovers():
    async def scenario():
        world = FakeWorld()
        world.direct_works = False
        a = link("a.example", 443, EE_SECRET, 1)
        world.dead = {("a.example", 443)}
        adapter, pool = tg_adapter(world, [a, None])
        with pytest.raises(BotApiError) as err:
            await adapter.get_updates(timeout=0)
        assert err.value.network and "no proxy" in err.value.description
        world.dead = set()
        assert await adapter.get_updates(timeout=0) == []
        no_candidates, _ = tg_adapter(FakeWorld(), [])
        with pytest.raises(BotApiError) as err:
            await no_candidates.get_updates(timeout=0)
        assert "no proxy configured" in err.value.description
    run(scenario())


def test_a_wrong_token_is_fatal_and_does_not_burn_through_the_pool():
    async def scenario():
        world = FakeWorld()
        world.bad_token = True
        adapter, pool = tg_adapter(world, [link("a.example", 443, EE_SECRET, 1),
                                           link("b.example", 443, DD_SECRET, 2)])
        with pytest.raises(BotApiError) as err:
            await adapter.get_updates(timeout=0)
        assert "401" in err.value.description and not err.value.network
        assert len(world.clients) == 1                    # the second proxy was not even tried
        assert TG_TOKEN not in str(err.value)
    run(scenario())


def test_update_ids_grow_and_survive_a_restart():
    async def scenario():
        world = FakeWorld()
        adapter, _ = tg_adapter(world, [None])
        await adapter.get_updates(timeout=0)
        for i in range(3):
            await world.user_says(user_id=UID, text=f"m{i}")
        ids = [u["update_id"] for u in await adapter.get_updates(timeout=0)]
        assert len(ids) == 3 and ids == sorted(set(ids))
        # a new process starts counting again, but the engine stored the old last id:
        # ids are time based, so they still come out larger
        world2 = FakeWorld()
        restarted, _ = tg_adapter(world2, [None])
        await restarted.get_updates(timeout=0)
        await world2.user_says(user_id=UID, text="after restart")
        assert (await restarted.get_updates(timeout=0))[0]["update_id"] > ids[-1]
    run(scenario())


# ============================ the proxy pool client ==========================
def pool_with(responses, **kw):
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path, request.headers.get("x-api-key"),
                      json.loads(request.content) if request.content else None))
        return responses(request)
    pool = ProxyPool(base_url="http://shopapi.test", worker_api_key=kw.pop("key", "worker-key"),
                     transport=httpx.MockTransport(handler), **kw)
    return pool, calls


def test_pool_ranking_is_kept_local_proxies_follow_and_direct_is_last():
    items = [{"id": 5, "host": "Best.Example", "port": 443, "secret": EE_SECRET},
             {"id": 6, "host": "second.example", "port": 8443, "secret": DD_SECRET},
             {"id": 7, "host": "broken"}]
    local = (f"tg://proxy?server=best.example&port=443&secret={EE_SECRET}",     # duplicate of #5
             f"tg://proxy?server=mine.example&port=443&secret={SECRET16}", "not-a-link")

    async def scenario():
        pool, calls = pool_with(lambda r: httpx.Response(200, json=items), local_proxies=local)
        got = await pool.candidates()
        assert [(p.host, p.id) if p else None for p in got] == [
            ("best.example", 5), ("second.example", 6), ("mine.example", None), None]
        assert calls[0][:3] == ("GET", "/worker/proxies", "worker-key")
        await pool.report([{"id": 5, "ok": True, "latency_ms": 90}, {"id": None, "ok": False}])
        assert calls[1][1] == "/worker/proxies/report"
        assert calls[1][3] == {"results": [{"id": 5, "ok": True, "latency_ms": 90}]}
        await pool.aclose()
    run(scenario())


def test_pool_down_or_keyless_still_gives_local_proxies_and_direct_can_be_off():
    local = (f"tg://proxy?server=mine.example&port=443&secret={SECRET16}",)

    async def scenario():
        pool, _ = pool_with(lambda r: httpx.Response(500), local_proxies=local, allow_direct=False)
        assert [p.host for p in await pool.candidates()] == ["mine.example"]
        await pool.report([{"id": 1, "ok": True}])        # a failing report is only logged
        keyless, calls = pool_with(lambda r: httpx.Response(200, json=[]), key="", local_proxies=local)
        assert [p.host for p in await keyless.candidates() if p] == ["mine.example"]
        await keyless.report([{"id": 1, "ok": True}])
        assert calls == []                                # no key = the pool API is never called
    run(scenario())


# ============================ engine, end to end =============================
@pytest.fixture
def tg_settings():
    return Settings(
        shopapi_base_url="http://shopapi.test", bot_api_key="test-bot-key",
        admin_api_key="test-admin-key", bale_token="TESTTOKEN-BALE-000",
        telegram_bot_token=TG_TOKEN, tg_api_id=12345, tg_api_hash=TG_HASH,
        admin_chat_ids=(f"bale:{ADMIN_CHAT}",), sqlite_path=":memory:", poll_timeout=1,
        product_page_size=2)


@contextlib.asynccontextmanager
async def tg_env(settings, store, shopapi, bale_api, *, candidates=(None,)):
    world = FakeWorld()
    adapter, pool = tg_adapter(world, list(candidates))
    bale_client = httpx.AsyncClient(transport=httpx.MockTransport(bale_api.handler))
    api_client = httpx.AsyncClient(transport=httpx.MockTransport(shopapi.handler))
    adapters = {"bale": BaleAdapter(token=settings.bale_token, api_base="https://bale.test",
                                    client=bale_client), "telegram": adapter}
    engine = BotEngine(settings, store, ShopApiClient(settings, client=api_client), adapters)
    await adapter.get_updates(timeout=0)                  # connect

    async def pump() -> int:
        updates = await adapter.get_updates(timeout=0)
        for update in updates:
            await engine.handle_update("telegram", update)
        return len(updates)

    class Ctx:
        pass
    ctx = Ctx()
    ctx.world, ctx.engine, ctx.adapter, ctx.pump, ctx.api = world, engine, adapter, pump, engine.api
    ctx.bale = bale_api

    async def say(**kw):
        kw.setdefault("user_id", UID)
        await world.user_says(**kw)
        await pump()

    async def press(data, **kw):
        kw.setdefault("user_id", UID)
        answers = await world.user_presses(data=data, **kw)
        await pump()
        return answers
    ctx.say, ctx.press = say, press

    def sent(chat=UID):
        return [r for r in world.sent + world.edited if r["chat"] == int(chat)]

    def last(chat=UID):
        records = sorted(sent(chat), key=lambda r: r["seq"])
        return records[-1]["text"] if records else ""

    def callbacks(chat=UID):
        out = []
        for record in sorted(sent(chat), key=lambda r: r["seq"])[-1:]:
            for row in record["buttons"] or []:
                out += [cb_data(b).decode() for b in row if cb_data(b)]
        return out
    ctx.sent, ctx.last, ctx.callbacks = sent, last, callbacks
    try:
        yield ctx
    finally:
        await adapter.aclose()
        await bale_client.aclose()
        await api_client.aclose()


@pytest.fixture
def tg(tg_settings, store, shopapi):
    bale = FakeBotApi()

    def _run(scenario):
        async def wrapper():
            async with tg_env(tg_settings, store, shopapi, bale) as ctx:
                return await scenario(ctx)
        return asyncio.run(wrapper())
    _run.bale = bale
    return _run


def test_registration_is_contact_only_with_the_share_button(tg, shopapi):
    async def scenario(c):
        await c.say(text="/start")
        assert texts.ASK_CONTACT in c.last()
        keyboard = c.world.sent[-1]["buttons"]
        assert is_phone_button(keyboard[0][0])

        await c.say(text="09121234567")                              # typed numbers are refused
        assert c.last() == texts.CONTACT_BUTTON_ONLY
        await c.say(contact=contact(user_id=int(OTHER_CHAT)))        # somebody else's card
        assert c.last() == texts.CONTACT_NOT_OWN
        await c.say(contact=contact(user_id=0))                      # no Telegram id on the card
        assert c.last() == texts.CONTACT_NOT_OWN
        await c.say(text="/start", user_id=UID + 1)
        await c.say(contact=contact(user_id=UID), user_id=UID + 1)   # forwarded by another user
        assert ("telegram", CUSTOMER_CHAT) not in shopapi.users
        assert texts.CONTACT_NOT_OWN in c.last(UID + 1)

        await c.say(contact=contact(user_id=UID))
        user = shopapi.users[("telegram", CUSTOMER_CHAT)]            # platform value 'telegram'
        assert user["phone"] == "09121234567" and user["name"] == "Ali Rezaei"
        assert user["status"] == "pending"
        assert texts.REGISTERED_PENDING in [r["text"] for r in c.sent()]

    tg(scenario)


def test_known_customer_is_approved_at_once_by_the_r4_match(tg, shopapi):
    shopapi.known_phones = {"09121234567": 7001}

    async def scenario(c):
        await c.say(text="/start")
        await c.say(contact=contact())
        user = shopapi.users[("telegram", CUSTOMER_CHAT)]
        assert user["status"] == "approved" and user["person_code"] == 7001
        assert c.callbacks()                                         # the main menu is shown
        assert tg.bale.sent == []                                    # no staff alert for auto-approval

    tg(scenario)


def test_pending_registration_alerts_the_owner_on_bale_not_telegram(tg, shopapi):
    async def scenario(c):
        await c.say(text="/start")
        await c.say(contact=contact())
        shopapi.add_event("customer_registered", shopapi.users[("telegram", CUSTOMER_CHAT)]["id"])
        await c.engine.admin_sweep()
        assert any(str(p["chat_id"]) == ADMIN_CHAT for p in tg.bale.sent)
        assert all(r["chat"] != int(ADMIN_CHAT) for r in c.world.sent)

    tg(scenario)


def test_catalog_search_cart_checkout_and_receipt_upload(tg, shopapi):
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(c):
        await c.say(text="/start")
        await c.press("grp:1")
        assert "کالای الف" in c.last()
        await c.say(text="کالای ب")                                   # text search
        assert "کالای ب" in c.last()
        await c.press("prod:101")
        await c.press("add:101:2")
        await c.press("checkout")
        order = next(iter(shopapi.orders.values()))
        assert order["status"] == "awaiting_payment" and order["_chat_id"] == CUSTOMER_CHAT
        assert "2,000" in c.last() and "واریز به کارت 1234" in c.last()

        blob = b"\xff\xd8\xff\xe0" + b"7" * 300
        await c.say(photo=True, data=blob)
        assert c.last() == texts.RECEIPT_RECEIVED
        assert order["status"] == "receipt_uploaded"
        assert base64.b64decode(order["_receipt_b64"]) == blob
        assert order["receipt_ref"].startswith(f"{CUSTOMER_CHAT}:")

    tg(scenario)


def test_receipt_as_png_document_and_oversize_or_wrong_files_are_refused(tg, shopapi, tg_settings):
    tg_settings.receipt_max_bytes = 1000
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(c):
        await c.say(text="/start")
        await c.press("grp:1")
        await c.press("prod:101")
        await c.press("add:101:1")
        await c.press("checkout")
        order = next(iter(shopapi.orders.values()))
        await c.say(document={"mime_type": "application/pdf", "name": "r.pdf"})
        assert order["status"] == "awaiting_payment"
        await c.say(document={"mime_type": "image/png", "name": "r.png", "size": 5000},
                    data=b"\x89PNG\r\n\x1a\n" + b"0" * 5000)
        assert order["status"] == "awaiting_payment"                 # declared size over the limit
        await c.say(photo=True, size=10, data=b"\xff\xd8\xff" + b"0" * 3000)
        assert order["status"] == "awaiting_payment"                 # streamed bytes over the limit
        await c.say(document={"mime_type": "image/png", "name": "r.png", "size": 300},
                    data=b"\x89PNG\r\n\x1a\n" + b"0" * 200)
        assert order["status"] == "receipt_uploaded"

    tg(scenario)


def test_model_deep_link_and_copied_text_resolve(tg, shopapi):
    _models(shopapi)
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(c):
        await c.say(text="/start m_iphone-17")
        assert "کالای د" in c.last() and "4,000" in c.last()
        await c.say(text="iPhone 17 Pro" + chr(10) + "کد مدل: iphone-17-pro")
        assert "kp:101" in c.callbacks() and "kp:102" in c.callbacks()
        await c.say(text="galaxy-s25-ultra")                          # unavailable: phone, no guess
        assert shopapi.resolve_texts[-1] == "galaxy-s25-ultra"

    tg(scenario)


def test_model_link_before_registration_is_kept_for_after_it(tg, shopapi):
    _models(shopapi)
    shopapi.known_phones = {"09121234567": 7001}

    async def scenario(c):
        await c.say(text="/start m_iphone-17")
        await c.say(contact=contact())
        assert "کالای د" in "\n".join(r["text"] for r in c.sent())

    tg(scenario)


def test_phone_color_picker_shows_the_price_per_color(tg, shopapi):
    shopapi.products.append(dict(PHONE, variants=[dict(v) for v in PHONE["variants"]]))
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(c):
        await c.say(text="900")
        assert "525" not in c.last() and "col:900:11" in c.callbacks()
        answers = await c.press("col:900:11")
        assert "525,000,000" in c.last()
        answers = await c.press("col:900:12")
        assert "🔄" in c.last() and "605,000,000" in c.last()
        assert any("605,000,000" in str(a["text"]) for a in answers)    # toast via the callback answer
        await c.press("vadd:900:12:1")
        await c.press("checkout")
        assert shopapi.orders[1]["total"] == 605_000_000

    tg(scenario)


def test_statement_is_paginated_and_needs_an_approved_customer(tg, shopapi, tg_settings):
    tg_settings.statement_page_size = 1
    shopapi.statement = {
        "balance": 700, "side": "debtor", "total": 2, "page": 1, "page_size": 1,
        "items": [{"date": "1405/07/19", "kind": "فاکتور فروش", "doc_no": "2672", "debit": 700,
                   "credit": 0, "balance": 700, "side": "debtor", "description": ""}]}
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(c):
        await c.say(text="/start")
        await c.press("stmt:1")
        assert "1405/07/19" in c.last() and "stmt:2" in c.callbacks()
        await c.press("stmt:2")
        assert shopapi.statement_requests[-1]["page"] == "2"

    tg(scenario)


def test_closed_shop_notice_and_tracking_messages(tg, shopapi):
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.closed = True

    async def scenario(c):
        await c.say(text="/start")
        await c.press("grp:1")
        await c.press("prod:101")
        await c.press("add:101:1")
        await c.press("checkout")
        assert texts.SHOP_CLOSED_NOTICE in c.last() and len(shopapi.orders) == 1

        oid = next(iter(shopapi.orders))
        await c.engine.notify_customers_from_events()                # first run: position only
        shopapi.add_event("order_invoiced", oid)
        shopapi.add_event("order_shipped", oid)
        assert await c.engine.notify_customers_from_events() == 2
        got = [r["text"] for r in c.sent()]
        assert texts.ORDER_INVOICED.format(order_id=oid) in got
        assert texts.ORDER_SHIPPED.format(order_id=oid) in got

    tg(scenario)


def test_callbacks_are_answered_and_a_stale_one_is_ignored(tg, shopapi):
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(c):
        await c.say(text="/start")
        answers = await c.press("grp:1")
        assert answers == [{"text": None, "alert": False}]
        await c.adapter.answer_callback("no-such-id", "x")           # expired/unknown: quietly ignored

    tg(scenario)


def test_group_chats_and_bots_are_ignored(tg, shopapi):
    async def scenario(c):
        await c.say(text="/start", is_private=False)
        await c.say(text="/start", bot=True)
        assert c.world.sent == [] and shopapi.users == {}

    tg(scenario)


def test_a_telegram_user_whose_id_equals_a_bale_admin_id_is_not_an_admin(tg, shopapi, tg_settings):
    tg_settings.admin_chat_ids = (ADMIN_CHAT, f"bale:{ADMIN_CHAT}", f"telegram:{ADMIN_CHAT}")
    assert tg_settings.is_admin_chat("bale", ADMIN_CHAT)
    assert not tg_settings.is_admin_chat("telegram", ADMIN_CHAT)
    assert tg_settings.admin_targets(("bale", "telegram")) == [("bale", ADMIN_CHAT)] * 2

    async def scenario(c):
        await c.say(text="/order 1", user_id=int(ADMIN_CHAT))
        assert shopapi.orders == {} and all(
            "Traceback" not in r["text"] for r in c.world.sent)

    tg(scenario)


def test_long_messages_are_split_and_the_keyboard_is_on_the_last_part(tg):
    async def scenario(c):
        text = "\n".join(f"سطر {i} " + "ی" * 60 for i in range(120))
        await c.adapter.send_text(UID, text, inline_keyboard([[("ok", "orders")]]))
        parts = [r for r in c.world.sent if r["chat"] == UID]
        assert len(parts) >= 2 and all(len(p["text"]) <= 4096 for p in parts)
        assert [p["buttons"] is not None for p in parts] == [False] * (len(parts) - 1) + [True]

    tg(scenario)


def test_edit_and_unknown_chat_errors_are_botapi_errors(tg):
    async def scenario(c):
        await c.adapter.edit_text(UID, 5, "new", inline_keyboard([[("ok", "orders")]]))
        assert c.world.edited[-1]["text"] == "new"

        async def boom(*a, **k):
            raise ValueError("Could not find the input entity for PeerUser")
        c.world.live.send_message = boom
        with pytest.raises(BotApiError) as err:
            await c.adapter.send_text(UID, "hi")
        assert err.value.description == "unknown chat" and not err.value.network

        async def reset(*a, **k):
            raise ConnectionResetError()
        c.world.live.send_message = reset
        with pytest.raises(BotApiError) as err:
            await c.adapter.send_text(UID, "hi")
        assert err.value.network                                      # dropped: next call reconnects
        assert c.adapter._client is None

    tg(scenario)


def test_polling_loop_drives_the_telegram_adapter_unchanged(tg_settings, store, shopapi):
    shopapi.add_user("telegram", CUSTOMER_CHAT, status="approved", person_code=7001)
    bale = FakeBotApi()

    async def scenario():
        async with tg_env(tg_settings, store, shopapi, bale) as c:
            stop = asyncio.Event()
            task = asyncio.create_task(poll_platform(
                platform="telegram", adapter=c.adapter, engine=c.engine, store=store,
                settings=tg_settings, stop_event=stop, sleep=lambda s: asyncio.sleep(0)))
            await c.world.user_says(user_id=UID, text="/start")
            for _ in range(200):
                if c.sent():
                    break
                await asyncio.sleep(0.01)
            stop.set()
            await asyncio.wait_for(task, 10)
            assert c.sent() and store.get_last_update_id("telegram") > 0
    run(scenario())


# ============================ settings / wiring ==============================
def test_channel_is_off_without_all_three_secrets_and_on_with_them(monkeypatch):
    base = Settings(bale_token="b")
    assert base.enabled_platforms() == ("bale",) and "telegram" not in build_adapters(base)
    partial = Settings(telegram_bot_token=TG_TOKEN, tg_api_id=1)       # no api hash
    assert partial.enabled_platforms() == ()
    full = Settings(bale_token="b", telegram_bot_token=TG_TOKEN, tg_api_id=1, tg_api_hash=TG_HASH,
                    worker_api_key="k", sqlite_path="/tmp/x/shopbots.db")
    assert full.enabled_platforms() == ("bale", "telegram")
    adapters = build_adapters(full)
    assert isinstance(adapters["telegram"], TelethonBotAdapter)
    assert full.tg_session_file.endswith("tg_bot")                     # next to the SQLite file
    asyncio.run(adapters["telegram"].aclose())


def test_settings_read_the_shared_tg_variables_from_the_environment(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    for key, value in {"TELEGRAM_BOT_TOKEN": TG_TOKEN, "TG_API_ID": "12345", "TG_API_HASH": TG_HASH,
                       "WORKER_API_KEY": "wk", "TG_PROXY": "tg://a, tg://b", "TG_ALLOW_DIRECT": "false",
                       "BALE_TOKEN": ""}.items():
        monkeypatch.setenv(key, value)
    s = Settings.from_env()
    assert s.telegram_configured and s.tg_api_id == 12345 and s.worker_api_key == "wk"
    assert s.tg_proxies == ("tg://a", "tg://b") and s.tg_allow_direct is False
    assert s.enabled_platforms() == ("telegram",)
    for secret in (TG_TOKEN, TG_HASH, "wk"):
        assert secret not in repr(s)                                   # dataclass repr hides them
    monkeypatch.setenv("TG_API_ID", "abc")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_no_secret_reaches_the_logs(tg_settings, store, shopapi, caplog):
    caplog.set_level(logging.DEBUG)
    bale = FakeBotApi()
    ee = link("ee.example", 443, EE_SECRET, 1)

    async def scenario():
        world_candidates = [ee, link("dd.example", 443, DD_SECRET, 2), None]
        async with tg_env(tg_settings, store, shopapi, bale, candidates=world_candidates) as c:
            c.world.dead = {("ee.example", 443)}
            c.adapter._client.connected = False
            with contextlib.suppress(BotApiError):
                await c.adapter.get_updates(timeout=0)
            await c.adapter.get_updates(timeout=0)
            await c.say(text="/start")
            await c.say(contact=contact())
    asyncio.run(scenario())
    log = caplog.text
    assert "ee.example:443 (ee)" in log                                # masked form is logged
    for secret in (TG_TOKEN, TG_TOKEN.split(":")[1], TG_HASH, EE_SECRET, SECRET16, DD_SECRET):
        assert secret not in log
    assert "09121234567" not in log


def test_real_telethon_client_accepts_our_options(tmp_path):
    """The kwargs we pass exist in the installed Telethon (nothing connects)."""
    async def scenario():
        pool = FakePool([])
        for session_path in (str(tmp_path / "tg_bot"), ""):
            adapter = TelethonBotAdapter(bot_token=TG_TOKEN, api_id=1, api_hash=TG_HASH, pool=pool,
                                         session_path=session_path)
            client = adapter._new_client(link("h.example", 443, EE_SECRET, 1))
            assert client.parse_mode is None
            assert client._connection is ConnectionTcpMTProxyFakeTLS
            adapter._register(client)
            assert len(client.list_event_handlers()) == 2
            assert client.session is not None
    asyncio.run(scenario())
