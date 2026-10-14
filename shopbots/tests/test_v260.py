"""v2.6.0 on the bot side: rate limits that tolerate quick taps, the sales gate
re-checked at the final checkout, no checkout without a payment card (never a
placeholder), «درخواست کالای ناموجود», and the statement as one PDF."""
from __future__ import annotations

import time

import pytest

from app import texts
from app.cards.render import find_browser
from app.cards.statement_pdf import statement_html

from .conftest import ADMIN_CHAT, CUSTOMER_CHAT, push_callback, push_message
from .test_phase2 import _callbacks, _phone_in_cart, _with_phone


def _warnings(api, chat_id=CUSTOMER_CHAT) -> int:
    return api.texts(chat_id).count(texts.RATE_LIMITED)


# ---- 6: rate limits ------------------------------------------------------------------------
def test_quick_plus_minus_taps_are_not_flooding(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        handled = [await push_callback(engine, "bale", 10 + i, CUSTOMER_CHAT,
                                       f"qty:101:{1 + i % 5}") for i in range(40)]
        assert all(handled)

    env(scenario)
    assert _warnings(bot_apis["bale"]) == 0


def test_flood_warns_once_per_window_and_start_always_works(env, bot_apis, shopapi, settings):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    settings.rate_limit_messages = 3
    settings.rate_limit_callbacks = 5

    async def scenario(engine, adapters, api):
        for i in range(10):
            await push_message(engine, "bale", 1 + i, CUSTOMER_CHAT, text="سلام")
        for i in range(12):
            await push_callback(engine, "bale", 20 + i, CUSTOMER_CHAT, "cart")
        # /start is never limited: the customer can always start over
        before = len(bot_apis["bale"].texts(CUSTOMER_CHAT))
        assert await push_message(engine, "bale", 50, CUSTOMER_CHAT, text="/start")
        assert len(bot_apis["bale"].texts(CUSTOMER_CHAT)) == before + 1
        assert texts.MAIN_MENU in bot_apis["bale"].last_text(CUSTOMER_CHAT)

    env(scenario)
    api = bot_apis["bale"]
    assert _warnings(api) == 1                                 # one warning, not one per tap
    # refused taps still stop the button's spinner (no alert)
    assert len(api.answered) >= 12


def test_warning_again_after_the_window(env, bot_apis, shopapi, settings):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    settings.rate_limit_messages = 1
    clock = [1000.0]

    async def scenario(engine, adapters, api):
        engine.rate_limiter._clock = lambda: clock[0]
        engine.rate_warner._clock = lambda: clock[0]
        for i in range(3):
            await push_message(engine, "bale", 1 + i, CUSTOMER_CHAT, text="x")
        clock[0] += 61
        for i in range(3):
            await push_message(engine, "bale", 10 + i, CUSTOMER_CHAT, text="x")

    env(scenario)
    assert _warnings(bot_apis["bale"]) == 2


# ---- 7: the sales gate at the final checkout -----------------------------------------------
def test_checkout_rereads_the_sales_state(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    _with_phone(shopapi)

    async def scenario(engine, adapters, api):
        await _phone_in_cart(engine)
        await push_callback(engine, "bale", 10, CUSTOMER_CHAT, "cart")
        assert "checkout" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        shopapi.closed = True                                  # closed meanwhile
        engine._shop_state = (time.monotonic(), {"closed": False, "payment_ready": True})
        await push_callback(engine, "bale", 11, CUSTOMER_CHAT, "checkout")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SALES_CLOSED
        assert len(shopapi.orders) == 0

    env(scenario)


# ---- 8: no payment card -> no checkout, never a placeholder --------------------------------
def test_no_card_no_checkout(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.payment_card = ""

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "cart")
        cart = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert texts.PAYMENT_NOT_READY in cart
        assert "checkout" not in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "checkout")   # an old button
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.PAYMENT_NOT_READY
        assert len(shopapi.orders) == 0

    env(scenario)
    assert not any("XXXX" in t for t in bot_apis["bale"].texts())


def test_shopapi_refusal_for_missing_card_is_explained(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        # the state says "ready"; shopapi refuses at the order itself
        shopapi.card_removed_meanwhile = True
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.PAYMENT_NOT_READY

    env(scenario)


# ---- 12: «درخواست کالای ناموجود» -------------------------------------------------------------
def test_item_request_flow(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert "ireq" in _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "ireq")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.ITEM_REQUEST_ASK
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="کالای")
        callbacks = _callbacks(bot_apis["bale"], CUSTOMER_CHAT)
        assert "ireqk:103" in callbacks and "ireqt" in callbacks
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "ireqk:103")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.ITEM_REQUEST_SENT
        # free text, nothing found
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "ireq")
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, text="نوکیا ۳۳۱۰")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == \
            texts.ITEM_REQUEST_NONE.format(text="نوکیا 3310")
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "ireqt")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.ITEM_REQUEST_SENT
        # the owner hears about it in the admin chat
        await engine.notify_customers_from_events()
        shopapi.add_event("item_request", 1)
        await engine.notify_customers_from_events()

    env(scenario)
    assert [r["kala_code"] for r in shopapi.item_requests] == [103, None]
    assert shopapi.item_requests[1]["text"] == "نوکیا 3310"
    assert not shopapi.orders                                  # no order, no payment
    assert texts.ITEM_REQUEST_NOTICE.format(product="کالای ج", name="علی") in \
        bot_apis["bale"].texts(ADMIN_CHAT)


def test_item_request_limit(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.item_request_limit = 0

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "ireq")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="چیزی")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "ireqt")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.ITEM_REQUEST_TOO_MANY

    env(scenario)


# ---- 13: statement as one PDF ---------------------------------------------------------------
STATEMENT = {
    "person_code": 7001, "customer_name": "علی آزمایشی", "from_date": "1405/07/01",
    "to_date": "1405/07/05", "opening_balance": 0, "opening_side": "zero",
    "rows": [
        {"date": "1405/07/01", "kind": "فاکتور فروش", "doc_no": "10", "description": "گوشی",
         "debit": 500.0, "credit": 0.0, "balance": 500.0, "side": "debtor"},
        {"date": "1405/07/05", "kind": "سند", "doc_no": "11", "description": "واریز",
         "debit": 0.0, "credit": 200.0, "balance": 300.0, "side": "debtor"},
    ],
    "total_debit": 500.0, "total_credit": 200.0, "balance": 300.0, "side": "debtor",
    "truncated": False,
}


def test_statement_html_has_everything():
    page = statement_html(STATEMENT, shop="عصر ارتباطات ۲")
    for part in ("علی آزمایشی", "۷۰۰۱", "۱۴۰۵/۰۷/۰۱", "۱۴۰۵/۰۷/۰۵", "تاریخ چاپ", "بدهکار",
                 "بستانکار", "مانده", "ماندهٔ نهایی", "۳۰۰ ریال — بدهکار", "@page{size:A4",
                 'dir="rtl"', "Vazirmatn"):
        assert part in page, part


@pytest.mark.skipif(find_browser() is None, reason="no Chromium/Edge here")
def test_statement_is_sent_as_one_pdf(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.statement_full = STATEMENT

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "stmt:1")

    env(scenario)
    docs = bot_apis["bale"].documents
    assert len(docs) == 1 and b"%PDF" in docs[0] and b"statement-7001.pdf" in docs[0]
    assert not shopapi.statement_requests                      # no paged text statement


def test_statement_falls_back_to_text_without_a_pdf(env, bot_apis, shopapi, monkeypatch):
    from app.cards import statement_pdf

    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.statement_full = STATEMENT
    monkeypatch.setattr(statement_pdf, "_print_pdf", lambda html: None)

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "stmt:1")

    env(scenario)
    assert not bot_apis["bale"].documents
    assert shopapi.statement_requests                          # the paged text instead
