"""v2.8.0 on the bot side: smart phone search (model -> color -> part -> order or
«درخواست خرید»), the payment message after staff confirmed the stock, phones
without stock, and «وقتی فروش باز شد خبرم کن» (one message per opening)."""
from __future__ import annotations

from app import texts
from app.engine import SALES_SEEN_KEY

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_phase3 import PHONE, _callbacks


def _row(key, model, color, part, price, *, action="purchase", code=None, variant=None,
         index=0):
    return {"row_key": key, "model_index": index, "model": model, "section": "iPHONE",
            "description": model, "color": color, "part": part, "price": price,
            "kala_code": code, "variant_id": variant, "action": action, "score": 1.0}


def _shop(shopapi):
    shopapi.products.append(dict(PHONE, variants=[dict(v) for v in PHONE["variants"]]))
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.phone_rows = [
        _row("a", "17 Pro 256", "مشکی", "ZAA", 525_000_000, action="order", code=900,
             variant=11),
        _row("b", "17 Pro 256", "مشکی", "CHA", 515_000_000),
        _row("c", "17 Pro 256", "Silver", "CHA", 520_000_000),
        _row("d", "17 Promax 256", "Blue", "ZAA", 600_000_000, index=1),
    ]


def test_typed_name_lists_models_then_colors_then_parts(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="17 pro")
        assert "17 pro" in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert _callbacks(bot_apis["bale"], CUSTOMER_CHAT)[:2] == ["psm:0", "psm:1"]
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "psm:0")
        assert {"psc:0:0", "psc:0:1"} <= set(_callbacks(bot_apis["bale"], CUSTOMER_CHAT))
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "psc:0:0")
        assert {"psr:0", "psr:1"} <= set(_callbacks(bot_apis["bale"], CUSTOMER_CHAT))
        # an orderable row opens the usual color screen with «افزودن به سبد»
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "psr:0")
        assert any(cb.startswith("vadd:900:11:") for cb in _callbacks(bot_apis["bale"], CUSTOMER_CHAT))
        # a row that is not mapped / not in stock: price + «درخواست خرید»
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "psm:0")
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "psc:0:0")
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "psr:1")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "CHA" in body
        assert "pbr:1" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 8, CUSTOMER_CHAT, "pbr:1")
        assert shopapi.purchase_requests == [
            {"platform": "bale", "chat_id": str(CUSTOMER_CHAT), "qty": 1, "row_key": "b"}]
        assert "درخواست خرید" in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        # a second tap does not send it again
        await push_callback(engine, "bale", 9, CUSTOMER_CHAT, "pbr:1")
        assert len(shopapi.purchase_requests) == 1

    env(scenario)


def test_single_model_and_color_goes_straight_to_the_row(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="promax")
        assert "pbr:0" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)

    env(scenario)


def test_search_button_tries_the_price_list_then_products(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "search")
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="17 Pro")
        assert "psm:0" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        # nothing anywhere: the free-text item request is offered
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "search")
        await push_message(engine, "bale", 5, CUSTOMER_CHAT, text="چیزی که نیست")
        assert "ireq" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "درخواست کالای ناموجود" in bot_apis["bale"].last_text(CUSTOMER_CHAT)

    env(scenario)


def test_phone_without_stock_offers_purchase_request(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.products[-1]["stock_qty"] = 0.0

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        callbacks = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "pbv:900:11" in callbacks and not any(c.startswith("vadd:") for c in callbacks)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "pbv:900:11")
        assert shopapi.purchase_requests[-1] == {
            "platform": "bale", "chat_id": str(CUSTOMER_CHAT), "qty": 1,
            "kala_code": 900, "variant_id": 11}

    env(scenario)


def test_confirmed_purchase_request_asks_for_payment(env, bot_apis, shopapi):
    _shop(shopapi)
    user = shopapi.users[("bale", str(CUSTOMER_CHAT))]
    shopapi.orders[7] = {
        "id": 7, "status": "awaiting_payment", "total": 520_000_000.0, "items": [
            {"kala_code": 900, "name": "گوشی آزمایشی — Silver — CHA", "qty": 1,
             "unit_price": 520_000_000.0}],
        "payment_info": None, "user_id": user["id"],
        "_platform": "bale", "_chat_id": str(CUSTOMER_CHAT)}

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()                    # first run: cursor only
        shopapi.add_event("purchase_order_created", 7)
        await engine.admin_sweep()
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "سفارش شمارهٔ 7" in body or "سفارش شمارهٔ ۷" in body
        # v2.8.2: the payment details follow from staff, in their own message
        assert texts.WAIT_PAYMENT_INFO in body and "6037" not in body
        state, _data = engine.store.get_conversation("bale", str(CUSTOMER_CHAT))
        assert state != "await_receipt"
        shopapi.orders[7]["payment_info"] = {"card_number": "6037-0000-1111-2222",
                                             "bank": "ملت"}
        shopapi.add_event("order_payment_info", 7)
        await engine.notify_customers_from_events()
        body = bot_apis["bale"].last_text(CUSTOMER_CHAT).replace("‎", "")
        assert "6037-0000-1111-2222" in body and "بانک: ملت" in body
        assert "شبا" not in body                          # empty fields are left out
        assert "ocx:7" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        state, data = engine.store.get_conversation("bale", str(CUSTOMER_CHAT))
        assert state == "await_receipt" and data["order_id"] == 7
        shopapi.add_event("purchase_order_created", 7)      # never twice
        sent = len(bot_apis["bale"].texts(CUSTOMER_CHAT))
        await engine.admin_sweep()
        assert len(bot_apis["bale"].texts(CUSTOMER_CHAT)) == sent

    env(scenario)


def test_notify_when_sales_open_once(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.closed = True

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        assert "snot" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "snot")
        assert texts.SALES_NOTIFY_OK in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert engine.store.get_value(SALES_SEEN_KEY) == "0"
        await engine.admin_sweep()                    # still closed: nothing
        assert texts.SALES_OPENED_NOTICE not in bot_apis["bale"].texts(CUSTOMER_CHAT)
        shopapi.closed = False
        await engine.admin_sweep()
        assert bot_apis["bale"].texts(CUSTOMER_CHAT).count(texts.SALES_OPENED_NOTICE) == 1
        assert engine.store.list_sales_watch() == []
        shopapi.closed = True
        await engine.admin_sweep()
        shopapi.closed = False
        await engine.admin_sweep()                    # not subscribed any more
        assert bot_apis["bale"].texts(CUSTOMER_CHAT).count(texts.SALES_OPENED_NOTICE) == 1

    env(scenario)


def test_cart_item_without_stock_has_a_clear_message(env, bot_apis, shopapi):
    """v2.8.2: in stock when added, gone at checkout: one tap «ثبت درخواست خرید»."""
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="900")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "vadd:900:11:1")
        assert engine.cart.items("bale", str(CUSTOMER_CHAT))
        shopapi.refuse_items[900] = "has no stock; purchase request"
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "checkout")
        assert "انبار فروشگاه موجود نیست" in bot_apis["bale"].last_text(CUSTOMER_CHAT)
        assert "pbv:900:11" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)

    env(scenario)
