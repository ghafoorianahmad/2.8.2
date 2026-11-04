"""v2.18.1 item 17 in the bot: the customers' calculator stays hidden while the switch is off; on,
it asks, and the card comes from the server. A card staff send arrives once."""
from __future__ import annotations

import base64
import json

import pytest

from app import texts

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_v2170 import _registered, _shop, _texts, details  # noqa: F401
from .test_v2180 import _send_data, _with_url


@pytest.fixture
def calc(shopapi):
    """shopapi's side: the switch, the quote, the delivery of a card."""
    state = {"enabled": False, "quotes": [], "png": "", "rejected": None, "results": [],
             "delivery": None}
    original = shopapi.handler

    def handler(request):
        import httpx

        path, method = request.url.path, request.method

        def reply(code, payload):
            return httpx.Response(code, json=payload, request=request)

        if path == "/installments/settings":
            return reply(200, {"enabled": state["enabled"]})
        if path == "/installments/quote" and method == "POST":
            body = json.loads(request.content)
            state["quotes"].append(body)
            if state["rejected"]:
                return reply(state["rejected"][0], {"detail": state["rejected"][1]})
            return reply(200, {"view": {}, "text": "متن کارت", "png_b64": state["png"]})
        if path.startswith("/admin/installments/deliveries/"):
            if path.endswith("/result"):
                state["results"].append(json.loads(request.content))
                return reply(200, {"ok": True})
            return reply(200, state["delivery"]) if state["delivery"] else reply(404, {"detail": "x"})
        return original(request)

    shopapi.handler = handler
    return state


def _menu_labels(bot_apis) -> str:
    return json.dumps(bot_apis["bale"].sent, ensure_ascii=False)


def test_off_there_is_no_button_and_no_command(env, bot_apis, shopapi, details, calc):  # noqa: F811
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "menu")
        assert texts.BTN_INSTALLMENT not in _menu_labels(bot_apis)
        await push_message(engine, "bale", 6, CUSTOMER_CHAT, text="/aghsat")
        assert not _texts(bot_apis)[-1].startswith(texts.INSTALLMENT_ASK_PRICE)
        assert calc["quotes"] == []

    env(scenario)


def test_an_old_button_says_it_is_off(env, bot_apis, shopapi, details, calc):  # noqa: F811
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "inst")
        assert _texts(bot_apis)[-1].startswith(texts.INSTALLMENT_OFF)

    env(scenario)


def test_on_it_asks_and_the_server_answers(env, bot_apis, shopapi, details, calc):  # noqa: F811
    calc["enabled"] = True
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "menu")
        assert texts.BTN_INSTALLMENT in _menu_labels(bot_apis)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "inst")
        assert _texts(bot_apis)[-1].startswith(texts.INSTALLMENT_ASK_PRICE)
        await push_message(engine, "bale", 7, CUSTOMER_CHAT, text="۲۰۰٬۰۰۰٬۰۰۰")
        assert _texts(bot_apis)[-1].startswith(texts.INSTALLMENT_ASK_DOWN)
        await push_message(engine, "bale", 8, CUSTOMER_CHAT, text="50%")
        assert _texts(bot_apis)[-1].startswith(texts.INSTALLMENT_ASK_MONTHS)
        await push_message(engine, "bale", 9, CUSTOMER_CHAT, text="5")
        assert calc["quotes"] == [{"phone_name": "", "price": 200_000_000, "down": 100_000_000,
                                   "months": 5}]
        assert _texts(bot_apis)[-1].startswith("متن کارت")

    env(scenario)


def test_a_bad_number_asks_again(env, bot_apis, shopapi, details, calc):  # noqa: F811
    calc["enabled"] = True
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "inst")
        await push_message(engine, "bale", 7, CUSTOMER_CHAT, text="یک میلیون")
        assert _texts(bot_apis)[-1].startswith(texts.INSTALLMENT_BAD_AMOUNT)
        assert calc["quotes"] == []

    env(scenario)


def test_the_servers_sentence_reaches_the_customer(env, bot_apis, shopapi, details, calc):  # noqa: F811
    calc["enabled"] = True
    calc["rejected"] = (422, "پیش‌پرداخت باید کمتر از قیمت گوشی باشد.")
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await _send_data(engine, 5, CUSTOMER_CHAT, json.dumps(
            {"v": 1, "type": "installment", "price": 100, "down": 200, "months": 5}))
        assert "کمتر از قیمت" in _texts(bot_apis)[-1]

    env(scenario)


def test_the_mini_app_page_is_off_too(env, bot_apis, shopapi, details, calc):  # noqa: F811
    calc["rejected"] = (403, "Installment calculator is off")
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await _send_data(engine, 5, CUSTOMER_CHAT, json.dumps(
            {"v": 1, "type": "installment", "price": 100, "down": 0, "months": 5}))
        assert _texts(bot_apis)[-1].startswith(texts.INSTALLMENT_OFF)

    env(scenario)


def test_garbage_numbers_from_the_page_are_refused(env, bot_apis, shopapi, details, calc):  # noqa: F811
    calc["enabled"] = True
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        await _send_data(engine, 5, CUSTOMER_CHAT, json.dumps(
            {"v": 1, "type": "installment", "price": "abc", "down": 0, "months": 5}))
        assert _texts(bot_apis)[-1].startswith(texts.WEB_APP_UNREADABLE)
        assert calc["quotes"] == []

    env(scenario)


def test_with_the_mini_app_published_the_form_is_offered(env, bot_apis, shopapi, details, calc):  # noqa: F811
    calc["enabled"] = True
    _shop(shopapi)
    _registered(shopapi, details)

    async def scenario(engine, adapters, api):
        engine.settings = _with_url(engine.settings)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "inst")
        assert "app/installment/" in _menu_labels(bot_apis)

    env(scenario)


def test_a_staff_card_is_delivered_once_and_reported(env, bot_apis, shopapi, calc):
    calc["delivery"] = {"status": "pending", "platform": "bale", "chat_id": CUSTOMER_CHAT,
                        "text": "متن کارت", "png_b64": ""}

    async def scenario(engine, adapters, api):
        assert await engine._deliver_installment_card(7) is True
        assert _texts(bot_apis)[-1].startswith("متن کارت")
        assert calc["results"] == [{"ok": True, "error": ""}]
        assert await engine._deliver_installment_card(7) is False
        assert len(calc["results"]) == 1

    env(scenario)


def test_a_staff_card_goes_as_a_photo(env, bot_apis, shopapi, calc):
    calc["delivery"] = {"status": "pending", "platform": "bale", "chat_id": CUSTOMER_CHAT,
                        "text": "متن", "png_b64": base64.b64encode(b"\x89PNGxx").decode()}

    async def scenario(engine, adapters, api):
        sent = []

        async def photo(chat_id, png, caption=""):
            sent.append((str(chat_id), png))
            return {}

        adapters["bale"].send_photo_bytes = photo
        assert await engine._deliver_installment_card(8) is True
        assert sent == [(str(CUSTOMER_CHAT), b"\x89PNGxx")]

    env(scenario)


def test_a_card_for_a_messenger_that_is_off_reports_why(env, bot_apis, shopapi, calc):
    calc["delivery"] = {"status": "pending", "platform": "telegram", "chat_id": "5",
                        "text": "متن", "png_b64": ""}

    async def scenario(engine, adapters, api):
        adapters.pop("telegram", None)
        engine.adapters.pop("telegram", None)
        assert await engine._deliver_installment_card(9) is False
        assert calc["results"][0]["ok"] is False and calc["results"][0]["error"]

    env(scenario)
