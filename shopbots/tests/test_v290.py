"""v2.9.0: the owner hears about a price list the Telegram reader could not fetch,
and the login notice points to «تنظیمات سرور»."""
from __future__ import annotations

from app import engine, texts


def test_pricelist_error_reaches_the_owner_chats():
    key = engine.OWNER_EVENT_TEXTS["telegram_pricelist_error"]
    assert key == "TG_PRICELIST_ERROR_NOTICE"
    texts.load()
    assert "لیست قیمت" in getattr(texts, key)


def test_login_notice_points_to_the_server_settings():
    texts.load()
    assert "تنظیمات سرور" in texts.TG_LOGIN_NOTICE and "shoptg" not in texts.TG_LOGIN_NOTICE
