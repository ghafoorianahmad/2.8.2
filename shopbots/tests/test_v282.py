"""v2.8.2: a phone without stock is offered as «درخواست خرید» already when its
color is picked (checkout rules asked from shopapi), the cart never gets it, a
phone that runs out before checkout is requested with one tap, the payment
details come from staff, and ShopAdmin's decisions reach the customer within
seconds (own events loop)."""
from __future__ import annotations

import asyncio

from app import texts
from app.polling import events_loop

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_phase3 import _callbacks
from .test_v280 import _shop


def test_no_stock_at_color_pick_offers_a_purchase_request(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.no_stock.add(900)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        callbacks = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "pbv:900:11" in callbacks
        assert not any(cb.startswith("vadd:900:11:") for cb in callbacks)
        assert shopapi.check_bodies and shopapi.order_bodies == []
        # an old «افزودن» button still refuses: nothing reaches the cart
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "vadd:900:11:1")
        assert engine.cart.items("bale", str(CUSTOMER_CHAT)) == []

    env(scenario)


def test_the_cart_quantity_is_checked_too(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "vadd:900:11:2")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "col:900:11")
        assert shopapi.check_bodies[-1]["items"] == [
            {"kala_code": 900, "qty": 3.0, "variant_id": 11}]   # 2 in the cart + 1

    env(scenario)


def test_out_of_stock_at_checkout_one_tap_request(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "vadd:900:11:1")
        shopapi.no_stock.add(900)
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "checkout")
        assert "pbv:900:11" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "pbv:900:11")
        assert shopapi.purchase_requests[-1]["kala_code"] == 900
        assert engine.cart.items("bale", str(CUSTOMER_CHAT)) == []    # requested, not ordered

    env(scenario)


def test_checkout_waits_for_the_payment_details(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.auto_payment_info = None

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()                     # cursor
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="101")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "checkout")
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert texts.WAIT_PAYMENT_INFO in body and "6037" not in body
        order_id = max(shopapi.orders)
        shopapi.orders[order_id]["payment_info"] = {"account_number": "0123456789",
                                                    "holder": "فروشگاه"}
        shopapi.add_event("order_payment_info", order_id)
        await engine.notify_customers_from_events()
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "شمارهٔ حساب: 0123456789" in body and "به نام: فروشگاه" in body
        assert "شمارهٔ کارت" not in body
        state, data = engine.store.get_conversation("bale", str(CUSTOMER_CHAT))
        assert state == "await_receipt" and data["order_id"] == order_id

    env(scenario)


def test_events_loop_runs_until_stopped(settings):
    calls = []

    class Engine:
        async def notify_customers_from_events(self):
            calls.append(1)
            if len(calls) == 3:
                stop.set()
            return 0

    stop = asyncio.Event()

    async def no_sleep(_seconds):
        return None

    asyncio.run(events_loop(engine=Engine(), settings=settings, stop_event=stop,
                            sleep=no_sleep))
    assert len(calls) == 3
    assert settings.events_poll_seconds == 2.0
