"""Phase 5: the bot reports suspicious acts to shopapi; logs never show secrets."""
from __future__ import annotations

import logging

from app import texts
from app.logging_setup import RedactingFilter, redact
from app.ratelimit import RateLimiter

from .conftest import CUSTOMER_CHAT, OTHER_CHAT, own_contact, push_message

TOKEN = "1234567890:" + "Ab_-" * 9


def test_foreign_contact_is_reported(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, contact=own_contact(OTHER_CHAT))
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CONTACT_NOT_OWN
        # a typed number is a user mistake, not an attack: not reported
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="09121234567")

    env(scenario)
    assert shopapi.security_reports == [
        {"kind": "contact_not_own", "platform": "bale", "chat_id": str(CUSTOMER_CHAT)}]


def test_rate_limit_flood_is_one_report(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    limiter = RateLimiter(max_events=2, window=60.0, clock=lambda: 0.0)

    async def scenario(engine, adapters, api):
        for index in range(8):
            await push_message(engine, "bale", index + 1, CUSTOMER_CHAT, text="سلام")
        assert bot_apis["bale"].last_text(CUSTOMER_CHAT) == texts.RATE_LIMITED

    env(scenario, rate_limiter=limiter)
    assert [r["kind"] for r in shopapi.security_reports] == ["rate_limited"]


def test_report_failure_never_breaks_the_chat(env, bot_apis, shopapi):
    shopapi.down = True

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, contact=own_contact(OTHER_CHAT))

    env(scenario)   # no exception escapes


def test_redact_masks_tokens_keys_and_passwords():
    text = redact(f"GET https://tapi.bale.ai/bot{TOKEN}/getUpdates -> 502; "
                  "headers X-API-Key: k3y-very-secret Authorization: Bearer abcdefghijklmnop "
                  "DB_PASSWORD=p4ss; ACCOUNTING_PASSWORD: zz9")
    for secret in (TOKEN, "k3y-very-secret", "abcdefghijklmnop", "p4ss", "zz9"):
        assert secret not in text
    assert "tapi.bale.ai/bot***/getUpdates" in text
    assert redact("order 12 created for 09121234567") == "order 12 created for 09121234567"


def test_filter_cleans_args_and_exception_text():
    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "send failed: %s", (
        f"https://tapi.bale.ai/bot{TOKEN}/sendMessage",), None)
    try:
        raise RuntimeError(f"connect to /bot{TOKEN}/x failed")
    except RuntimeError:
        import sys

        record.exc_info = sys.exc_info()
    assert RedactingFilter().filter(record)
    assert TOKEN not in record.getMessage()
    assert TOKEN not in (record.exc_text or "")
