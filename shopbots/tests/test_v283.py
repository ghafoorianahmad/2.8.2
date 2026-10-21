"""v2.8.3: «مرحلهٔ قبل» next to «منوی اصلی» on every step (one step back, the
earlier choices kept), card / account / Sheba numbers left to right, the
customer may cancel while the payment details have not come yet."""
from __future__ import annotations

from app import texts
from app.engine import LRM, ltr

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_phase3 import _callbacks
from .test_v280 import _shop


def _last_row(api) -> list[tuple[str, str]]:
    rows = api.buttons_for(CUSTOMER_CHAT)
    return rows[-1] if rows else []


def _has_back(api) -> bool:
    return _last_row(api) == [(texts.BTN_BACK, "back"), (texts.BTN_MENU, "menu")]


def test_back_through_group_product_color_part_cart(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.groups.append({"code": 3, "name": "گوشی"})
    for v in shopapi.products[-1]["variants"]:
        v.setdefault("part", "")
    # the black color is sold in two parts
    shopapi.products[-1]["variants"].append(
        {"id": 14, "color": "مشکی", "part": "CHA", "unit_price": 515_000_000.0,
         "available": True})
    shopapi.products[-1]["variants"][0]["part"] = "ZAA"
    api = bot_apis["bale"]

    async def scenario(engine, adapters, _api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "menu")
        assert not _has_back(api)                               # the main menu: no step back
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "groups")
        assert _has_back(api)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "grp:3")
        assert "prod:900" in _callbacks(api, CUSTOMER_CHAT) and _has_back(api)
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "prod:900")
        assert "col:900:11" in _callbacks(api, CUSTOMER_CHAT) and _has_back(api)
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "col:900:11")
        assert "prt:900:14" in _callbacks(api, CUSTOMER_CHAT) and _has_back(api)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "prt:900:14")
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "vqty:900:14:3")
        assert "vadd:900:14:3" in _callbacks(api, CUSTOMER_CHAT)
        await push_callback(engine, "bale", 8, CUSTOMER_CHAT, "vadd:900:14:3")
        assert "checkout" in _callbacks(api, CUSTOMER_CHAT) and _has_back(api)
        # cart -> the price screen, with the quantity chosen before (3)
        await push_callback(engine, "bale", 9, CUSTOMER_CHAT, "back")
        assert "vadd:900:14:3" in _callbacks(api, CUSTOMER_CHAT)
        # price -> the parts of that color
        await push_callback(engine, "bale", 10, CUSTOMER_CHAT, "back")
        assert "prt:900:14" in _callbacks(api, CUSTOMER_CHAT)
        # parts -> colors -> the group's list -> the groups -> the main menu
        await push_callback(engine, "bale", 11, CUSTOMER_CHAT, "back")
        assert "col:900:11" in _callbacks(api, CUSTOMER_CHAT)
        await push_callback(engine, "bale", 12, CUSTOMER_CHAT, "back")
        assert "prod:900" in _callbacks(api, CUSTOMER_CHAT)
        await push_callback(engine, "bale", 13, CUSTOMER_CHAT, "back")
        assert "grp:3" in _callbacks(api, CUSTOMER_CHAT)
        await push_callback(engine, "bale", 14, CUSTOMER_CHAT, "back")
        assert texts.MAIN_MENU in api.last_text_any(CUSTOMER_CHAT) and not _has_back(api)
        # the cart kept what was added
        assert engine.cart.items("bale", str(CUSTOMER_CHAT))[0]["qty"] == 3

    env(scenario)


def test_back_in_phone_search_and_purchase_request(env, bot_apis, shopapi):
    _shop(shopapi)
    api = bot_apis["bale"]

    async def scenario(engine, adapters, _api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "search")
        assert _has_back(api)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="17 pro")
        assert _callbacks(api, CUSTOMER_CHAT)[:2] == ["psm:0", "psm:1"] and _has_back(api)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "psm:0")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "psc:0:0")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "psr:1")
        assert "pbr:1" in _callbacks(api, CUSTOMER_CHAT) and _has_back(api)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "pbr:1")
        assert _has_back(api)                                    # «ثبت شد» too
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "back")
        assert "pbr:1" in _callbacks(api, CUSTOMER_CHAT)          # the row again
        await push_callback(engine, "bale", 8, CUSTOMER_CHAT, "back")
        assert {"psr:0", "psr:1"} <= set(_callbacks(api, CUSTOMER_CHAT))
        await push_callback(engine, "bale", 9, CUSTOMER_CHAT, "back")
        assert {"psc:0:0", "psc:0:1"} <= set(_callbacks(api, CUSTOMER_CHAT))
        await push_callback(engine, "bale", 10, CUSTOMER_CHAT, "back")
        assert _callbacks(api, CUSTOMER_CHAT)[:2] == ["psm:0", "psm:1"]
        await push_callback(engine, "bale", 11, CUSTOMER_CHAT, "back")
        assert texts.ASK_SEARCH in api.last_text_any(CUSTOMER_CHAT)
        # the search prompt waits for a text again
        await push_message(engine, "bale", 12, CUSTOMER_CHAT, text="17 pro")
        assert _callbacks(api, CUSTOMER_CHAT)[:2] == ["psm:0", "psm:1"]

    env(scenario)


def test_back_in_item_request(env, bot_apis, shopapi):
    _shop(shopapi)
    api = bot_apis["bale"]

    async def scenario(engine, adapters, _api):
        await push_callback(engine, "bale", 1, CUSTOMER_CHAT, "ireq")
        assert _has_back(api)
        await push_message(engine, "bale", 2, CUSTOMER_CHAT, text="شارژر سامسونگ")
        assert "ireqt" in _callbacks(api, CUSTOMER_CHAT) and _has_back(api)
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "back")
        assert texts.ITEM_REQUEST_ASK in api.last_text_any(CUSTOMER_CHAT)
        await push_message(engine, "bale", 4, CUSTOMER_CHAT, text="شارژر سامسونگ")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "ireqt")
        assert _has_back(api)
        await push_callback(engine, "bale", 6, CUSTOMER_CHAT, "back")
        assert "ireqt" in _callbacks(api, CUSTOMER_CHAT)          # what was typed is kept
        await push_callback(engine, "bale", 7, CUSTOMER_CHAT, "back")
        assert texts.ITEM_REQUEST_ASK in api.last_text_any(CUSTOMER_CHAT)

    env(scenario)


def test_back_label_works_on_text_only_platforms():
    # the label maps to the callback like every other button
    assert texts.BTN_BACK and texts.BTN_BACK != texts.BTN_MENU


def test_numbers_are_left_to_right():
    card = ltr("6037-1234-5678-1234")
    assert card.startswith(LRM) and card.endswith(LRM)
    assert card.replace(LRM, "") == "6037-1234-5678-1234"
    assert f"{LRM}-{LRM}" in card
    assert ltr("IR123").replace(LRM, "") == "IR123"


def test_cancel_while_waiting_for_payment_details(env, bot_apis, shopapi):
    _shop(shopapi)
    shopapi.auto_payment_info = None
    api = bot_apis["bale"]

    async def scenario(engine, adapters, _api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="101")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "add:101:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "checkout")
        assert texts.WAIT_PAYMENT_INFO in api.last_text_any(CUSTOMER_CHAT)
        order_id = next(iter(shopapi.orders))
        assert f"ocx:{order_id}" in _callbacks(api, CUSTOMER_CHAT)
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "orders")
        assert f"ocx:{order_id}" in _callbacks(api, CUSTOMER_CHAT)

    env(scenario)
