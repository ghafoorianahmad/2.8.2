"""v2.6.1 on the bot side: no shop phone line without a phone, «استعلام قیمت» for
price-on-inquiry items, clear messages for stale cart items, item requests never
announced in the admin chat, and staff replies delivered to the customer."""
from __future__ import annotations

import json

from app import texts

from .conftest import ADMIN_CHAT, CUSTOMER_CHAT, push_callback, push_message
from .test_phase2 import _callbacks


# ---- 1: shop phone -------------------------------------------------------------------------
def _load_with_phone(tmp_path, phone):
    path = tmp_path / "messages.json"
    path.write_text(json.dumps({"shop": {"shop_phone": phone}}), encoding="utf-8")
    texts.load(path)


def test_no_phone_line_when_the_phone_is_empty(tmp_path):
    try:
        for empty in ("", "  ", texts.PHONE_PLACEHOLDER):
            _load_with_phone(tmp_path, empty)
            for key in ("SUPPORT", "SHOP_INFO", "REJECTED_USER", "PAYMENT_NOT_READY",
                        "SALES_CLOSED", "MODEL_UNAVAILABLE"):
                value = getattr(texts, key)
                assert "☎️" not in value and "شماره تلفن فروشگاه" not in value, (empty, key)
            assert "ساعت پذیرش" in texts.SHOP_INFO                  # the other lines stay
            assert texts.SHOP["shop_phone"] == ""
        _load_with_phone(tmp_path, "021-1234")
        assert "☎️ تلفن: 021-1234" in texts.SUPPORT
    finally:
        texts.load()


def test_drop_phone_lines():
    assert texts.drop_phone_lines("a\n☎️ {shop_phone}\nb") == "a\nb"
    assert texts.drop_phone_lines("no phone {x}") == "no phone {x}"


def test_shipped_default_has_no_placeholder_phone():
    texts.load()
    assert "شماره تلفن فروشگاه" not in texts.SUPPORT


# ---- 6: price on inquiry ---------------------------------------------------------------------
def _inquiry_product(shopapi):
    shopapi.products.append({"code": 600, "name": "ساعت طلا", "group": 9, "unit_price": 0.0,
                             "available_qty": 0.0, "image": None, "priced_by": "inquiry",
                             "price_on_inquiry": True})


def test_inquiry_item_has_no_price_and_no_cart(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    _inquiry_product(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:9")
        listing = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert texts.PRODUCT_LINE_INQUIRY.format(name="ساعت طلا") in listing
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:600")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.PRODUCT_DETAIL_INQUIRY.format(name="ساعت طلا")
        callbacks = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "pinq:600" in callbacks and not any(c.startswith("add:600") for c in callbacks)
        # a forged add is refused
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:600:1")
        assert engine.cart.items("bale", CUSTOMER_CHAT) == []
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "pinq:600")
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "pinq:600")     # once only

    env(scenario)
    assert [(r["kala_code"], r["kind"]) for r in shopapi.item_requests] == [(600, "inquiry")]
    assert texts.PRICE_INQUIRY_SENT.format(name="ساعت طلا") in \
        bot_apis["bale"].texts(CUSTOMER_CHAT)
    assert not shopapi.orders
    assert bot_apis["bale"].texts(ADMIN_CHAT) == []                # never the admin chat


# ---- 3: stale carts --------------------------------------------------------------------------
def test_stale_cart_item_is_named_with_the_reason(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        for n, (reason, key) in enumerate((
                ("is price on inquiry", "CART_ITEM_ON_INQUIRY"),
                ("is not available for sale", "CART_ITEM_NOT_FOR_SALE"),
                ("is not in the current price list", "CART_ITEM_NOT_IN_LIST"))):
            shopapi.refuse_items = {101: reason}
            await push_callback(engine, "bale", 10 + n, CUSTOMER_CHAT, "checkout")
            assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
                getattr(texts, key).format(name="کالای الف")
            assert "cart" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)

    env(scenario)
    assert not shopapi.orders


# ---- 7: staff replies ------------------------------------------------------------------------
def _reply(shopapi, message_id=1, platform="bale", text="موجود شد؛ تشریف بیاورید"):
    shopapi.item_request_messages[message_id] = {
        "id": message_id, "request_id": 1, "text": text, "status": "pending", "error": "",
        "created_at": "t", "created_by": "staff:ali", "platform": platform,
        "chat_id": CUSTOMER_CHAT, "product_name": "نوکیا ۳۳۱۰", "request_text": "",
        "kind": "unavailable"}
    shopapi.add_event("item_request_message", message_id)


def test_reply_is_delivered_once_and_reported(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await engine.notify_customers_from_events()                 # sets the cursor
        _reply(shopapi)
        assert await engine.notify_customers_from_events() == 1
        shopapi.add_event("item_request_message", 1)                # a duplicate event
        await engine.notify_customers_from_events()

    env(scenario)
    sent = bot_apis["bale"].texts(CUSTOMER_CHAT)
    assert sent == [texts.ITEM_REQUEST_REPLY.format(product=" («نوکیا ۳۳۱۰»)",
                                                    text="موجود شد؛ تشریف بیاورید")]
    assert shopapi.message_results == [{"id": 1, "ok": True, "error": ""}]


def test_reply_failure_is_reported(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await engine.notify_customers_from_events()
        bot_apis["bale"].fail_methods.add("sendMessage")
        _reply(shopapi)
        _reply(shopapi, 2, platform="telegram")                     # no telegram bot here
        await engine.notify_customers_from_events()

    env(scenario)
    results = {r["id"]: r for r in shopapi.message_results}
    assert results[1]["ok"] is False and "forced failure" in results[1]["error"]
    assert results[2]["ok"] is False and "telegram" in results[2]["error"]
    assert TOKEN_FREE(results)


def TOKEN_FREE(results) -> bool:
    from .conftest import BALE_TOKEN

    return all(BALE_TOKEN not in str(r) for r in results.values())


def test_group_list_shows_subgroups_under_their_parent():
    from app.engine import BotEngine

    groups = [{"code": 31, "name": "سامسونگ", "parent": 3}, {"code": 1, "name": "جانبی", "parent": 0},
              {"code": 3, "name": "گوشی", "parent": 0}]
    assert [g["code"] for g in BotEngine._tree_order(groups)] == [1, 3, 31]
    loop = [{"code": 7, "parent": 8}, {"code": 8, "parent": 7}]
    assert sorted(g["code"] for g in BotEngine._tree_order(loop)) == [7, 8]
