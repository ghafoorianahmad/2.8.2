"""Phase 2 (Bale): deep links, receipts as photo or file, statement, closed mode,
order tracking messages."""
from __future__ import annotations

from app import texts

from .conftest import (
    CUSTOMER_CHAT,
    own_contact,
    push_callback,
    push_message,
)


def _callbacks(api, chat_id):
    return [cb for row in api.buttons_for(chat_id) for _, cb in row]


async def _order_and_wait_for_receipt(engine):
    await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
    await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
    await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
    await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
    await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")


# ---- deep link / product code ----------------------------------------------
def test_start_with_product_parameter_opens_the_product(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start kala_104")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "کالای د" in body and "4,000" in body
        assert "add:104:1" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "add:104:1")
        assert engine.store.cart_list("bale", CUSTOMER_CHAT)[0]["kala_code"] == 104

    env(scenario)


def test_deep_link_survives_registration(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start kala_101")
        assert texts.ASK_CONTACT in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="hello")      # refused
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, contact=own_contact(CUSTOMER_CHAT))
        assert "کالای الف" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_typed_product_code_is_the_fallback(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="kala_102")
        assert "کالای ب" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="۱۰۴")
        assert "کالای د" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="999")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.PRODUCT_NOT_FOUND

    env(scenario)


def test_code_typed_before_registration_is_shown_after_it(env, bot_apis, shopapi):
    """Bale drops the /start parameter: the customer types the site's code instead."""
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert texts.ASK_CONTACT in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="کد کالا: ۱۰۱")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.PRODUCT_AFTER_CONTACT
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="09121234567")  # typed phone: refused
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CONTACT_BUTTON_ONLY
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, contact=own_contact(CUSTOMER_CHAT))
        assert "کالای الف" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_new_user_typing_a_bare_code_keeps_it(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="104")
        assert texts.ASK_CONTACT in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, contact=own_contact(CUSTOMER_CHAT))
        assert "کالای د" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_start_with_bare_code_parameter(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start 104")
        assert "کالای د" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_out_of_stock_deep_link_shows_unavailable(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start kala_103")
        assert texts.OUT_OF_STOCK in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert not any(cb.startswith("add:") for cb in _callbacks(bot_apis["bale"], CUSTOMER_CHAT))

    env(scenario)


# ---- receipts ----------------------------------------------------------------
def test_receipt_as_image_document(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_and_wait_for_receipt(engine)
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, document={
            "file_id": "DOC", "mime_type": "image/png", "file_size": 1000})
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_RECEIVED
        order = next(iter(shopapi.orders.values()))
        assert order["status"] == "receipt_uploaded" and order["receipt_ref"] == "DOC"

    env(scenario)


def test_receipt_rejections(env, settings, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_and_wait_for_receipt(engine)
        order = next(iter(shopapi.orders.values()))
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, document={
            "file_id": "PDF", "mime_type": "application/pdf"})
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_EXPECTED_PHOTO
        await push_message(engine, "bale", 7, CUSTOMER_CHAT, document={
            "file_id": "BIG", "mime_type": "image/jpeg", "file_size": 6 * 1024 * 1024})
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_TOO_LARGE
        # declared small, but the bytes are not an image
        bot_apis["bale"].file_bytes = b"<html>"
        await push_message(engine, "bale", 8, CUSTOMER_CHAT, photo=[{"file_id": "P"}])
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_EXPECTED_PHOTO
        # getFile reports a size over the limit: not downloaded at all
        bot_apis["bale"].file_size = 6 * 1024 * 1024
        downloads = bot_apis["bale"].methods().count("download")
        await push_message(engine, "bale", 9, CUSTOMER_CHAT, photo=[{"file_id": "P"}])
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_TOO_LARGE
        assert bot_apis["bale"].methods().count("download") == downloads
        # Bot API unreachable
        bot_apis["bale"].file_size = None
        bot_apis["bale"].raise_on.add("getFile")
        await push_message(engine, "bale", 10, CUSTOMER_CHAT, photo=[{"file_id": "P"}])
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_DOWNLOAD_FAILED
        assert order["status"] == "awaiting_payment"

    env(scenario)


def test_receipt_rate_limit(env, settings, bot_apis, shopapi):
    settings.receipt_rate_count = 2
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_and_wait_for_receipt(engine)
        bot_apis["bale"].file_bytes = b"not an image"
        for i in range(2):
            await push_message(engine, "bale", 10 + i, CUSTOMER_CHAT, photo=[{"file_id": "P"}])
        await push_message(engine, "bale", 20, CUSTOMER_CHAT, photo=[{"file_id": "P"}])
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_RATE_LIMITED

    env(scenario)


# ---- statement -----------------------------------------------------------------
def test_statement_is_paginated(env, settings, bot_apis, shopapi):
    settings.statement_page_size = 1
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.statement = {
        "balance": 700, "side": "debtor", "total": 2, "page": 1, "page_size": 1,
        "items": [{"date": "1405/07/19", "kind": "فاکتور فروش", "doc_no": "2672", "debit": 700,
                   "credit": 0, "balance": 700, "side": "debtor", "description": ""}],
    }

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "stmt:1")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "1405/07/19" in body and "2672" in body and texts.SIDE_DEBTOR in body
        assert "stmt:2" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "stmt:2")
        assert shopapi.statement_requests[-1]["page"] == "2"

    env(scenario)


# ---- closed mode -------------------------------------------------------------
PHONE = {
    "code": 900, "name": "گوشی آزمایشی", "group": 1, "unit_price": 525_000_000.0,
    "available_qty": 1.0, "image": None, "priced_by": "pricelist",
    "variants": [{"id": 11, "color": "مشکی", "unit_price": 525_000_000.0, "available": True}],
}


def _with_phone(shopapi):
    shopapi.products.append(dict(PHONE, variants=[dict(v) for v in PHONE["variants"]]))


async def _phone_in_cart(engine, start=1):
    await push_message(engine, "bale", start, CUSTOMER_CHAT, text="900")
    await push_callback(engine, "bale", start + 1, CUSTOMER_CHAT, "col:900:11")
    await push_callback(engine, "bale", start + 2, CUSTOMER_CHAT, "vadd:900:11:1")


def test_closed_sales_block_only_phones(env, bot_apis, shopapi):
    """v2.5.0: list not updated / closing time / Friday / holiday -> no PHONE orders;
    accessories and other items stay orderable."""
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    _with_phone(shopapi)
    shopapi.closed = True

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        first = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert texts.SHOP_CLOSED_NOTICE not in first and "1,000" in first   # no phone here
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "pg:1:2")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert body.startswith(texts.SHOP_CLOSED_NOTICE)        # this page shows the phone
        assert "گوشی آزمایشی" in body                            # last prices stay visible
        await _phone_in_cart(engine, start=4)
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "cart")
        assert "checkout" not in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 8, CUSTOMER_CHAT, "checkout")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SALES_CLOSED
        assert len(shopapi.orders) == 0
        # remove the phone: the accessory alone is ordered
        await push_callback(engine, "bale", 9, CUSTOMER_CHAT, "vdel:900:11")
        await push_callback(engine, "bale", 10, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 11, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 12, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 13, CUSTOMER_CHAT, "checkout")
        assert len(shopapi.orders) == 1

    env(scenario)


def test_accessories_order_normally_while_phone_sales_are_closed(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.closed = True

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        # a list without phones: no closed banner
        assert texts.SHOP_CLOSED_NOTICE not in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "cart")
        assert "checkout" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "checkout")
        assert len(shopapi.orders) == 1
        assert texts.RECEIPT_DEADLINE_NOTE.format(minutes="30") in \
            bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_holiday_and_friday_have_their_own_closed_text(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    _with_phone(shopapi)
    shopapi.closed = True
    shopapi.closed_reason = "holiday"

    async def scenario(engine, adapters, api):
        await _phone_in_cart(engine)
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "checkout")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SALES_CLOSED_HOLIDAY
        engine._shop_state = None
        shopapi.closed_reason = "weekday_closed"
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SALES_CLOSED_FRIDAY

    env(scenario)


def test_sales_closed_between_cart_and_checkout_is_refused_cleanly(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    _with_phone(shopapi)

    async def scenario(engine, adapters, api):
        await _phone_in_cart(engine)
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "cart")   # caches "open"
        shopapi.closed = True
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SALES_CLOSED
        assert len(shopapi.orders) == 0
        assert engine.store.cart_list("bale", CUSTOMER_CHAT) != []   # cart kept

    env(scenario)


def test_checkout_states_the_30_minute_receipt_deadline(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_and_wait_for_receipt(engine)
        assert texts.RECEIPT_DEADLINE_NOTE.format(minutes="30") in \
            bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_receipt_after_the_deadline_is_answered_clearly(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_and_wait_for_receipt(engine)
        shopapi.receipt_too_late = True
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, photo=[{"file_id": "P1"}])
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_TOO_LATE

    env(scenario)


def test_auto_cancelled_order_is_announced_to_the_customer(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_and_wait_for_receipt(engine)
        oid = next(iter(shopapi.orders))
        await engine.notify_customers_from_events()          # first run: position only
        shopapi.add_event("order_auto_cancelled", oid)
        assert await engine.notify_customers_from_events() == 1
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.ORDER_AUTO_CANCELLED.format(order_id=oid)

    env(scenario)


def test_open_shop_has_no_notice(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _order_and_wait_for_receipt(engine)
        assert texts.SHOP_CLOSED_NOTICE not in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


# ---- tracking ----------------------------------------------------------------
def test_invoiced_and_shipped_are_told_to_the_customer(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])
        await engine.notify_customers_from_events()          # first run: position only
        shopapi.add_event("order_partially_invoiced", order["id"])
        shopapi.add_event("order_invoiced", order["id"])
        shopapi.add_event("order_shipped", order["id"])
        shopapi.add_event("order_shipped", order["id"])       # duplicate: told once
        sent = await engine.notify_customers_from_events()
        assert sent == 3
        got = bot_apis["bale"].texts(CUSTOMER_CHAT)
        oid = order["id"]
        assert texts.ORDER_PARTIALLY_INVOICED.format(order_id=oid) in got
        assert texts.ORDER_INVOICED.format(order_id=oid) in got
        assert got.count(texts.ORDER_SHIPPED.format(order_id=oid)) == 1

    env(scenario)


def test_my_orders_shows_tracking_step(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])
        shopapi.orders[order["id"]].update(status="written", invoice_state="full")
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "orders")
        assert texts.ORDER_STATUS_FA["invoiced"] in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        shopapi.orders[order["id"]]["shipped_at"] = "t"
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "orders")
        assert texts.ORDER_STATUS_FA["shipped"] in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)
