"""Branded image cards: Persian shaping, PNG output, the BOT_IMAGE_CARDS switch and
the text fallbacks (nothing here touches a real network)."""
from __future__ import annotations

import datetime as dt
import io
import sys

import pytest
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


needs_browser = pytest.mark.skipif(render.find_browser() is None,
                                   reason="no Chromium/Edge available for the card screenshot")


# ============================ rendering ======================================
def test_shamsi_date():
    assert shamsi_date(dt.date(2026, 10, 12)) == "1405/07/20"
    assert shamsi_date(dt.date(2025, 3, 21)) == "1404/01/01"
    assert shamsi_date("2026-10-12T08:00:00+00:00") == "1405/07/20"


def test_persian_numbers():
    assert render.fa_num(118_900_000) == "۱۱۸٬۹۰۰٬۰۰۰"
    assert render.fa_num(None) == "۰"


def test_html_is_escaped_and_self_contained():
    page = render._page(render._items_table(
        [{"name": "<script>x</script>", "qty": 1, "unit_price": 5}], "ریال"), 500)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "font/ttf;base64" in page and "http" not in page.replace("http://www.w3.org", "")


def test_icons_are_bundled_and_licensed():
    assert "<path" in render.icon("file-invoice")
    assert (render.ASSETS / "ICONS-LICENSE-MIT.txt").exists()


def _open(png: bytes) -> Image.Image:
    assert png.startswith(PNG_MAGIC)
    return Image.open(io.BytesIO(png))


@needs_browser
def test_cards_are_png_images_with_the_light_theme():
    price = render.price_card(shop="عصر ارتباطات ۲", name="Apple iPhone 17 Pro", color="نارنجی",
                              price=118_900_000, in_stock=True)
    pre = render.pre_invoice_card(shop="عصر ارتباطات ۲", order_id=7, items=ITEMS, total=79_400_000,
                                  payment={"card_number": "6037991122223333", "owner": "نمونه"})
    final = render.final_invoice_card(shop="عصر ارتباطات ۲", order_id=7, items=ITEMS,
                                      total=79_400_000, partial=True, accounting_no=2673)
    for png in (price, pre, final):
        img = _open(png)
        assert img.width == render.W and 400 < img.height < 2400
        from PIL import ImageStat

        assert min(ImageStat.Stat(img.convert("RGB")).mean) > 150   # light theme
    assert _open(pre).height > _open(price).height


@needs_browser
def test_long_and_odd_input_does_not_fail():
    png = render.price_card(shop="x" * 200, name="گوشی " * 60 + "A" * 80, color="ر" * 90,
                            price="not a number", in_stock=False)
    assert png and png.startswith(PNG_MAGIC)
    many = [{"name": f"کالا {i}", "qty": i, "unit_price": 1000 * i} for i in range(1, 40)]
    assert render.final_invoice_card(shop="s", order_id=1, items=many, total=1)


@needs_browser
def test_pre_invoice_without_payment_info_renders():
    png = render.pre_invoice_card(shop="s", order_id=1, items=ITEMS, total=1, payment={})
    assert png and png.startswith(PNG_MAGIC)


def test_no_browser_returns_none(monkeypatch):
    monkeypatch.setattr(render, "find_browser", lambda: None)
    assert render.price_card(shop="s", name="n", color="c", price=1, in_stock=True) is None


def test_browser_crash_returns_none(monkeypatch, tmp_path):
    fake = tmp_path / "fakebrowser.cmd" if sys.platform == "win32" else tmp_path / "fakebrowser"
    fake.write_text("exit 1\n" if sys.platform == "win32" else "#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(render, "find_browser", lambda: str(fake))
    assert render.price_card(shop="s", name="n", color="c", price=1, in_stock=True) is None


def test_browser_override_env(monkeypatch, tmp_path):
    render.find_browser.cache_clear()
    monkeypatch.setenv("BOT_CARD_BROWSER", str(tmp_path / "nope.exe"))
    assert render.find_browser() is None
    render.find_browser.cache_clear()


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


@needs_browser
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
    monkeypatch.setattr(render, "find_browser", lambda: None)
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


@needs_browser
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


@needs_browser
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


# ============================ invoice card rules (HTML level, no browser) ====
def _html(monkeypatch, fn, **kw):
    """The page the card would screenshot."""
    seen = {}
    monkeypatch.setattr(render, "_screenshot", lambda page, h: seen.setdefault("p", page) and b"x")
    assert fn(shop="عصر ارتباطات ۲", order_id=1042, items=ITEMS, total=525_000_000, **kw) == b"x"
    return seen["p"]


CONTACT = {"address": "نشانی نمونه", "phone": "02112345678", "bot_id": "@sample_bot", "thanks": "سپاس از خرید شما"}


def test_invoice_has_logo_no_signature_no_color_and_buyer_label(monkeypatch):
    page = _html(monkeypatch, render.final_invoice_card, accounting_no=7, contact=CONTACT, customer="احمد")
    assert 'class="logo"' in page and "data:image/png;base64" in page
    assert "مهر و امضا" not in page and "با آرزوی همدلی" not in page
    assert "مشکی" not in page and "رنگ" not in page       # item color is never shown
    assert "خریدار:" in page and "مشتری:" not in page
    assert "حسابداری" not in page
    assert "اعتبار" not in page and "ممکن است تغییر کند" not in page   # no price-validity line


def test_invoice_total_in_words_and_tracking_message(monkeypatch):
    page = _html(monkeypatch, render.final_invoice_card, accounting_no=7, contact=CONTACT)
    assert "پانصد و بیست و پنج میلیون ریال" in page
    assert "سفارش شما ثبت شد — شمارهٔ پیگیری: ۱۰۴۲" in page


def test_titles_follow_the_order_state(monkeypatch):
    assert "پیش‌فاکتور</div>" in _html(monkeypatch, render.pre_invoice_card)
    final = _html(monkeypatch, render.final_invoice_card, accounting_no=7)
    assert "فاکتور فروش</div>" in final and "پیش‌فاکتور" not in final


def test_footer_is_built_from_the_given_shop_settings(monkeypatch):
    page = _html(monkeypatch, render.pre_invoice_card, contact=CONTACT)
    for value in ("نشانی نمونه", "@sample_bot", "سپاس از خرید شما", "۰۲۱۱۲۳۴۵۶۷۸"):
        assert value in page
    assert 'class="contact"' not in _html(monkeypatch, render.pre_invoice_card)   # nothing configured


def test_payment_section_only_when_configured(monkeypatch):
    none = _html(monkeypatch, render.pre_invoice_card, payment={"card_number": "", "sheba": None})
    assert 'class="payrow"' not in none and "شمارهٔ شبا" not in none and "شمارهٔ کارت" not in none
    full = _html(monkeypatch, render.pre_invoice_card, payment={
        "card_number": "6037991122223333", "sheba": "ir062960000000100324200001", "owner": "احمد نمونه"})
    assert "6037 9911 2222 3333" in full and "IR062960000000100324200001" in full and "احمد نمونه" in full
    partial = _html(monkeypatch, render.pre_invoice_card, payment={"owner": "فقط نام"})
    assert "فقط نام" in partial and "شمارهٔ کارت" not in partial


def test_price_card_has_no_accounting_word(monkeypatch):
    seen = {}
    monkeypatch.setattr(render, "_screenshot", lambda page, h: seen.setdefault("p", page) and b"x")
    render.price_card(shop="s", name="n", color="سبز", price=1, in_stock=True)
    assert "حسابداری" not in seen["p"] and "سبز" in seen["p"]      # the color column stays on this card


def test_missing_logo_does_not_break_the_card(monkeypatch, tmp_path):
    render._logo_tag.cache_clear()
    monkeypatch.setattr(render, "LOGO_FILE", tmp_path / "none.png")
    assert render._logo_tag() == ""
    render._logo_tag.cache_clear()
