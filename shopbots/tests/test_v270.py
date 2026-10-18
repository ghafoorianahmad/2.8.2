"""v2.7.0 on the bot side: «ارسال شد» names the courier only when staff entered one."""
from __future__ import annotations

import pytest

from app import texts

from .conftest import CUSTOMER_CHAT, push_callback, push_message


async def _ordered(engine):
    await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
    await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
    await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
    await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
    await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")


@pytest.mark.parametrize("name,phone,extra", [
    ("علی پیک", "09123456789", "🛵 پیک: علی پیک — تلفن: 09123456789"),
    ("علی پیک", "", "🛵 پیک: علی پیک"),
    ("", "09123456789", "🛵 تلفن پیک: 09123456789"),
    ("", "", None),
])
def test_shipped_message_with_optional_courier(env, bot_apis, shopapi, name, phone, extra):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await _ordered(engine)
        await engine.notify_customers_from_events()                  # sets the cursor
        shopapi.orders[1].update(status="approved", shipped_at="t",
                                 courier_name=name or None, courier_phone=phone or None)
        shopapi.add_event("order_shipped", 1)
        await engine.notify_customers_from_events()

    env(scenario)
    plain = texts.ORDER_SHIPPED.format(order_id=1)
    sent = [t for t in bot_apis["bale"].texts(CUSTOMER_CHAT) if t.startswith(plain[:10])]
    assert sent == [plain if extra is None else f"{plain}\n{extra}"]


def test_no_postal_tracking_code_in_bot_texts():
    for key in dir(texts):
        value = getattr(texts, key)
        if isinstance(value, str):
            assert "کد رهگیری" not in value and "رهگیری پست" not in value, key
