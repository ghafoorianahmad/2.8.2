"""v2.18.0: required details, the form as a web_app page, its answer checked on the server."""
from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app import texts
from app.config import _miniapp_url
from app.platforms.base import web_app_keyboard
from app.platforms.telegram import to_buttons

from .conftest import CUSTOMER_CHAT, push_message
from .test_v2170 import _contact, _texts, details  # noqa: F401 - the fixture

URL = "https://shop.test/app/"


def _form(payload: dict) -> str:
    return json.dumps({"v": 1, "type": "customer", **payload}, ensure_ascii=False)


async def _send_data(engine, update_id, chat, data: str):
    await engine.handle_update("bale", {"update_id": update_id, "message": {
        "message_id": update_id, "chat": {"id": int(chat), "type": "private"},
        "from": {"id": int(chat)}, "web_app_data": {"data": data}}})


FULL = {"first_name": "علی", "last_name": "رضایی", "national_code": "0084575948",
        "address": "مشهد، خیابان نمونه، پلاک ۱"}


def test_miniapp_url_must_be_https():
    assert _miniapp_url("http://shop.test/app/") == ""
    assert _miniapp_url("") == ""
    assert _miniapp_url("https://shop.test/app") == URL


def test_without_a_published_page_there_is_no_button(env, bot_apis, shopapi, details):  # noqa: F811
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        assert "web_app" not in json.dumps(bot_apis["bale"].sent)
        assert _texts(bot_apis)[-1].startswith(texts.ASK_FIRST_NAME)

    env(scenario)


def test_the_form_opens_prefilled(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = ["national_code", "address"]
    details["prefill"] = {"first_name": "علی", "last_name": "رضایی"}

    async def scenario(engine, adapters, api):
        engine.settings = _with_url(engine.settings)
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        sent = [m for m in bot_apis["bale"].sent if "web_app" in json.dumps(m)]
        assert sent, bot_apis["bale"].sent
        markup = sent[-1]["reply_markup"]
        markup = json.loads(markup) if isinstance(markup, str) else markup
        button = markup["keyboard"][0][0]
        assert button["text"] == texts.BTN_DETAILS_FORM
        link = urlparse(button["web_app"]["url"])
        assert link.path == "/app/form/"
        assert parse_qs(link.query) == {"fn": ["علی"], "ln": ["رضایی"], "need": ["nc,addr"]}

    env(scenario)


def _with_url(settings):
    from dataclasses import replace

    return replace(settings, miniapp_url=URL)


def test_a_filled_form_is_saved(env, bot_apis, shopapi, details):  # noqa: F811
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await _send_data(engine, 3, CUSTOMER_CHAT, _form(FULL))
        assert details["missing"] == []
        assert dict(details["saved"]) == FULL
        assert texts.DETAILS_DONE in _texts(bot_apis)

    env(scenario)


def test_a_refused_form_says_why_and_offers_it_again(env, bot_apis, shopapi, details):  # noqa: F811
    details["refuse"] = {"national_code"}
    details["refuse_text"] = "کد ملی ۱۰ رقمی معتبر نیست (رقم کنترل نادرست است)."

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await _send_data(engine, 3, CUSTOMER_CHAT, _form(FULL))
        assert _texts(bot_apis)[-1] == details["refuse_text"]
        assert texts.DETAILS_DONE not in _texts(bot_apis)

    env(scenario)


def test_typed_answer_gets_the_servers_sentence(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = ["first_name"]
    details["refuse"] = {"first_name"}
    details["refuse_text"] = "نام باید فقط شامل حروف فارسی باشد."

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="Ali")
        said = _texts(bot_apis)[-1]
        assert said.startswith(details["refuse_text"]) and texts.ASK_FIRST_NAME in said

    env(scenario)


@pytest.mark.parametrize("raw", ["not json", "[]", '{"v": 2, "type": "customer"}',
                                 '{"v": 1, "type": "nonsense"}', "x" * 5000])
def test_garbage_from_a_page_is_refused(env, bot_apis, shopapi, details, raw):  # noqa: F811
    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await _contact(engine, 2, CUSTOMER_CHAT)
        await _send_data(engine, 3, CUSTOMER_CHAT, raw)
        assert _texts(bot_apis)[-1] == texts.WEB_APP_UNREADABLE
        assert details["saved"] == []

    env(scenario)


def test_telegram_buttons_of_a_web_app():
    from telethon import TelegramClient
    from telethon.tl.types import ButtonTypeSimpleWebView, ReplyKeyboardMarkup

    rows = to_buttons(web_app_keyboard([[("فرم", URL + "form/")]]))
    # Telethon itself must accept it as a normal (not inline) keyboard
    markup = TelegramClient.build_reply_markup(rows)
    assert isinstance(markup, ReplyKeyboardMarkup) and markup.resize is True
    button = markup.rows[0].buttons[0]
    assert button.text == "فرم" and isinstance(button.type, ButtonTypeSimpleWebView)
    assert button.type.url == URL + "form/"


def test_telegram_passes_on_what_the_page_sent():
    from app.platforms.telegram import TelethonBotAdapter

    pushed = []
    adapter = SimpleNamespace(_push=pushed.append)
    action = type("MessageActionWebViewDataSentMe", (), {"data": '{"v":1}', "text": "فرم"})()
    update = SimpleNamespace(message=SimpleNamespace(
        id=9, action=action, peer_id=SimpleNamespace(user_id=55)))

    import asyncio

    asyncio.run(TelethonBotAdapter._on_raw(adapter, update))
    message = pushed[0]["message"]
    assert message["chat"] == {"id": 55, "type": "private"}
    assert message["web_app_data"] == {"data": '{"v":1}'}
    pushed.clear()
    other = SimpleNamespace(message=SimpleNamespace(id=9, action=None))
    asyncio.run(TelethonBotAdapter._on_raw(adapter, other))
    assert pushed == []


# ---- the shop page -----------------------------------------------------------------------------
def _cart(items) -> str:
    return json.dumps({"v": 1, "type": "cart", "items": items}, ensure_ascii=False)


def _serve(shopapi, answers: dict, seen: list | None = None):
    """{path part: (status, json)} before the fake shopapi's own answers."""
    original = shopapi.handler

    def handler(request):
        import httpx

        for part, (status, payload) in answers.items():
            if part in request.url.path:
                if seen is not None and request.content:
                    seen.append(json.loads(request.content))
                return httpx.Response(status, json=payload, request=request)
        return original(request)

    shopapi.handler = handler


RESOLVE = "/resolve"


async def _registered(engine, bot_apis):
    await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
    await _contact(engine, 2, CUSTOMER_CHAT)


def test_a_cart_from_the_page_goes_into_the_bots_cart(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = []
    _serve(shopapi, {RESOLVE: (200, {"status": "found", "model": {"name": "کالای الف"},
                                     "items": [{"kala_code": 101, "label": "الف"}]})})

    async def scenario(engine, adapters, api):
        await _registered(engine, bot_apis)
        await _send_data(engine, 3, CUSTOMER_CHAT, _cart([{"id": "x", "color": "", "qty": 2,
                                                           "price": 1}]))
        items = engine.cart.items("bale", str(CUSTOMER_CHAT))
        assert [(i["kala_code"], i["qty"]) for i in items] == [(101, 2)]
        # the price is the shop's, whatever a page may send
        assert items[0]["unit_price"] == 1000.0

    env(scenario)


def test_an_unknown_item_reaches_staff_not_the_cart(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = []
    asked: list = []
    _serve(shopapi, {RESOLVE: (200, {"status": "unknown"}),
                     "/item-requests": (201, {"id": 1})}, asked)

    async def scenario(engine, adapters, api):
        await _registered(engine, bot_apis)
        await _send_data(engine, 3, CUSTOMER_CHAT, _cart([{"id": "galaxy-a57", "color": "آبی",
                                                           "qty": 1}]))
        assert engine.cart.items("bale", str(CUSTOMER_CHAT)) == []
        assert "galaxy a57 آبی" in _texts(bot_apis)[-1]
        assert [a["text"] for a in asked if "text" in a] == ["galaxy a57 آبی"]

    env(scenario)


def test_a_price_question_gets_its_answer_and_a_way_back(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = []
    _serve(shopapi, {RESOLVE: (200, {"status": "unknown"}), "/item-requests": (201, {"id": 1}),
                     "/phones/search": (200, {"items": []})})

    async def scenario(engine, adapters, api):
        await _registered(engine, bot_apis)
        engine.settings = _with_url(engine.settings)
        await _send_data(engine, 3, CUSTOMER_CHAT, json.dumps(
            {"v": 1, "type": "price", "id": "galaxy-a57", "color": "آبی"}, ensure_ascii=False))
        said = _texts(bot_apis)
        assert any("galaxy a57 آبی" in t for t in said)
        assert said[-1] == texts.WEB_APP_BACK
        markup = bot_apis["bale"].sent[-1]["reply_markup"]
        markup = json.loads(markup) if isinstance(markup, str) else markup
        assert markup["keyboard"][0][0] == {"text": texts.BTN_SHOP, "web_app": {"url": URL}}

    env(scenario)


def test_start_offers_the_shop_only_once_published(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = []

    async def scenario(engine, adapters, api):
        await _registered(engine, bot_apis)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="/start")
        assert texts.SHOP_BUTTON_NOTE not in _texts(bot_apis)
        engine.settings = _with_url(engine.settings)
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, text="/start")
        assert _texts(bot_apis)[-1] == texts.SHOP_BUTTON_NOTE

    env(scenario)


# ---- automatic answers ---------------------------------------------------------------------------
def test_a_known_question_is_answered_and_staff_told(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = []
    asked: list = []
    _serve(shopapi, {"/faq/answer": (200, {"answer": "ساعت کاری ما: ۹ تا ۲۱", "id": "hours",
                                           "needs_staff": True, "score": 100}),
                     "/phones/search": (200, {"items": []}),
                     RESOLVE: (200, {"status": "unknown"}),
                     "/item-requests": (201, {"id": 1})}, asked)

    async def scenario(engine, adapters, api):
        await _registered(engine, bot_apis)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="ساعت کاری چنده")
        assert _texts(bot_apis)[-1] == "ساعت کاری ما: ۹ تا ۲۱"
        assert [a["text"] for a in asked if "text" in a] == ["ساعت کاری چنده"]

    env(scenario)


def test_an_unknown_question_gets_the_menu(env, bot_apis, shopapi, details):  # noqa: F811
    details["missing"] = []
    _serve(shopapi, {"/faq/answer": (200, {}), "/phones/search": (200, {"items": []}),
                     RESOLVE: (200, {"status": "unknown"})})

    async def scenario(engine, adapters, api):
        await _registered(engine, bot_apis)
        await push_message(engine, "bale", 3, CUSTOMER_CHAT, text="یک متن بی‌ربط")
        assert texts.MAIN_MENU in _texts(bot_apis)[-1]

    env(scenario)
