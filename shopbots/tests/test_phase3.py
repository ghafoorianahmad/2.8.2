"""Phase 3 (bot side): phone colors — price after the color pick, a new price
announced when the color changes, cart lines per color, inquiries for colors
without a price, and owner alerts from the price-list / proxy events."""
from __future__ import annotations

from app import texts
from app.store import Store

from .conftest import ADMIN_CHAT, CUSTOMER_CHAT, push_callback, push_message

PHONE = {
    "code": 900, "name": "گوشی آزمایشی", "group": 3, "unit_price": 525_000_000.0,
    "available_qty": 1.0, "image": None, "priced_by": "pricelist",
    "variants": [
        {"id": 11, "color": "مشکی", "unit_price": 525_000_000.0, "available": True},
        {"id": 12, "color": "طلایی", "unit_price": 605_000_000.0, "available": True},
        {"id": 13, "color": "آبی", "unit_price": None, "available": False},
    ],
}


def _callbacks(api, chat_id):
    return [cb for row in api.buttons_for(chat_id) for _, cb in row]


def _shop(shopapi):
    shopapi.products.append(dict(PHONE, variants=[dict(v) for v in PHONE["variants"]]))
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)


async def _open_phone(engine):
    await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")


def test_phone_shows_colors_without_price(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)

    env(scenario)
    bale = bot_apis["bale"]
    text = bale.last_text_any(CUSTOMER_CHAT)
    assert "رنگ را انتخاب کنید" in text and "525" not in text
    callbacks = _callbacks(bale, CUSTOMER_CHAT)
    assert {"col:900:11", "col:900:12", "col:900:13"} <= set(callbacks)
    assert not any(cb.startswith("add:") for cb in callbacks)


def test_pick_color_shows_price_and_change_announces_new_price(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        first = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "col:900:12")
        return first

    first = env(scenario)
    bale = bot_apis["bale"]
    assert "مشکی" in first and "525,000,000" in first and "🔄" not in first
    second = bale.last_text_any(CUSTOMER_CHAT)
    assert "🔄" in second and "طلایی" in second and "605,000,000" in second
    # the customer also gets the new price as a toast
    assert any("605,000,000" in str(a.get("text", "")) for a in bale.answered)
    assert "vadd:900:12:1" in _callbacks(bale, CUSTOMER_CHAT)


def test_price_is_read_again_when_a_color_is_picked(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        shopapi.products[-1]["variants"][0]["unit_price"] = 530_000_000.0   # new list
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")

    env(scenario)
    assert "530,000,000" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)


def test_color_to_cart_and_checkout_sends_variant(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:12")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "vqty:900:12:2")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "vadd:900:12:2")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "col:900:11")
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "vadd:900:11:1")
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "vinc:900:11")
        await push_callback(engine, "bale", 8, CUSTOMER_CHAT, "checkout")

    env(scenario)
    body = shopapi.order_bodies[-1]
    assert sorted((i["variant_id"], i["qty"]) for i in body["items"]) == [(11, 2.0), (12, 2.0)]
    order = shopapi.orders[1]
    assert order["total"] == 2 * 525_000_000 + 2 * 605_000_000


def test_cart_shows_each_color(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "vadd:900:11:1")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "col:900:12")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "vadd:900:12:1")
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "vdel:900:11")

    env(scenario)
    bale = bot_apis["bale"]
    cart = bale.last_text_any(CUSTOMER_CHAT)
    assert "طلایی" in cart and "مشکی" not in cart
    assert "vdel:900:12" in _callbacks(bale, CUSTOMER_CHAT)


def test_plain_add_is_refused_for_a_phone(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "add:900:1")
        return engine.cart.items("bale", CUSTOMER_CHAT)

    assert env(scenario) == []


def test_color_without_price_offers_inquiry(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:13")
        unavailable = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "inq:900:13")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "inq:900:13")   # not twice
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "vadd:900:13:1")
        return unavailable, engine.cart.items("bale", CUSTOMER_CHAT)

    unavailable, cart = env(scenario)
    assert "آبی" in unavailable and "قیمت ندارد" in unavailable
    assert shopapi.inquiries == [{"id": 1, "platform": "bale", "chat_id": CUSTOMER_CHAT,
                                  "kala_code": 900, "variant_id": 13}]
    assert texts.INQUIRY_SENT in bot_apis["bale"].texts(CUSTOMER_CHAT)
    assert cart == []


def test_product_list_line_for_phones(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.groups.append({"code": 3, "name": "گوشی"})

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:3")

    env(scenario)
    text = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
    assert "3 رنگ" in text or "۳ رنگ" in text
    assert "525" not in text


def test_owner_alerts_from_events(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await engine.notify_customers_from_events()          # first run: position only
        shopapi.add_event("pricelist_held", 7)
        shopapi.add_event("price_inquiry", 1)
        shopapi.add_event("proxies_all_dead", None)
        shopapi.inquiries.append({"id": 1})
        await engine.notify_customers_from_events()
        await engine.notify_customers_from_events()          # nothing twice

    env(scenario)
    sent = bot_apis["bale"].texts(ADMIN_CHAT)
    assert len(sent) == 3
    assert "شمارهٔ 7" in sent[0] or "شمارهٔ ۷" in sent[0]
    assert "گوشی آزمایشی" in sent[1] and "آبی" in sent[1]
    assert "پراکسی" in sent[2]


def test_old_cart_table_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE carts (platform TEXT NOT NULL, chat_id TEXT NOT NULL, "
        "kala_code INTEGER NOT NULL, name TEXT NOT NULL, qty REAL NOT NULL, "
        "unit_price REAL NOT NULL, PRIMARY KEY (platform, chat_id, kala_code));"
        "INSERT INTO carts VALUES ('bale','1',101,'x',2,1000);"
    )
    conn.commit()
    conn.close()
    store = Store(path)
    assert store.cart_list("bale", "1") == [
        {"kala_code": 101, "variant_id": 0, "name": "x", "qty": 2.0, "unit_price": 1000.0}
    ]
    store.cart_add("bale", "1", 101, "x — red", 1, 5, variant_id=3)
    assert len(store.cart_list("bale", "1")) == 2
    store.close()
