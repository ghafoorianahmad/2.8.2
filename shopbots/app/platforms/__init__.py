"""Platform adapters.

Bale speaks the Telegram-style Bot API (same method names and JSON shapes), so
the HTTP part lives in HttpBotAdapter and a channel only sets its base URL and
feature flags. Telegram is a Telethon bot connection through the MTProto proxy
pool (telegram.py, imported lazily: Telethon is only needed when that channel is
configured). Adding a channel = one thin adapter here; the business logic lives
in app/core and app/engine.
"""
from __future__ import annotations

from .base import (
    BotApiError,
    HttpBotAdapter,
    InlineButtonRow,
    PlatformAdapter,
    contact_keyboard,
    web_app_keyboard,
    inline_keyboard,
    remove_keyboard,
    reply_keyboard,
)
from .bale import BaleAdapter

__all__ = [
    "BotApiError",
    "HttpBotAdapter",
    "PlatformAdapter",
    "InlineButtonRow",
    "BaleAdapter",
    "contact_keyboard",
    "inline_keyboard",
    "remove_keyboard",
    "reply_keyboard",
]
