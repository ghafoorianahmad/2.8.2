"""v2.9.2 on the bot side: one button «درخواست خرید - استعلام قیمت»; a price held
by the price guard is never shown or sold (only requested); the price staff
offer comes with «تأیید و خرید» / «نمی‌خواهم» and the answer goes to shopapi."""
from __future__ import annotations

from app import texts

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_phase3 import _callbacks
from .test_v280 import _row, _shop


def test_one_button_for_purchase_and_inquiry():
    assert texts.BTN_BUY_INQUIRY == "🛍 درخواست خرید - استعلام قیمت"


def test_held_color_is_only_requested(env, bot_apis, shopapi):
    _shop(shopapi)
    phone = shopapi.products[-1]
    for v in phone["variants"]:
        if v["id"] == 11:
            v.update(unit_price=None, available=False, price_held=True)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "تغییر زیادی" in body and "525" not in body
        callbacks = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "pbv:900:11" in callbacks and not any(c.startswith("vadd:") for c in callbacks)
        # never added to the cart with an old price
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "vadd:900:11:1")
        assert not engine.cart.items("bale", str(CUSTOMER_CHAT))
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "pbv:900:11")
        assert shopapi.purchase_requests[-1]["variant_id"] == 11

    env(scenario)


def test_held_search_row_shows_no_price(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.phone_rows = [dict(_row("h", "17 Pro 256", "مشکی", "ZAA", None), price_held=True)]

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="17 pro")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "تغییر زیادی" in body
        assert "pbr:0" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)

    env(scenario)


def _offer(shopapi, message_id=5, price=1_210_000_000):
    shopapi.item_request_messages[message_id] = {
        "id": message_id, "request_id": 3, "text": "قیمت پیشنهادی", "status": "pending",
        "error": "", "created_at": "t", "created_by": "staff:mina", "purpose": "offer",
        "platform": "bale", "chat_id": str(CUSTOMER_CHAT), "product_name": "آیفون ۱۷ پرو",
        "request_text": "", "kind": "purchase", "color": "Silver", "part": "CHA", "qty": 1,
        "offer_price_rial": price, "outcome": "offered"}
    shopapi.add_event("item_request_message", message_id)


def test_offer_has_buy_and_decline_buttons_and_accept_orders(env, bot_apis, shopapi):
    _shop(shopapi)
    user = shopapi.users[("bale", str(CUSTOMER_CHAT))]
    shopapi.orders[9] = {
        "id": 9, "status": "awaiting_payment", "total": 1_210_000_000.0, "items": [
            {"kala_code": 900, "name": "آیفون ۱۷ پرو — Silver — CHA", "qty": 1,
             "unit_price": 1_210_000_000.0}],
        "payment_info": None, "user_id": user["id"],
        "_platform": "bale", "_chat_id": str(CUSTOMER_CHAT)}
    shopapi.offer_order_id = 9

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()                    # first run: cursor only
        _offer(shopapi)
        await engine.notify_customers_from_events()
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "1,210,000,000" in body or "۱٬۲۱۰٬۰۰۰٬۰۰۰" in body or "1210000000" in body \
            or "تأیید و خرید" in body
        callbacks = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "pok:5" in callbacks and "pno:5" in callbacks
        assert shopapi.message_results[-1]["ok"] is True
        # another chat cannot answer
        await push_callback(engine, "bale", 1, 999, "pok:5")
        assert shopapi.offer_answers == []
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "pok:5")
        assert shopapi.offer_answers == [{"id": 3, "accept": True, "price_rial": 1_210_000_000}]
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "سفارش شمارهٔ 9" in body or "سفارش شمارهٔ ۹" in body
        assert texts.WAIT_PAYMENT_INFO in body
        # the events feed does not say it again
        shopapi.add_event("purchase_order_created", 9)
        sent = len(bot_apis["bale"].texts(CUSTOMER_CHAT))
        await engine.notify_customers_from_events()
        assert len(bot_apis["bale"].texts(CUSTOMER_CHAT)) == sent

    env(scenario)


def test_offer_decline_and_a_replaced_offer(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        _offer(shopapi)
        await engine.notify_customers_from_events()
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "pno:5")
        assert shopapi.offer_answers[-1]["accept"] is False
        assert texts.PURCHASE_OFFER_DECLINED in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        shopapi.offer_answer_error = (409, "The offer is no longer open")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "pok:5")
        assert texts.PURCHASE_OFFER_GONE in bot_apis["bale"].last_text(CUSTOMER_CHAT)

    env(scenario)
