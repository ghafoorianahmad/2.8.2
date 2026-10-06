"""Platform adapters.

Both Bale and Telegram speak the same Bot API method names and JSON shapes, so
the HTTP part lives in one place and only the base URL and the per-platform
feature flags differ.
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
from .telegram import TelegramAdapter

__all__ = [
    "BotApiError",
    "HttpBotAdapter",
    "PlatformAdapter",
    "InlineButtonRow",
    "BaleAdapter",
    "TelegramAdapter",
    "contact_keyboard",
    "inline_keyboard",
    "remove_keyboard",
    "reply_keyboard",
]
