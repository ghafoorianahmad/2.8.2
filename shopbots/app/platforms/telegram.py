"""Telegram adapter (https://api.telegram.org), optionally behind a proxy."""
from __future__ import annotations

import httpx

from .base import HttpBotAdapter


class TelegramAdapter(HttpBotAdapter):
    platform = "telegram"
    supports_inline_keyboard = True
    supports_reply_keyboard = True
    supports_contact_button = True

    def __init__(
        self,
        token: str,
        api_base: str = "https://api.telegram.org",
        client: httpx.AsyncClient | None = None,
        timeout: float = 40.0,
        proxy_url: str | None = None,
    ):
        super().__init__(token=token, api_base=api_base, client=client, timeout=timeout)
        self.proxy_url = proxy_url or None

    async def _http(self) -> httpx.AsyncClient:
        # Telegram is blocked in Iran, so the owned client honours PROXY_URL.
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, proxy=self.proxy_url)
            self._owns_client = True
        return self._client
