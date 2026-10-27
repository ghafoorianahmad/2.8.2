"""v2.11.0: the site's cart reaches the bot as ``/start c_<code>``; shopapi turns
each line into a «درخواست خرید - استعلام قیمت» and the customer sees the list."""
from __future__ import annotations

from app import texts
from app.core import looks_like_cart_ref, looks_like_model_ref

from .conftest import CUSTOMER_CHAT, own_contact, push_message

CART = "c_xYpSmCCE6XvoAC"


def test_cart_ref_shape():
    assert looks_like_cart_ref(CART) and looks_like_cart_ref("c_" + "xYpSmCC" * 8)
    for sent in ("c_", "c_short", "c_" + "xYpSmCC" * 9, "m_iphone-17", "c_xYpSm!C"):
        assert not looks_like_cart_ref(sent), sent
    assert not looks_like_model_ref(CART)


def test_start_with_a_cart_creates_purchase_requests(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text=f"/start {CART}")
        assert shopapi.cart_codes == [CART]
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert body.startswith("☑ سبد خرید شما از سایت ثبت شد")
        assert "• Galaxy S26 Ultra، رنگ مشکی — 2 عدد" in body
        assert "• پاوربانک Anker 737 — 1 عدد" in body
        assert texts.SITE_CART_UNKNOWN.format(count=1) in body

    env(scenario)


def test_cart_typed_before_registration_is_sent_after_it(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text=f"/start {CART}")
        assert texts.ASK_CONTACT in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert shopapi.cart_codes == []
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, contact=own_contact(CUSTOMER_CHAT))
        assert shopapi.cart_codes == [CART]
        assert "سبد خرید شما از سایت ثبت شد" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_pasted_cart_code_and_repeat(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.cart_answer = {**shopapi.cart_answer, "repeated": True}

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text=CART)
        assert shopapi.cart_codes == [CART]
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SITE_CART_REPEATED

    env(scenario)


def test_too_many_and_server_down(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        shopapi.cart_status = 429
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text=f"/start {CART}")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.ITEM_REQUEST_TOO_MANY
        shopapi.cart_status = None
        shopapi.down = True
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text=CART)
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.SERVICE_UNAVAILABLE

    env(scenario)
