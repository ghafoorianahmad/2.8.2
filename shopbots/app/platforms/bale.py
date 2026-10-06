"""Bale adapter (https://tapi.bale.ai)."""
from __future__ import annotations

import httpx

from .base import HttpBotAdapter


class BaleAdapter(HttpBotAdapter):
    """Bale's Bot API mirrors Telegram's method names and JSON shapes.

    Feature flags are deliberately conservative; see NOTES.md — the Bale base
    URL and these capabilities must be verified against Bale's official docs
    with a real test bot.
    """

    platform = "bale"
    supports_inline_keyboard = True
    supports_reply_keyboard = True
    supports_contact_button = True

    def __init__(
        self,
        token: str,
        api_base: str = "https://tapi.bale.ai",
        client: httpx.AsyncClient | None = None,
        timeout: float = 40.0,
    ):
        super().__init__(token=token, api_base=api_base, client=client, timeout=timeout)
