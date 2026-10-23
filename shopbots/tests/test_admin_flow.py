"""Admin flow: sweeps, notifications, approve/reject, admin-only guard."""
from __future__ import annotations

from app import texts
from app.utils import mask_phone

from .conftest import ADMIN_CHAT, CUSTOMER_CHAT, OTHER_CHAT, push_callback, push_message


def test_sweep_announces_pending_user_once(env, bot_apis, shopapi):
    user = shopapi.add_user(
        "bale", CUSTOMER_CHAT, name="علی رضایی", phone="09121234567", status="pending"
    )
    shopapi.person_match = {"code": 7001, "masked_name": "ع********"}

    async def scenario(engine, adapters, api):
        engine.settings.admin_chat_order_notices = True   # v2.9.1: opt-in
        first = await engine.admin_sweep()
        assert first == {"users": 1, "orders": 0, "notified": 0}

        notice = bot_apis["bale"].last_text_any(ADMIN_CHAT)
        assert texts.NEW_USER_NOTICE.splitlines()[0] in notice
        assert "bale" in notice
        assert mask_phone("09121234567") in notice
        assert "09121234567" not in notice          # never the full phone number
        assert "7001" in notice                     # suggested accounting code
        callbacks = [cb for row in bot_apis["bale"].buttons_for(ADMIN_CHAT) for _, cb in row]
        assert f"addu:{user['id']}" in callbacks
        assert f"adru:{user['id']}" in callbacks
        assert f"adsug:{user['id']}:7001" in callbacks

        # a second sweep announces nothing again
        second = await engine.admin_sweep()
        assert second == {"users": 0, "orders": 0, "notified": 0}

    env(scenario)


def test_admin_approves_user_with_typed_person_code(env, bot_apis, shopapi):
    user = shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        await push_callback(engine, "bale", 10, ADMIN_CHAT, f"addu:{user['id']}")
        assert bot_apis["bale"].last_text_any(ADMIN_CHAT) == texts.ADMIN_ASK_PERSON_CODE

        await push_message(engine, "bale", 11, ADMIN_CHAT, text="۷۰۰۱")  # Persian digits
        assert shopapi.users[("bale", CUSTOMER_CHAT)]["status"] == "approved"
        assert shopapi.users[("bale", CUSTOMER_CHAT)]["person_code"] == 7001
        assert bot_apis["bale"].last_text_any(ADMIN_CHAT) == texts.ADMIN_USER_APPROVED
        # the customer is notified and can shop
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.APPROVED_BY_ADMIN

    env(scenario)


def test_admin_approves_user_with_suggested_code(env, bot_apis, shopapi):
    user = shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")
    shopapi.person_match = {"code": 4242, "masked_name": "م****"}

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        await push_callback(engine, "bale", 10, ADMIN_CHAT, f"adsug:{user['id']}:4242")
        assert shopapi.users[("bale", CUSTOMER_CHAT)]["person_code"] == 4242
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.APPROVED_BY_ADMIN

    env(scenario)


def test_admin_rejects_user_and_notifies_customer(env, bot_apis, shopapi):
    user = shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        await push_callback(engine, "bale", 10, ADMIN_CHAT, f"adru:{user['id']}")
        assert shopapi.users[("bale", CUSTOMER_CHAT)]["status"] == "rejected"
        assert bot_apis["bale"].last_text_any(ADMIN_CHAT) == texts.ADMIN_USER_REJECTED
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.REJECTED_BY_ADMIN

    env(scenario)


def test_sweep_announces_receipt_with_photo_and_admin_approves(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        engine.settings.admin_chat_order_notices = True   # v2.9.1: opt-in
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 2}])
        await api.upload_receipt(order["id"], "RECEIPT-FILE", "bale", CUSTOMER_CHAT)
        engine.store.save_receipt(order["id"], "bale", CUSTOMER_CHAT, "RECEIPT-FILE")

        result = await engine.admin_sweep()
        assert result == {"users": 0, "orders": 1, "notified": 0}

        notice = bot_apis["bale"].last_text_any(ADMIN_CHAT)
        assert texts.NEW_RECEIPT_NOTICE.splitlines()[0] in notice
        assert str(order["id"]) in notice
        assert "2,000" in notice
        assert bot_apis["bale"].photos[-1]["photo"] == "RECEIPT-FILE"

        await push_callback(engine, "bale", 20, ADMIN_CHAT, f"adap:{order['id']}")
        assert shopapi.orders[order["id"]]["status"] == "written"
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.PAYMENT_APPROVED.format(order_id=1)

    env(scenario)


def test_admin_rejects_payment(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        # the real flow: the customer orders and uploads the receipt through the bot
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, photo=[{"file_id": "F"}])
        order = next(iter(shopapi.orders.values()))
        assert order["status"] == "receipt_uploaded"

        await engine.admin_sweep()
        await push_callback(engine, "bale", 20, ADMIN_CHAT, f"adrp:{order['id']}")
        assert shopapi.orders[order["id"]]["status"] == "rejected"
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.PAYMENT_REJECTED.format(order_id=1)

    env(scenario)


def test_admin_sees_plain_error_when_approval_fails(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.approve_payment_fails = True

    async def scenario(engine, adapters, api):
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])
        await api.upload_receipt(order["id"], "F", "bale", CUSTOMER_CHAT)
        await engine.admin_sweep()
        await push_callback(engine, "bale", 20, ADMIN_CHAT, f"adap:{order['id']}")
        assert bot_apis["bale"].answered[-1]["text"] == texts.ADMIN_INSUFFICIENT_STOCK
        assert bot_apis["bale"].last_text_any(ADMIN_CHAT) == texts.ADMIN_INSUFFICIENT_STOCK
        assert shopapi.orders[order["id"]]["status"] == "receipt_uploaded"

    env(scenario)


def test_admin_callback_from_a_non_admin_chat_is_refused(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "adap:1")
        assert bot_apis["bale"].answered[-1]["text"] == texts.ADMIN_ONLY
        # not a single admin API call was made
        assert not any(path.startswith("/admin") for _, path, _ in shopapi.requests)

    env(scenario)


def test_admin_callback_from_the_admin_bale_chat_is_accepted(env, bot_apis, shopapi):
    shopapi.add_user("bale", OTHER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 1, ADMIN_CHAT, "adap:1")       # admin
        assert bot_apis["bale"].answered[-1]["text"] != texts.ADMIN_ONLY

    env(scenario)


def test_admin_commands_pending_and_order(env, settings, bot_apis, shopapi):
    settings.admin_chat_ids = ("bale:9001",)  # single, unambiguous admin
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.add_user("bale", OTHER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])

        await push_message(engine, "bale", 1, ADMIN_CHAT, text="/pending")
        assert texts.ADMIN_PENDING_SUMMARY.format(users=1, orders=0) in bot_apis["bale"].last_text_any(ADMIN_CHAT)

        await push_message(engine, "bale", 2, ADMIN_CHAT, text=f"/order {order['id']}")
        body = bot_apis["bale"].last_text_any(ADMIN_CHAT)
        assert f"سفارش {order['id']}" in body
        assert texts.ORDER_STATUS_FA["awaiting_payment"] in body

        await push_message(engine, "bale", 3, ADMIN_CHAT, text="/order 9999")
        assert texts.ADMIN_UNKNOWN_ORDER.format(order_id=9999) == bot_apis["bale"].last_text_any(ADMIN_CHAT)

    env(scenario)


def test_admin_user_commands_use_the_admin_key(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        await engine.admin_sweep()
        admin_calls = [(p, k) for _, p, k in shopapi.requests if p.startswith("/admin")]
        assert admin_calls, "expected admin calls"
        assert all(key == "test-admin-key" for _, key in admin_calls)
        customer_calls = [(p, k) for _, p, k in shopapi.requests if not p.startswith("/admin")]
        assert all(key == "test-bot-key" for _, key in customer_calls)

    env(scenario)
