"""Telegram adapter (https://api.telegram.org), optionally behind a proxy.

Telegram is only reachable through a local proxy (TELEGRAM_PROXY, e.g.
socks5://127.0.0.1:10808). The proxy is set on this adapter's own httpx client,
so every Telegram call - long polling, sending, getFile and the file download -
goes through it, while shopapi / Bale clients never see it.
"""
from __future__ import annotations

import httpx

from ..config import describe_proxy
from .base import BotApiError, HttpBotAdapter


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

    @property
    def proxy_label(self) -> str:
        return describe_proxy(self.proxy_url)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            try:
                # trust_env=False: only TELEGRAM_PROXY decides, never a stray
                # HTTP(S)_PROXY / ALL_PROXY variable of the Windows account.
                self._client = httpx.AsyncClient(
                    timeout=self._timeout, proxy=self.proxy_url, trust_env=False
                )
            except ImportError:
                raise BotApiError(
                    "proxy", "SOCKS support missing (install socksio)", network=True
                ) from None
            except ValueError:
                raise BotApiError(
                    "proxy", f"invalid TELEGRAM_PROXY ({self.proxy_label})", network=True
                ) from None
            self._owns_client = True
        return self._client

    def _network_error(self, method: str, exc: httpx.HTTPError) -> BotApiError:
        if not self.proxy_url:
            return super()._network_error(method, exc)
        if isinstance(exc, httpx.ProxyError):
            return BotApiError(method, f"proxy refused ({self.proxy_label})", network=True)
        if isinstance(exc, httpx.TimeoutException):
            return BotApiError(method, f"timeout via proxy ({self.proxy_label})", network=True)
        return BotApiError(
            method, f"proxy unreachable or down ({self.proxy_label})", network=True
        )
