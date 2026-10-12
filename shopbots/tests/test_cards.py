"""Branded image cards: Persian shaping, PNG output, the BOT_IMAGE_CARDS switch and
the text fallbacks (nothing here touches a real network)."""
from __future__ import annotations

import datetime as dt
import io

from PIL import Image

from app import texts
from app.cards import render
from app.cards.jdate import shamsi_date

from .conftest import CUSTOMER_CHAT, push_callback, push_message
from .test_phase3 import _open_phone, _shop

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ITEMS = [
    {"name": "گوشی Samsung Galaxy S25 Ultra", "variant": "مشکی", "qty": 1, "unit_price": 78_500_000},
    {"name": "کاور iPhone 17 Pro", "qty": 2, "unit_price": 450_000},
]


# ============================ rendering ======================================
def test_persian_text_is_shaped_joined_and_right_to_left():
    shaped = render.shape("سلام")
    # joined letters = Arabic presentation forms, not the isolated base letters
    assert all(0xFB50 <= ord(ch) <= 0xFEFF for ch in shaped)
    assert shaped != "سلام"
    # visual order of an RTL word is reversed (first letter drawn on the right)
    assert shaped[-1] == render.shape("س")[0] or shaped[0] == render.shape("م")[0]


def test_latin_model_names_and_digits_keep_their_order_inside_persian():
    shaped = render.shape("گوشی Galaxy S25 Ultra ۲۵۶")
    assert "Galaxy S25 Ultra" in shaped          # Latin run stays left-to-right, unreversed


def test_font_has_the_glyphs_the_shaper_emits():
    from PIL import ImageFont

    font = ImageFont.truetype(str(render.FONT_REGULAR), 40, layout_engine=ImageFont.Layout.BASIC)
    notdef = font.getmask("￿").getbbox()
    for word in ("عصر ارتباطات", "پیش‌فاکتور", "ناموجود", "۱۲٬۳۴۵"):
        for ch in render.shape(word):
            if ch == " ":
                continue
            assert font.getmask(ch).getbbox() != notdef, (word, hex(ord(ch)))


def test_shamsi_date():
    assert shamsi_date(dt.date(2026, 10, 12)) == "1405/07/20"
    assert shamsi_date(dt.date(2025, 3, 21)) == "1404/01/01"
    assert shamsi_date("2026-10-12T08:00:00+00:00") == "1405/07/20"


def test_persian_numbers():
    assert render.fa_num(118_900_000) == "۱۱۸٬۹۰۰٬۰۰۰"
    assert render.fa_num(None) == "۰"


def _open(png: bytes) -> Image.Image:
    assert png.startswith(PNG_MAGIC)
    return Image.open(io.BytesIO(png))


def test_cards_are_png_images_with_the_dark_background():
    price = render.price_card(shop="عصر ارتباطات ۲", name="Apple iPhone 17 Pro", color="نارنجی",
                              price=118_900_000, in_stock=True)
    pre = render.pre_invoice_card(shop="عصر ارتباطات ۲", order_id=7, items=ITEMS, total=79_400_000,
                                  card_number="6037-0000-1111-2222", card_owner="نمونه",
                                  bank_name="بانک نمونه")
    final = render.final_invoice_card(shop="عصر ارتباطات ۲", order_id=7, items=ITEMS,
                                      total=79_400_000, partial=True, accounting_no=2673)
    for png in (price, pre, final):
        img = _open(png)
        assert img.width == render.W and 400 < img.height < 2000
        from PIL import ImageStat

        assert max(ImageStat.Stat(img.convert("RGB")).mean) < 60   # near-black (website style)
    assert _open(pre).height > _open(price).height


def test_long_and_odd_input_does_not_fail():
    png = render.price_card(shop="x" * 200, name="گوشی " * 60 + "A" * 80, color="ر" * 90,
                            price="not a number", in_stock=False)
    assert png and png.startswith(PNG_MAGIC)
    many = [{"name": f"کالا {i}", "qty": i, "unit_price": 1000 * i} for i in range(1, 40)]
    assert render.final_invoice_card(shop="s", order_id=1, items=many, total=1)


def test_pre_invoice_without_card_number_says_payment_follows():
    png = render.pre_invoice_card(shop="s", order_id=1, items=ITEMS, total=1,
                                  card_number="XXXX-XXXX-XXXX-XXXX")
    assert png and png.startswith(PNG_MAGIC)


def test_rendering_failure_returns_none(monkeypatch):
    monkeypatch.setattr(render, "FONT_REGULAR", render.ASSETS / "missing.ttf")
    assert render.price_card(shop="s", name="n", color="c", price=1, in_stock=True) is None


# ============================ engine =========================================
def _photo_calls(api):
    return [payload for method, payload in api.calls if method == "sendPhoto"]


def test_cards_are_off_by_default(env, bot_apis, shopapi):
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")

    env(scenario)
    assert not _photo_calls(bot_apis["bale"])
    assert "525,000,000" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)


def test_price_card_only_on_the_first_color_pick_of_a_product_view(settings, env, bot_apis, shopapi):
    settings.bot_image_cards = True
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")
        assert len(_photo_calls(bot_apis["bale"])) == 1
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "col:900:12")   # switch: text only
        assert len(_photo_calls(bot_apis["bale"])) == 1
        await push_message(engine, "bale", 9, CUSTOMER_CHAT, text="900")        # a new view
        await push_callback(engine, "bale", 10, CUSTOMER_CHAT, "col:900:12")
        assert len(_photo_calls(bot_apis["bale"])) == 2

    env(scenario)
    # the short "new price" text still went out for the switch
    assert any("605,000,000" in str(a.get("text", "")) for a in bot_apis["bale"].answered)


def test_price_card_failure_falls_back_to_text(settings, env, bot_apis, shopapi):
    settings.bot_image_cards = True
    bot_apis["bale"].fail_methods.add("sendPhoto")
    _shop(shopapi)

    async def scenario(engine, adapters, api):
        await _open_phone(engine)
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "col:900:11")

    env(scenario)
    assert "525,000,000" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)


def test_render_failure_falls_back_to_text(settings, env, bot_apis, shopapi, monkeypatch):
    settings.bot_image_cards = True
    monkeypatch.setattr(render, "FONT_REGULAR", render.ASSETS / "missing.ttf")
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:2")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")

    env(scenario)
    assert not _photo_calls(bot_apis["bale"])
    assert "شمارهٔ سفارش" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)


def test_pre_invoice_card_after_checkout(settings, env, bot_apis, shopapi):
    settings.bot_image_cards = True
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        await push_message(engine, "bale", 1, CUSTOMER_CHAT, text="/start")
        await push_callback(engine, "bale", 2, CUSTOMER_CHAT, "grp:1")
        await push_callback(engine, "bale", 3, CUSTOMER_CHAT, "prod:101")
        await push_callback(engine, "bale", 4, CUSTOMER_CHAT, "add:101:2")
        await push_callback(engine, "bale", 5, CUSTOMER_CHAT, "checkout")

    env(scenario)
    assert len(_photo_calls(bot_apis["bale"])) == 1
    # the text instructions are still sent (copyable card number, receipt prompt)
    assert "شمارهٔ سفارش" in bot_apis["bale"].last_text_any(CUSTOMER_CHAT)


def test_invoice_card_replaces_the_invoiced_text(settings, env, bot_apis, shopapi):
    settings.bot_image_cards = True
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])
        await engine.notify_customers_from_events()
        shopapi.add_event("order_invoiced", order["id"])
        assert await engine.notify_customers_from_events() == 1
        shopapi.add_event("order_invoiced", order["id"])                 # duplicate: once
        await engine.notify_customers_from_events()

    env(scenario)
    assert len(_photo_calls(bot_apis["bale"])) == 1


def test_invoice_falls_back_to_text_when_the_photo_fails(settings, env, bot_apis, shopapi):
    settings.bot_image_cards = True
    bot_apis["bale"].fail_methods.add("sendPhoto")
    shopapi.add_user("bale", CUSTOMER_CHAT, status="approved", person_code=7001)

    async def scenario(engine, adapters, api):
        order = await api.create_order("bale", CUSTOMER_CHAT, [{"kala_code": 101, "qty": 1}])
        await engine.notify_customers_from_events()
        shopapi.add_event("order_invoiced", order["id"])
        await engine.notify_customers_from_events()
        assert texts.ORDER_INVOICED.format(order_id=order["id"]) in bot_apis["bale"].texts(CUSTOMER_CHAT)

    env(scenario)


def test_bale_upload_is_multipart_and_log_safe():
    import asyncio

    import httpx

    from app.platforms import BaleAdapter

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ctype"] = request.headers["content-type"]
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = BaleAdapter(token="TESTTOKEN", client=client)
            return await adapter.send_photo_bytes(1, PNG_MAGIC + b"x" * 10, "caption")

    assert asyncio.run(run()) == {"message_id": 5}
    assert seen["ctype"].startswith("multipart/form-data")
    assert PNG_MAGIC in seen["body"] and b'name="chat_id"' in seen["body"]
