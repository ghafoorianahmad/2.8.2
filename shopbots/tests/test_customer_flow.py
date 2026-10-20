"""Customer flow: registration, approval gate, browsing, cart, checkout, receipt."""
from __future__ import annotations

import base64

from app import texts

from .conftest import CUSTOMER_CHAT, OTHER_CHAT, own_contact, push_callback, push_message


def test_registration_is_contact_only_and_registers(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == f"{texts.WELCOME}\n\n{texts.ASK_CONTACT}"
        keyboard = bot_apis["bale"].sent[-1]["reply_markup"]["keyboard"]
        assert keyboard[0][0]["request_contact"] is True

        await push_message(engine, "bale", 2, CUSTOMER_CHAT,
                           contact=own_contact(CUSTOMER_CHAT, "+989121234567"))
        texts_sent = bot_apis["bale"].texts(CUSTOMER_CHAT)
        assert texts.REGISTERED_PENDING in texts_sent
        assert bot_apis["bale"].sent[-2]["reply_markup"] == {"remove_keyboard": True}
        return shopapi.users[("bale", CUSTOMER_CHAT)]

    user = env(scenario)
    assert user["phone"] == "09121234567"
    assert user["name"] == "Ali Rezaei"          # from the contact, not asked
    assert user["status"] == "pending"


def test_typed_number_is_never_accepted(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        # Persian or Latin digits: typed numbers are refused, the button is offered again
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="۰۹۱۲۱۲۳۴۵۶۷")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CONTACT_BUTTON_ONLY
        assert bot_apis["bale"].sent[-1]["reply_markup"]["keyboard"][0][0]["request_contact"]
        assert ("bale", CUSTOMER_CHAT) not in shopapi.users

    env(scenario)


def test_someone_elses_contact_is_refused(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT,
                           contact=own_contact(OTHER_CHAT))           # forwarded card
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CONTACT_NOT_OWN
        await push_message(engine, "bale", 3, CUSTOMER_CHAT,
                           contact={"phone_number": "09121234567"})  # no user_id at all
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CONTACT_NOT_OWN
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, from_id=OTHER_CHAT,
                           contact=own_contact(CUSTOMER_CHAT))        # sender differs
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CONTACT_NOT_OWN
        assert ("bale", CUSTOMER_CHAT) not in shopapi.users

    env(scenario)


def test_non_iranian_mobile_is_refused(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT,
                           contact=own_contact(CUSTOMER_CHAT, "+14155550100"))
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.CONTACT_NOT_MOBILE
        assert ("bale", CUSTOMER_CHAT) not in shopapi.users

    env(scenario)


def test_known_customer_is_approved_at_once(env, bot_apis, shopapi):
    shopapi.known_phones["09121234567"] = 7001

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, contact=own_contact(CUSTOMER_CHAT))
        assert texts.REGISTERED_APPROVED in bot_apis["bale"].texts(CUSTOMER_CHAT)
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.MAIN_MENU
        callbacks = [cb for row in bot_apis["bale"].buttons_for(CUSTOMER_CHAT) for _, cb in row]
        assert "stmt:1" in callbacks

    env(scenario)
    assert shopapi.users[("bale", CUSTOMER_CHAT)]["person_code"] == 7001


def test_contact_name_falls_back_to_profile(env, bot_apis, shopapi):
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_message(engine, "bale", 2, CUSTOMER_CHAT,
                           contact={"phone_number": "09121234567", "user_id": int(CUSTOMER_CHAT)})

    env(scenario)
    assert shopapi.users[("bale", CUSTOMER_CHAT)]["name"] == "Bale User"


def test_pending_user_can_browse_but_not_see_statement(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="سلام")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert body.startswith(texts.STILL_PENDING) and body.endswith(texts.MAIN_MENU)
        callbacks = [cb for row in bot_apis["bale"].buttons_for(CUSTOMER_CHAT) for _, cb in row]
        assert "groups" in callbacks and "stmt:1" not in callbacks
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "groups")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.GROUPS_TITLE
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "stmt:1")
        assert bot_apis["bale"].answered[-1]["text"] == texts.STATEMENT_ONLY_APPROVED

    env(scenario)


def test_pending_user_order_gets_note(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="pending")

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")
        assert texts.PENDING_ORDER_NOTE in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_rejected_user_is_told(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="rejected")

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT).endswith(texts.REJECTED_USER)

    env(scenario)


def test_approved_user_gets_main_menu(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == f"{texts.WELCOME}\n\n{texts.MAIN_MENU}"
        rows = bot_apis["bale"].buttons_for(CUSTOMER_CHAT)
        assert any(cb == "groups" for row in rows for _, cb in row)
        assert any(cb == "cart" for row in rows for _, cb in row)
        assert any(cb == "orders" for row in rows for _, cb in row)

    env(scenario)


def test_groups_then_products_then_pagination(env, settings, bot_apis, shopapi):
    settings.product_page_size = 1  # force several pages
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "groups")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.GROUPS_TITLE

        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "grp:1")
        first = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "کالای الف" in first
        assert "1,000" in first          # price comes from the API
        assert texts.PRODUCTS_TITLE.format(page=1, pages=2) in first
        callbacks = [cb for row in bot_apis["bale"].buttons_for(CUSTOMER_CHAT) for _, cb in row]
        assert "pg:1:2" in callbacks

        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "pg:1:2")
        assert texts.PRODUCTS_TITLE.format(page=2, pages=2) in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_product_detail_quantity_selection_and_add_to_cart(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        assert "کالای الف" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "qty:101:3")
        assert "3" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "add:101:3")
        cart = engine.store.cart_list("bale", CUSTOMER_CHAT)
        assert len(cart) == 1 and cart[0]["qty"] == 3
        assert texts.CART_TITLE in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_cart_change_and_remove(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "cinc:101")
        assert engine.store.cart_list("bale", CUSTOMER_CHAT)[0]["qty"] == 2
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "cdec:101")
        assert engine.store.cart_list("bale", CUSTOMER_CHAT)[0]["qty"] == 1
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "cdel:101")
        assert engine.store.cart_list("bale", CUSTOMER_CHAT) == []

    env(scenario)


def test_search_by_text(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "search")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.ASK_SEARCH
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="کالای د")
        listing = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "کالای د" in listing

    env(scenario)


def test_checkout_and_receipt_upload(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:2")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")

        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert "شمارهٔ سفارش" in body
        assert "2,000" in body
        assert "6037-0000-1111-2222" in body      # v2.8.2: the details staff sent
        assert body.endswith(texts.PAYMENT_SEND_RECEIPT)
        assert "6037-0000-1111-2222" in body               # the card configured in shopapi
        assert engine.store.cart_list("bale", CUSTOMER_CHAT) == []

        order = next(iter(shopapi.orders.values()))
        assert order["status"] == "awaiting_payment"
        assert order["_chat_id"] == CUSTOMER_CHAT

        # the customer sends a photo: the largest size is downloaded and sent
        # to shopapi with its ref (the image is kept for ShopAdmin)
        await push_message(
            engine, "bale", 6, CUSTOMER_CHAT,
            photo=[{"file_id": "SMALL"}, {"file_id": "LARGE"}],
        )
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_RECEIVED
        assert order["status"] == "receipt_uploaded"
        assert order["receipt_ref"] == "LARGE"
        assert base64.b64decode(order["_receipt_b64"]) == bot_apis["bale"].file_bytes
        assert engine.store.get_receipt(order["id"])["file_ref"] == "LARGE"

    env(scenario)


def test_text_while_waiting_for_receipt_is_refused(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, text="سلام")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.RECEIPT_EXPECTED_PHOTO

    env(scenario)


def test_my_orders_lists_persian_status(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "orders")
        body = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert texts.ORDERS_TITLE in body
        assert texts.ORDER_STATUS_FA["awaiting_payment"] in body

    env(scenario)


def test_my_orders_empty(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "orders")
        assert bot_apis["bale"].last_text_any(CUSTOMER_CHAT) == texts.ORDERS_EMPTY

    env(scenario)


def test_out_of_stock_product_cannot_be_added(env, bot_apis, shopapi):
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        # v2.6.0: lists show only in-stock items; 103 (0 available) is not listed
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:2")
        listing = bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        assert texts.OUT_OF_STOCK_LABEL not in listing and texts.IN_STOCK in listing
        callbacks = [cb for row in bot_apis["bale"].buttons_for(CUSTOMER_CHAT) for _, cb in row]
        assert "prod:103" not in callbacks and "prod:104" in callbacks
        # opened by its code it is out of stock: no add, but «درخواست این کالا»
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="103")
        assert texts.OUT_OF_STOCK in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        callbacks = [cb for row in bot_apis["bale"].buttons_for(CUSTOMER_CHAT) for _, cb in row]
        assert not any(cb.startswith(("add:", "qty:")) for cb in callbacks)
        assert "ireqk:103" in callbacks
        # a forged "add" callback is refused too
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:103:1")
        assert api is not None
        assert not engine.store.cart_list("bale", CUSTOMER_CHAT)

    env(scenario)


def test_typed_label_works_without_inline_keyboards(env, bot_apis, shopapi):
    """Text-only fallback: typing a button label triggers the same action."""
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        # no inline keyboard and no reply keyboard -> options are listed as plain text
        adapters["bale"].supports_inline_keyboard = False
        adapters["bale"].supports_reply_keyboard = False
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        assert texts.BTN_GROUPS in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text=texts.BTN_CART)
        assert texts.CART_EMPTY in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_other_customer_data_is_not_reachable(env, bot_apis, shopapi):
    """A chat only ever sees its own cart, orders and profile."""
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)
    shopapi.add_user("bale", OTHER_CHAT, status="approved", person_code=7002)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, OTHER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, OTHER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, OTHER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, OTHER_CHAT, "add:101:1")
        assert engine.store.cart_list("bale", CUSTOMER_CHAT) == []
        assert len(engine.store.cart_list("bale", OTHER_CHAT)) == 1

    env(scenario)
