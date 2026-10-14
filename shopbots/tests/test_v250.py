"""v2.5.0 on the bot side: owner alerts for duplicate order numbers and
timed-out orders that already exist in accounting, admin error texts."""
from __future__ import annotations

from app import texts
from app.shopapi import ShopApiRejected, format_admin_error

from .conftest import ADMIN_CHAT


def test_owner_alerts_for_accounting_problems(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await engine.notify_customers_from_events()          # first run: position only
        shopapi.add_event("accounting_duplicate_order", 12)
        shopapi.add_event("order_timeout_written", 13)
        await engine.notify_customers_from_events()
        await engine.notify_customers_from_events()          # nothing twice

    env(scenario)
    sent = bot_apis["bale"].texts(ADMIN_CHAT)
    assert sent == [texts.DUPLICATE_ORDER_NOTICE.format(list_id=12),
                    texts.TIMEOUT_WRITTEN_NOTICE.format(list_id=13)]
    assert all("حذف" in s for s in sent)                   # nothing is deleted


def test_admin_errors_for_status_and_duplicate_are_persian():
    status = ShopApiRejected("x", status=409, detail="Order status code is not configured")
    dup = ShopApiRejected("x", status=409,
                          detail="Duplicate accounting order number; nothing was written")
    assert format_admin_error(status) == texts.ADMIN_STATUS_NOT_CONFIGURED
    assert format_admin_error(dup) == texts.ADMIN_DUPLICATE_ORDER_NO
