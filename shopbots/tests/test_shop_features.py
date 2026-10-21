"""Shop customisation (messages.fa.json), /myid, new-order/receipt notices,
dry-run approvals, ShopAdmin decisions via the event feed, Bot API outages.

The Bot API is always mocked (httpx.MockTransport) - no network, no real token.
(Was test_telegram_shop.py; Bale is the only channel since 2026-10-11.)
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from app import texts
from app.platforms import BaleAdapter
from app.polling import poll_platform
from app.store import Store

from .conftest import (
    ADMIN_CHAT,
    CUSTOMER_CHAT,
    BALE_TOKEN,
    FakeBotApi,
    push_callback,
    push_message,
)

PHOTO = [{"file_id": "small"}, {"file_id": "big-receipt"}]


@pytest.fixture(autouse=True)
def _builtin_texts(monkeypatch):
    monkeypatch.delenv(texts.ENV_VAR, raising=False)
    texts.load()
    yield
    texts.load()


def _callbacks(api: FakeBotApi, chat) -> list[str]:
    return [cb for row in api.buttons_for(chat) for _, cb in row]


# ============================ messages.fa.json ==============================
def test_builtin_texts_have_shop_name_and_keep_message_placeholders():
    assert "عصر ارتباطات ۲" in texts.WELCOME
    assert "{shop_name}" not in texts.MAIN_MENU
    assert "{order_id}" in texts.CHECKOUT_OK and "{total}" in texts.CHECKOUT_OK
    assert texts.CHECKOUT_OK.format(order_id=7, total="1,000").count("7") == 1
    assert texts.status_fa("awaiting_payment") == "در انتظار پرداخت"


def test_operator_file_overrides_key_by_key(tmp_path):
    custom = tmp_path / "messages.fa.json"
    custom.write_text(json.dumps({
        "shop": {"shop_name": "فروشگاه آزمایشی", "shop_phone": "021-0000-1111"},
        "messages": {"WELCOME": "سلام از {shop_name}"},
        "buttons": {"BTN_MENU": "خانه"},
    }, ensure_ascii=False), encoding="utf-8")
    assert texts.load(custom) == str(custom)
    assert texts.WELCOME == "سلام از فروشگاه آزمایشی"
    assert texts.BTN_MENU == "خانه"
    assert "فروشگاه آزمایشی" in texts.MAIN_MENU          # default text, new shop name
    assert "021-0000-1111" in texts.SUPPORT
    assert texts.BTN_CART                                # missing key -> default


def test_broken_operator_file_falls_back_to_defaults(tmp_path, caplog):
    broken = tmp_path / "messages.fa.json"
    broken.write_text("{ not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="shopbots.texts"):
        source = texts.load(broken)
    assert source == str(texts.DEFAULT_FILE)
    assert "عصر ارتباطات ۲" in texts.WELCOME
    assert "invalid" in caplog.text


def test_env_var_selects_the_operator_file(tmp_path, monkeypatch):
    custom = tmp_path / "m.json"
    custom.write_text(json.dumps({"shop": {"shop_name": "X"}}), encoding="utf-8")
    monkeypatch.setenv(texts.ENV_VAR, str(custom))
    texts.load()
    assert "«X»" in texts.WELCOME


def test_braces_in_shop_values_do_not_break_formatting(tmp_path):
    custom = tmp_path / "m.json"
    custom.write_text(json.dumps({"shop": {"shop_phone": "{021} 123"}}), encoding="utf-8")
    texts.load(custom)
    assert "{021} 123" in texts.REJECTED_USER.format()


# ============================ commands / screens ============================
def test_myid_works_for_anyone_in_any_state(env, bot_apis):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")  # -> asks contact
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="/myid")
        assert CUSTOMER_CHAT in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        # still in the registration step afterwards
        assert engine.store.get_conversation("bale", CUSTOMER_CHAT)[0] == "await_contact"
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="/myid@asrertebatat2_bot")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT) == texts.MY_ID.format(chat_id=CUSTOMER_CHAT)

    env(scenario)


def test_start_restarts_registration_with_welcome(env, bot_apis):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="علی رضایی")
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="/start")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT).startswith(texts.WELCOME)
        assert engine.store.get_conversation("bale", CUSTOMER_CHAT)[0] == "await_contact"


def test_conversation_left_in_old_registration_state_continues_with_contact(env, bot_apis):
    async def scenario(engine, adapters, api):
        engine.store.set_conversation("bale", CUSTOMER_CHAT, "await_phone", {"name": "x"})
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="09121234567")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT) == texts.CONTACT_BUTTON_ONLY

    env(scenario)


def test_main_menu_has_support_and_info(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        callbacks = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert callbacks == ["groups", "search", "cart", "orders", "ireq", "stmt:1", "support",
                             "info"]
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "info")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SHOP_INFO
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "support")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SUPPORT

    env(scenario)


def test_pending_customer_sees_menu_without_statement(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert texts.STILL_PENDING in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert _callbacks(bot_apis["bale"], CUSTOMER_CHAT) == [
            "groups", "search", "cart", "orders", "support", "info"]
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "info")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SHOP_INFO


def test_rejected_customer_only_sees_support_and_info(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="rejected")

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT).endswith(texts.REJECTED_USER)
        assert _callbacks(bot_apis["bale"], CUSTOMER_CHAT) == ["support", "info"]
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "groups")
        assert bot_apis["bale"].answered[-1]["text"] == texts.REJECTED_USER

    env(scenario)


def test_product_list_shows_stock_state_not_quantity(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        listing = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "1,000" in listing and texts.IN_STOCK in listing
        assert "10" not in listing.replace("1,000", "")      # available_qty is not shown
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        detail = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "کالای الف" in detail and texts.IN_STOCK in detail

    env(scenario)


# ============================ order flow / admin ============================
async def _order_one(engine, platform="bale", start=10):
    await push_message(engine, platform, start, CUSTOMER_CHAT, text="/start")
    await push_callback(engine, platform, start + 1, CUSTOMER_CHAT, "grp:1")
    await push_callback(engine, platform, start + 2, CUSTOMER_CHAT, "add:101:2")
    await push_callback(engine, platform, start + 3, CUSTOMER_CHAT, "checkout")


def test_full_order_notifies_admin_on_order_and_receipt(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        await _order_one(engine)
        # admin hears about the new order immediately, with a status button
        notice = next(t for t in tg.texts(ADMIN_CHAT) if t.startswith(texts.NEW_ORDER_NOTICE.splitlines()[0].format(order_id=1)))
        assert "کالای الف × 2" in notice
        assert "adst:1" in _callbacks(tg, ADMIN_CHAT)
        await push_callback(engine, "bale", 30, ADMIN_CHAT, "adst:1")
        assert tg.last_text(ADMIN_CHAT) == texts.ADMIN_ORDER_STATUS.format(
            order_id=1, status=texts.status_fa("awaiting_payment"), total="2,000")

        # receipt -> admin gets the photo + approve/reject at once (no sweep needed)
        await push_message(engine, "bale", 31, CUSTOMER_CHAT, photo=PHOTO)
        assert tg.last_text(CUSTOMER_CHAT) == texts.RECEIPT_RECEIVED
        assert tg.photos and tg.photos[-1]["photo"] == "big-receipt"
        assert {"adap:1", "adrp:1"} <= set(_callbacks(tg, ADMIN_CHAT))
        result = await engine.admin_sweep()
        assert result["orders"] == 0                       # not announced twice

        await push_callback(engine, "bale", 32, ADMIN_CHAT, "adap:1")
        assert tg.last_text(ADMIN_CHAT) == texts.ADMIN_PAYMENT_APPROVED
        assert tg.last_text(CUSTOMER_CHAT) == texts.PAYMENT_APPROVED.format(order_id=1)

    env(scenario)


def test_dry_run_approval_says_so_and_still_informs_customer(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.dry_run_writes = True
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        await _order_one(engine)
        await push_message(engine, "bale", 20, CUSTOMER_CHAT, photo=PHOTO)
        await push_callback(engine, "bale", 21, ADMIN_CHAT, "adap:1")
        assert tg.last_text(ADMIN_CHAT) == texts.ADMIN_PAYMENT_APPROVED_DRY_RUN
        assert tg.last_text(CUSTOMER_CHAT) == texts.PAYMENT_APPROVED.format(order_id=1)
        assert shopapi.orders[1]["status"] == "receipt_uploaded"   # nothing written

    env(scenario)


def test_card_comes_from_shopapi_never_from_the_messages_file(env, bot_apis, shopapi, tmp_path):
    """v2.6.0: an old operator copy with a placeholder card changes nothing."""
    custom = tmp_path / "m.json"
    custom.write_text(json.dumps({"shop": {"card_number": "XXXX-XXXX-XXXX-XXXX"}}), encoding="utf-8")
    texts.load(custom)
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.payment_card = "6037991122334455"
    shopapi.auto_payment_info = {"card_number": "6037-9911-2233-4455"}

    async def scenario(engine, adapters, api):
        await _order_one(engine)
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT).replace("‎", "")
        assert "6037-9911-2233-4455" in body and "2,000" in body
        assert "XXXX" not in body

    env(scenario)


def test_receipt_button_in_my_orders(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        await _order_one(engine)
        await push_callback(engine, "bale", 20, CUSTOMER_CHAT, "menu")
        await push_callback(engine, "bale", 21, CUSTOMER_CHAT, "orders")
        assert "rcpt:1" in _callbacks(tg, CUSTOMER_CHAT)
        await push_callback(engine, "bale", 22, CUSTOMER_CHAT, "rcpt:1")
        assert tg.last_text(CUSTOMER_CHAT) == texts.ASK_RECEIPT.format(order_id=1)
        await push_message(engine, "bale", 23, CUSTOMER_CHAT, photo=PHOTO)
        assert shopapi.orders[1]["status"] == "receipt_uploaded"

    env(scenario)


def test_receipt_for_order_not_awaiting_payment_is_explained(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_one(engine)
        shopapi.orders[1]["status"] = "expired"
        await push_message(engine, "bale", 20, CUSTOMER_CHAT, photo=PHOTO)
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT) == texts.ORDER_NOT_AWAITING

    env(scenario)


def test_shopadmin_decisions_reach_the_customer_once(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        shopapi.add_event("customer_registered", 1)          # history: not replayed
        await engine.admin_sweep()                            # first run: cursor only
        await _order_one(engine)
        await push_message(engine, "bale", 20, CUSTOMER_CHAT, photo=PHOTO)
        # staff approve in ShopAdmin -> shopapi emits an event
        shopapi.orders[1]["status"] = "written"
        shopapi.add_event("payment_approved", 1)
        result = await engine.admin_sweep()
        assert result["notified"] == 1
        assert tg.last_text(CUSTOMER_CHAT) == texts.PAYMENT_APPROVED.format(order_id=1)
        sent = len(tg.texts(CUSTOMER_CHAT))
        assert (await engine.admin_sweep())["notified"] == 0
        assert len(tg.texts(CUSTOMER_CHAT)) == sent

    env(scenario)


def test_bot_decision_is_not_repeated_by_the_event_feed(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        await _order_one(engine)
        await push_message(engine, "bale", 20, CUSTOMER_CHAT, photo=PHOTO)
        await push_callback(engine, "bale", 21, ADMIN_CHAT, "adrp:1")
        shopapi.add_event("payment_rejected", 1)
        sent = len(tg.texts(CUSTOMER_CHAT))
        assert (await engine.admin_sweep())["notified"] == 0
        assert len(tg.texts(CUSTOMER_CHAT)) == sent

    env(scenario)


def test_customer_approved_in_shopadmin_is_told(env, bot_apis, shopapi):
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        user = shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=9)
        shopapi.add_event("customer_approved", user["id"])
        await engine.admin_sweep()
        assert tg.last_text(CUSTOMER_CHAT) == texts.APPROVED_BY_ADMIN

    env(scenario)


# ============================ proxy =========================================


# ============================ Bot API outages ===============================
def test_file_download_uses_the_adapter_client():
    api = FakeBotApi()
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        if "/file/" in request.url.path:
            return httpx.Response(200, content=b"JPEG")
        return api.handler(request)

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = BaleAdapter(token=BALE_TOKEN, api_base="https://bale.test", client=client)
        data = await adapter.download_file_ref("big-receipt")
        await client.aclose()
        return data

    assert asyncio.run(go()) == b"JPEG"
    assert seen[0].endswith("/getFile") and "/file/bot" in seen[1]


def test_poller_survives_bale_outage_and_recovers(settings, store, caplog):
    state = {"calls": 0}
    bale = FakeBotApi()

    def handler(request):
        state["calls"] += 1
        if state["calls"] <= 3:
            raise httpx.ConnectError("network down")
        return bale.handler(request)

    sleeps: list[float] = []

    async def go():
        stop = asyncio.Event()
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter = BaleAdapter(token=BALE_TOKEN, api_base="https://bale.test", client=client)

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            if state["calls"] >= 5:
                stop.set()

        class _Engine:
            async def handle_update(self, *a):
                return True

        await poll_platform(platform="bale", adapter=adapter, engine=_Engine(),
                            store=Store(":memory:"), settings=settings, stop_event=stop,
                            sleep=fake_sleep)
        await client.aclose()

    with caplog.at_level(logging.INFO):
        asyncio.run(go())
    assert sleeps[:3] == [1.0, 2.0, 4.0]                  # exponential backoff
    log = caplog.text
    assert log.count("cannot reach the Bot API") == 1     # no log spam
    assert "در دسترس نیست" in log and "connection restored" in log
    assert "proxy" not in log
    assert BALE_TOKEN not in log
