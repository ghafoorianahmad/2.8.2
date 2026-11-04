"""v2.18.1 item 16 in the bot: the national code and the address are never in a link or a
message; only what is missing is asked; nothing is ordered before it is there."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from app import texts

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_v2170 import _contact, _registered, _shop, _texts, details  # noqa: F401
from .test_v2180 import _form, _send_data, _with_url  # noqa: F401

CODE = "0084575948"
ADDRESS = "مشهد، خیابان نمونه، پلاک ۱"


def _sent(bot_apis) -> str:
    return json.dumps(bot_apis["bale"].sent, ensure_ascii=False)


def _form_links(bot_apis) -> list:
    found = []
    for message in bot_apis["bale"].sent:
        markup = message.get("reply_markup")
        markup = json.loads(markup) if isinstance(markup, str) else markup
        for row in (markup or {}).get("keyboard") or ():
            for button in row:
                if isinstance(button, dict) and button.get("web_app"):
                    found.append(button["web_app"]["url"])
    return found


def test_only_the_missing_one_is_asked(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = ["address"]

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        assert _texts(bot_apis)[-1].startswith(texts.ASK_ADDRESS)
        assert texts.ASK_NATIONAL_CODE not in _sent(bot_apis)

    env(scenario)


def test_the_link_says_what_to_ask_and_never_a_value(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = ["address"]
    # even a server that sent them could not get them into a link
    details["prefill"] = {"first_name": "علی", "last_name": "رضایی", "national_code": CODE,
                          "address": ADDRESS}

    async def scenario(engine, adapters, api):
        engine.settings = _with_url(engine.settings)
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        links = _form_links(bot_apis)
        assert links
        query = parse_qs(urlparse(links[-1]).query)
        assert query == {"fn": ["علی"], "ln": ["رضایی"], "need": ["addr"]}
        assert CODE not in _sent(bot_apis) and "خیابان نمونه" not in _sent(bot_apis)

    env(scenario)


def test_a_refused_form_never_puts_its_answers_in_a_link(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = ["national_code", "address"]
    details["refuse"] = ["national_code"]

    async def scenario(engine, adapters, api):
        engine.settings = _with_url(engine.settings)
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await _send_data(engine, 3, CUSTOMER_CHAT, _form({
            "first_name": "علی", "last_name": "رضایی", "national_code": CODE, "address": ADDRESS}))
        assert _form_links(bot_apis)
        for link in _form_links(bot_apis):
            assert CODE not in link and "نمونه" not in link
            assert not {"nc", "addr"} & set(parse_qs(urlparse(link).query))

    env(scenario)


def test_a_page_that_left_one_out_is_asked_for_it(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = ["national_code", "address"]

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await _send_data(engine, 3, CUSTOMER_CHAT, _form({"national_code": CODE}))
        assert _texts(bot_apis)[-1].startswith(texts.ASK_ADDRESS)

    env(scenario)


def test_text_and_buttons_wait_for_the_missing_details(env, bot_apis, shopapi, details):  # noqa: F811
    _shop(shopapi)
    _registered(shopapi, details)
    details["missing"] = ["national_code"]

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "menu")
        assert _texts(bot_apis)[-1].startswith(texts.ASK_NATIONAL_CODE)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "orders")
        assert _texts(bot_apis)[-1].startswith(texts.ASK_NATIONAL_CODE)
        await push_message(engine, "bale", 7, CUSTOMER_CHAT, text=CODE)
        assert ("national_code", CODE) in details["saved"]
        # complete: the next tap goes where it was going
        await push_callback(engine, "bale", 8, CUSTOMER_CHAT, "menu")
        assert not _texts(bot_apis)[-1].startswith(texts.ASK_NATIONAL_CODE)

    env(scenario)


def test_the_mini_app_waits_too(env, bot_apis, shopapi, details):  # noqa: F811
    _shop(shopapi)
    _registered(shopapi, details)
    details["missing"] = ["national_code"]

    async def scenario(engine, adapters, api):
        await _send_data(engine, 5, CUSTOMER_CHAT, json.dumps(
            {"v": 1, "type": "cart", "items": [{"id": "x", "qty": 1}]}))
        assert _texts(bot_apis)[-1].startswith(texts.ASK_NATIONAL_CODE)
        assert engine.cart.items("bale", CUSTOMER_CHAT) == []

    env(scenario)


def test_placing_an_order_never_says_the_address(env, bot_apis, shopapi, details):  # noqa: F811
    assert "{address}" not in texts.CHECKOUT_CONFIRM_ADDRESS
    assert "{address}" not in texts.ORDER_ADDRESS_SAVED
    assert "{address}" not in texts.ORDER_SHIP_TO
    _shop(shopapi)
    _registered(shopapi, details)
    details["address"] = ADDRESS

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "cart")
        assert "خیابان نمونه" not in _sent(bot_apis)

    env(scenario)


def test_complete_details_are_asked_of_shopapi_once(env, bot_apis, shopapi, details):  # noqa: F811
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        calls = []
        real = api.customer_details

        async def counted(platform, chat_id):
            calls.append(chat_id)
            return await real(platform, chat_id)

        api.customer_details = counted
        for update in (5, 6, 7):
            await push_callback(engine, "bale", update, CUSTOMER_CHAT, "menu")
        assert len(calls) == 1

    env(scenario)
