"""v2.6.2 on the bot side: a phone color sold in several parts (ZAA / CHA …) asks for the
part (only parts with a price), each with its own price, and the customer's own order
cancel (confirmation, only before a receipt)."""
from __future__ import annotations

from app import texts
from app.engine import variant_label

from .conftest import ADMIN_CHAT, CUSTOMER_CHAT, push_callback, push_message
from .test_phase2 import _callbacks

PHONE = {
    "code": 900, "name": "آیفون ۱۷ پرو", "group": 1, "unit_price": 480_000_000.0,
    "available_qty": 1.0, "image": None, "priced_by": "pricelist",
    "variants": [
        {"id": 11, "color": "Silver", "part": "ZAA", "unit_price": 500_000_000.0, "available": True},
        {"id": 12, "color": "Silver", "part": "CHA", "unit_price": 480_000_000.0, "available": True},
        {"id": 13, "color": "Silver", "part": "LLA", "unit_price": None, "available": False},
        {"id": 14, "color": "Orange", "part": "ZAA", "unit_price": 510_000_000.0, "available": True},
    ],
}


def _with_parts(shopapi):
    shopapi.products.append(dict(PHONE, variants=[dict(v) for v in PHONE["variants"]]))


def test_variant_label():
    assert variant_label({"name": "Silver", "part": "CHA"}) == "Silver — CHA"
    assert variant_label({"name": "مشکی", "part": ""}) == "مشکی"


def test_color_then_part_with_its_own_price(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    _with_parts(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        colors = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        # one button per color name
        assert [c for c in colors if c.startswith("col:")] == ["col:900:11", "col:900:14"]
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.CHOOSE_PART.format(name="آیفون ۱۷ پرو", color="Silver")
        parts = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "prt:900:11" in parts and "prt:900:12" in parts
        assert "prt:900:13" not in parts                       # no price in this list
        labels = [t for row in bot_apis["bale"].buttons_for(CUSTOMER_CHAT) for t, _ in row]
        assert "CHA — 480,000,000" in labels
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prt:900:12")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "Silver — CHA" in body and "480,000,000" in body
        assert "vadd:900:12:1" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "vadd:900:12:1")
        cart = engine.cart.items("bale", CUSTOMER_CHAT)
        assert cart[0]["variant_id"] == 12 and cart[0]["name"].endswith("Silver — CHA")
        # a color with one part only goes straight to its price
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "col:900:14")
        assert "Orange — ZAA" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "checkout")

    env(scenario)
    order = next(iter(shopapi.orders.values()))
    assert [(i["variant_id"], i["part"]) for i in order["items"]] == [(12, "CHA")]


# ---- 4: cancel -------------------------------------------------------------------------------
async def _ordered(engine):
    await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
    await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
    await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
    await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
    await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")


def test_customer_cancels_after_confirming(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _ordered(engine)
        assert "ocx:1" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)     # in the order message
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "ocx:1")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.CANCEL_ORDER_CONFIRM.format(order_id=1)
        assert shopapi.orders[1]["status"] == "awaiting_payment"           # not before yes
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "ocy:1")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.CANCEL_ORDER_DONE.format(order_id=1)
        state, _data = engine.store.get_conversation("bale", CUSTOMER_CHAT)
        assert state != "await_receipt"

    env(scenario)
    assert shopapi.orders[1]["status"] == "cancelled"
    assert bot_apis["bale"].texts(ADMIN_CHAT) == [] or all(
        "لغو" not in t for t in bot_apis["bale"].texts(ADMIN_CHAT))


def test_cancel_button_in_my_orders_and_none_after_receipt(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _ordered(engine)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "orders")
        assert "ocx:1" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        shopapi.orders[1]["status"] = "receipt_uploaded"                  # receipt sent
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "orders")
        assert "ocx:1" not in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 8, CUSTOMER_CHAT, "ocy:1")       # an old button
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CANCEL_ORDER_RECEIPT_SENT

    env(scenario)
    assert shopapi.orders[1]["status"] == "receipt_uploaded"
