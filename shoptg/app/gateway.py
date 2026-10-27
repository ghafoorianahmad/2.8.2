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

from tgproxy import ProxyLink
from tgproxy.connection import connection_for

log = logging.getLogger(__name__)

#: The default InitConnection parameters (own api_id); Settings.device() gives
#: the Telegram Desktop ones for the public key (v2.9.0).
DEVICE = dict(device_model="ShopServer", system_version="Windows", app_version="shoptg 1.1",
              lang_code="fa", system_lang_code="fa", lang_pack="")


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
    #: v2.9.1: when the post was last edited (a list PDF may be replaced in place)
    edit_date: datetime | None = None

    @property
    def version(self) -> str:
        """Changes when the post is edited (or its file replaced)."""
        stamp = self.edit_date.isoformat() if self.edit_date else ""
        return f"{self.id}:{stamp}:{self.file_size}"

    @property
    def published(self) -> datetime | None:
        """The post time, or its last edit (an edited list is the newer list)."""
        return self.edit_date or self.date


@dataclass
class TgChannel:
    """v2.9.1: a channel (or group) the account has joined."""
    id: int
    username: str = ""
    title: str = ""
    broadcast: bool = True

    @property
    def ref(self) -> str:
        """What the reader asks Telegram for: the @name, else the numeric id."""
        return self.username or str(self.id)


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
                     is_pdf=is_pdf, file_size=size, file_name=name, raw=msg,
                     edit_date=getattr(msg, "edit_date", None))


def channel_target(ref: str):
    """A channel @name as is; a numeric id as a channel peer (known from the dialogs)."""
    value = str(ref or "").strip()
    if value.lstrip("-").isdigit():
        from telethon.tl.types import PeerChannel

        return PeerChannel(abs(int(value)))
    return value


class TelegramGateway:
    def __init__(self, api_id: int, api_hash: str, *, timeout: float = 20,
                 client_factory: Callable[..., Any] = _default_client_factory,
                 clock: Callable[[], float] = time.monotonic,
                 device: dict[str, str] | None = None, probe_timeout: float | None = None):
        self._api_id = api_id
        self._api_hash = api_hash
        self._timeout = timeout
        self._probe_timeout = probe_timeout or min(timeout, 12)
        self._device = dict(DEVICE, **(device or {}))
        self._factory = client_factory
        self._clock = clock
        self._client: Any = None
        self.proxy: ProxyLink | None = None
        #: v2.13.0: channel -> InputPeer, kept across reconnects (same account)
        self._peers: dict[str, Any] = {}

    def make_client(self, session: str, link: ProxyLink | None):
        with warnings.catch_warnings():
            # MTProxy does not use python-socks; Telethon warns regardless.
            warnings.filterwarnings("ignore", message="proxy argument will be ignored")
            return self._make_client(session, link)

    def _make_client(self, session: str, link: ProxyLink | None):
        device = dict(self._device)
        lang_pack = device.pop("lang_pack", "")
        client = self._factory(session, self._api_id, self._api_hash,
                               receive_updates=False, connection_retries=1, retry_delay=1,
                               request_retries=2, timeout=self._timeout,
                               flood_sleep_threshold=0, **device, **connection_for(link))
        # Telethon 1.x has no constructor argument for InitConnection.lang_pack
        # (Telegram Desktop sends "tdesktop"); it is set on the prepared request.
        init = getattr(client, "_init_request", None)
        if lang_pack and init is not None and hasattr(init, "lang_pack"):
            init.lang_pack = lang_pack
        return client

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
            await asyncio.wait_for(client.connect(), self._probe_timeout)
            return int((self._clock() - started) * 1000)
        finally:
            await _quiet_disconnect(client)

    async def messages(self, channel: str, *, min_id: int = 0, limit: int = 50) -> list[TgMessage]:
        """Messages newer than ``min_id``, oldest first (at most ``limit``)."""
        if self._client is None:
            raise ConnectionError("not connected")

        target = await self._peer(channel)

        async def collect():
            return [to_message(m) async for m in
                    self._client.iter_messages(target, min_id=min_id, limit=limit)]
        try:
            out = await asyncio.wait_for(collect(), self._timeout * 3)
        except BaseException:
            self._peers.pop(str(channel).lower(), None)
            raise
        return sorted(out, key=lambda m: m.id)

    async def _peer(self, channel: str):
        """v2.13.0: the channel is looked up (ResolveUsername) once and kept across
        reconnects: every lookup counts against Telegram's limits, and a reader
        that reconnected often was told to wait for hours (all jobs paused)."""
        key = str(channel).lower()
        peer = self._peers.get(key)
        if peer is not None:
            return peer
        target = channel_target(channel)
        resolve = getattr(self._client, "get_input_entity", None)
        if resolve is None:
            return target
        peer = await asyncio.wait_for(resolve(target), self._timeout)
        self._peers[key] = peer
        return peer

    async def channels(self, limit: int = 300) -> list[TgChannel]:
        """v2.9.1: channels and groups the account has joined (read only: the
        dialog list; nothing is opened, read or marked)."""
        if self._client is None:
            raise ConnectionError("not connected")

        async def collect():
            out = []
            async for dialog in self._client.iter_dialogs(limit=limit):
                if not getattr(dialog, "is_channel", False):
                    continue
                entity = dialog.entity
                out.append(TgChannel(id=int(entity.id), username=getattr(entity, "username", None) or "",
                                     title=str(getattr(dialog, "name", "") or "")[:120],
                                     broadcast=bool(getattr(entity, "broadcast", False))))
            return out
        return await asyncio.wait_for(collect(), self._timeout * 3)

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
