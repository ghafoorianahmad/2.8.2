"""Thin wrapper around Telethon: the only module that touches Telegram.

Read-only by design: it connects, reads messages of public channels, downloads
documents and pings. It never joins, posts, reacts or marks anything as read.
Tests replace ``client_factory`` with a fake Telethon client.
"""
from __future__ import annotations

import asyncio
import logging
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .proxies import ProxyLink

log = logging.getLogger(__name__)

DEVICE = dict(device_model="ShopServer", system_version="Windows", app_version="shoptg 1.0",
              lang_code="fa", system_lang_code="fa")


class NotAuthorized(Exception):
    """The saved session is no longer logged in (revoked / logged out)."""


@dataclass
class TgMessage:
    id: int
    date: datetime | None
    text: str = ""
    urls: list[str] = field(default_factory=list)
    is_pdf: bool = False
    file_size: int = 0
    file_name: str = ""
    raw: Any = field(default=None, repr=False)


def connection_for(link: ProxyLink | None) -> dict:
    """``TelegramClient`` keyword arguments for a proxy (``{}`` = direct)."""
    if link is None:
        return {}
    from telethon.network.connection import (
        ConnectionTcpMTProxyIntermediate,
        ConnectionTcpMTProxyRandomizedIntermediate,
    )
    if link.kind == "ee":
        from .faketls import ConnectionTcpMTProxyFakeTLS
        conn = ConnectionTcpMTProxyFakeTLS
    elif link.kind == "dd":
        conn = ConnectionTcpMTProxyRandomizedIntermediate
    else:
        conn = ConnectionTcpMTProxyIntermediate
    return {"connection": conn, "proxy": (link.host, link.port, link.secret)}


def _default_client_factory(session: str, api_id: int, api_hash: str, **kwargs):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(session or None), api_id, api_hash, **kwargs)


def to_message(msg: Any) -> TgMessage:
    """Telethon ``Message`` -> TgMessage (text, every URL, PDF metadata)."""
    text = getattr(msg, "message", None) or ""
    urls: list[str] = []
    for ent in getattr(msg, "entities", None) or []:
        url = getattr(ent, "url", None)
        if url:
            urls.append(url)
    markup = getattr(msg, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        for button in getattr(row, "buttons", None) or []:
            url = getattr(button, "url", None)
            if url:
                urls.append(url)
    is_pdf, size, name = False, 0, ""
    file = getattr(msg, "file", None) if getattr(msg, "document", None) is not None else None
    if file is not None:
        mime = (getattr(file, "mime_type", "") or "").lower()
        name = getattr(file, "name", "") or ""
        size = int(getattr(file, "size", 0) or 0)
        is_pdf = mime == "application/pdf" or name.lower().endswith(".pdf")
    return TgMessage(id=int(msg.id), date=getattr(msg, "date", None), text=text, urls=urls,
                     is_pdf=is_pdf, file_size=size, file_name=name, raw=msg)


class TelegramGateway:
    def __init__(self, api_id: int, api_hash: str, *, timeout: float = 20,
                 client_factory: Callable[..., Any] = _default_client_factory,
                 clock: Callable[[], float] = time.monotonic):
        self._api_id = api_id
        self._api_hash = api_hash
        self._timeout = timeout
        self._factory = client_factory
        self._clock = clock
        self._client: Any = None
        self.proxy: ProxyLink | None = None

    def make_client(self, session: str, link: ProxyLink | None):
        with warnings.catch_warnings():
            # MTProxy does not use python-socks; Telethon warns regardless.
            warnings.filterwarnings("ignore", message="proxy argument will be ignored")
            return self._make_client(session, link)

    def _make_client(self, session: str, link: ProxyLink | None):
        return self._factory(session, self._api_id, self._api_hash,
                             receive_updates=False, connection_retries=1, retry_delay=1,
                             request_retries=2, timeout=self._timeout,
                             flood_sleep_threshold=0, **DEVICE, **connection_for(link))

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self, session: str, link: ProxyLink | None) -> int:
        """Connect with the saved session through ``link``; latency in ms."""
        await self.disconnect()
        client = self.make_client(session, link)
        started = self._clock()
        try:
            await asyncio.wait_for(client.connect(), self._timeout)
            authorized = await asyncio.wait_for(client.is_user_authorized(), self._timeout)
        except BaseException:
            await _quiet_disconnect(client)
            raise
        if not authorized:
            await _quiet_disconnect(client)
            raise NotAuthorized()
        self._client, self.proxy = client, link
        return int((self._clock() - started) * 1000)

    async def ping(self) -> int:
        """A cheap request on the logged-in connection; latency in ms."""
        from telethon.tl.functions.help import GetNearestDcRequest
        if self._client is None:
            raise ConnectionError("not connected")
        started = self._clock()
        await asyncio.wait_for(self._client(GetNearestDcRequest()), self._timeout)
        return int((self._clock() - started) * 1000)

    async def probe(self, link: ProxyLink) -> int:
        """Test a proxy with a throw-away *anonymous* client (never the shop's
        session: the same auth key from two IPs can get it revoked)."""
        client = self.make_client("", link)
        started = self._clock()
        try:
            await asyncio.wait_for(client.connect(), self._timeout)
            return int((self._clock() - started) * 1000)
        finally:
            await _quiet_disconnect(client)

    async def messages(self, channel: str, *, min_id: int = 0, limit: int = 50) -> list[TgMessage]:
        """Messages newer than ``min_id``, oldest first (at most ``limit``)."""
        if self._client is None:
            raise ConnectionError("not connected")

        async def collect():
            return [to_message(m) async for m in
                    self._client.iter_messages(channel, min_id=min_id, limit=limit)]
        out = await asyncio.wait_for(collect(), self._timeout * 3)
        return sorted(out, key=lambda m: m.id)

    async def download(self, message: TgMessage, max_bytes: int) -> bytes:
        if self._client is None:
            raise ConnectionError("not connected")
        if message.file_size > max_bytes:
            raise ValueError("file too large")
        data = await asyncio.wait_for(
            self._client.download_media(message.raw, file=bytes), self._timeout * 6)
        if not isinstance(data, (bytes, bytearray)) or len(data) > max_bytes:
            raise ValueError("unexpected download result")
        return bytes(data)

    async def disconnect(self) -> None:
        client, self._client, self.proxy = self._client, None, None
        if client is not None:
            await _quiet_disconnect(client)


async def _quiet_disconnect(client) -> None:
    try:
        await asyncio.wait_for(client.disconnect(), 10)
    except Exception:  # noqa: BLE001 - closing a broken connection
        log.debug("disconnect failed", exc_info=True)
