"""v2.9.3 on the bot side: an order cancelled in ShopAdmin reaches the customer
(with the short reason), its old buttons stop working; the price offer says
«قیمت امروز این کالا», a quantity / total only for more than one, and staff's
own words under it."""
from __future__ import annotations

from app import texts

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_v280 import _shop
from .test_v292 import _offer


def _checkout(engine):
    async def run():
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="101")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "checkout")
    return run()


def test_staff_cancel_reaches_the_customer_and_retires_the_buttons(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.auto_payment_info = None

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()                     # cursor
        await _checkout(engine)
        order_id = max(shopapi.orders)
        shopapi.orders[order_id]["payment_info"] = {"card_number": "6037991234567890"}
        shopapi.add_event("order_payment_info", order_id)
        await engine.notify_customers_from_events()
        state, _ = engine.store.get_conversation("bale", str(CUSTOMER_CHAT))
        assert state == "await_receipt"
        edits_before = len(bot_apis["bale"].edited)
        shopapi.orders[order_id].update(status="cancelled", cancel_reason="staff",
                                        cancel_note="این رنگ تمام شد")
        shopapi.add_event("order_cancelled_by_staff", order_id)
        await engine.notify_customers_from_events()
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "از طرف فروشگاه لغو شد" in body and "دلیل: این رنگ تمام شد" in body
        edits = bot_apis["bale"].edited[edits_before:]
        assert len(edits) >= 2                         # checkout + payment details
        assert all(texts.ORDER_CANCELLED_MARK in e["text"] for e in edits)
        assert all(not e.get("reply_markup") for e in edits)   # the keyboard is gone
        state, _ = engine.store.get_conversation("bale", str(CUSTOMER_CHAT))
        assert state != "await_receipt"
        # an old «لغو سفارش» / «ارسال رسید» button: «لغو شده است»
        await push_callback(engine, "bale", 9, CUSTOMER_CHAT, f"ocx:{order_id}")
        assert "لغو شده است" in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        await push_callback(engine, "bale", 10, CUSTOMER_CHAT, f"rcpt:{order_id}")
        state, _ = engine.store.get_conversation("bale", str(CUSTOMER_CHAT))
        assert state != "await_receipt"
        # the same event again: nothing new
        sent = len(bot_apis["bale"].texts(CUSTOMER_CHAT))
        shopapi.add_event("order_cancelled_by_staff", order_id)
        await engine.notify_customers_from_events()
        assert len(bot_apis["bale"].texts(CUSTOMER_CHAT)) == sent

    env(scenario)


def test_offer_text_one_item_with_staffs_note(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        _offer(shopapi)
        shopapi.item_request_messages[5]["note"] = "گارانتی ۱۸ ماهه دارد"
        await engine.notify_customers_from_events()
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "قیمت امروز این کالا:" in body
        assert "تعداد" not in body and "جمع" not in body
        assert body.index("قیمت امروز") < body.index("گارانتی ۱۸ ماهه دارد")

    env(scenario)


def test_offer_text_shows_the_total_for_more_than_one(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        _offer(shopapi, price=100)
        shopapi.item_request_messages[5]["qty"] = 3
        await engine.notify_customers_from_events()
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "تعداد: 3" in body and "جمع: 300" in body
        assert "📝" not in body

    env(scenario)
