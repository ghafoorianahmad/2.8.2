"""v2.9.1: the admin chat gets only problems; open carts are re-checked with the
new prices at checkout (placed orders keep theirs)."""
from __future__ import annotations

import pytest

from app import texts

from .conftest import ADMIN_CHAT, CUSTOMER_CHAT, push_callback, push_message


@pytest.fixture(autouse=True)
def _builtin_texts(monkeypatch):
    monkeypatch.delenv(texts.ENV_VAR, raising=False)
    texts.load()
    yield
    texts.load()


async def _add_to_cart(engine, start=10):
    await push_message(engine, "bale", start, CUSTOMER_CHAT, text="/start")
    await push_callback(engine, "bale", start + 1, CUSTOMER_CHAT, "grp:1")
    await push_callback(engine, "bale", start + 2, CUSTOMER_CHAT, "add:101:2")


def test_new_orders_are_not_announced_in_the_admin_chat(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        assert engine.settings.admin_chat_order_notices is False
        await _add_to_cart(engine)
        await push_callback(engine, "bale", 13, CUSTOMER_CHAT, "checkout")
        assert shopapi.order_bodies                       # the order was placed
        first_line = texts.NEW_ORDER_NOTICE.splitlines()[0].format(order_id=1)
        assert not any(t.startswith(first_line) for t in tg.texts(ADMIN_CHAT))

    env(scenario)


def test_problems_reach_the_admin_chat_and_inquiries_do_not(env, bot_apis, shopapi):
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        await engine.notify_customers_from_events()      # first run: position only
        shopapi.add_event("price_held", 9)
        shopapi.add_event("price_correction_unmatched", 4)
        shopapi.add_event("sales_closed_channel", 9)
        shopapi.add_event("price_inquiry", 1)
        shopapi.inquiries.append({"id": 1})
        await engine.notify_customers_from_events()
        sent = tg.texts(ADMIN_CHAT)
        assert texts.PRICE_HELD_NOTICE.format(list_id=9) in sent
        assert texts.PRICE_CORRECTION_UNMATCHED_NOTICE in sent
        assert texts.SALES_CLOSED_CHANNEL_NOTICE in sent
        assert not any(t.startswith("📨") for t in sent)

    env(scenario)


def test_changed_price_is_confirmed_again_before_the_order(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    tg = bot_apis["bale"]

    async def scenario(engine, adapters, api):
        await _add_to_cart(engine)
        product = next(p for p in shopapi.products if p["code"] == 101)
        product["unit_price"] = float(product["unit_price"]) + 500   # a new price list
        await push_callback(engine, "bale", 13, CUSTOMER_CHAT, "checkout")
        assert not shopapi.order_bodies                   # nothing placed yet
        assert any("قیمت این کالاها" in t for t in tg.texts(CUSTOMER_CHAT))
        item = engine.cart.items("bale", CUSTOMER_CHAT)[0]
        assert float(item["unit_price"]) == float(product["unit_price"])
        # the customer confirms: placed at the new price
        await push_callback(engine, "bale", 14, CUSTOMER_CHAT, "checkout")
        assert len(shopapi.order_bodies) == 1

    env(scenario)
