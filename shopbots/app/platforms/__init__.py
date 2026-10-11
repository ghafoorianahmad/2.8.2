"""Platform adapters.

Bale speaks the Telegram-style Bot API (same method names and JSON shapes), so
the HTTP part lives in HttpBotAdapter and a channel only sets its base URL and
feature flags. Adding a channel = one thin adapter here; the business logic
lives in app/core and app/engine.
"""
from __future__ import annotations

from .base import (
    BotApiError,
    HttpBotAdapter,
    InlineButtonRow,
    PlatformAdapter,
    contact_keyboard,
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
