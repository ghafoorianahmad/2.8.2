"""Telegram adapter: a Telethon *bot* connection through the MTProto proxy pool.

No webhook and no inbound port: the bot logs in with its BotFather token over an
outgoing MTProto connection (fake-TLS ``ee`` proxies included, via the shared
``tgproxy`` package). Telethon pushes updates; they are turned into Bot-API-shaped
update dicts and queued, so ``polling.poll_platform`` and ``BotEngine`` work
unchanged (same flows as Bale).

Proxy handling: candidates come from ``ProxyPool`` (best first). A dead connection
(failed ping, dropped socket) is discarded and the next ``get_updates`` call
reconnects through the next candidate; every attempt is reported back to shopapi.

Privacy: no error text or log line contains the bot token, the api hash or a proxy
secret; failures are described by exception class only.
"""
from __future__ import annotations

import asyncio
import logging
import time
import warnings
from collections import OrderedDict
from typing import Any, Callable

from tgproxy.connection import connection_for

from .base import BotApiError, PlatformAdapter, Update

logger = logging.getLogger("shopbots.telegram")

MESSAGE_LIMIT = 4096
CALLBACK_DATA_LIMIT = 64
_CACHE_SIZE = 256
#: Wrong credentials are not a proxy problem: do not cycle through the pool.
_FATAL_AUTH = {"AccessTokenInvalidError", "AccessTokenExpiredError", "ApiIdInvalidError"}
_DEVICE = dict(device_model="ShopBot", system_version="Windows", app_version="shopbots 1.0",
               lang_code="fa", system_lang_code="fa")


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Chunks of at most ``limit`` characters, cut at line ends when possible."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def to_buttons(reply_markup: dict | None):
    """Bot-API reply markup -> Telethon ``buttons`` (None = no change)."""
    if not reply_markup:
        return None
    from telethon import Button
    if reply_markup.get("remove_keyboard"):
        return Button.clear()
    if "inline_keyboard" in reply_markup:
        rows = []
        for row in reply_markup["inline_keyboard"]:
            out = []
            for btn in row:
                data = str(btn.get("callback_data", "")).encode("utf-8")
                if len(data) > CALLBACK_DATA_LIMIT:
                    raise BotApiError("buttons", "callback data too long")
                out.append(Button.inline(str(btn["text"]), data))
            rows.append(out)
        return rows
    if "keyboard" in reply_markup:
        resize = bool(reply_markup.get("resize_keyboard", True))
        once = bool(reply_markup.get("one_time_keyboard", False))
        rows = []
        for row in reply_markup["keyboard"]:
            out = []
            for btn in row:
                text = str(btn["text"])
                if btn.get("web_app"):
                    # the reply keyboard's kind: the page may send data back (Bot API web_app)
                    from telethon.tl.types import ButtonTypeSimpleWebView, KeyboardButton
                    out.append(Button(
                        KeyboardButton(text, ButtonTypeSimpleWebView(str(btn["web_app"]["url"]))),
                        resize=resize, single_use=once, selective=None, persistent=None,
                        placeholder=None))
                elif btn.get("request_contact"):
                    out.append(Button.request_phone(text, resize=resize, single_use=once))
                else:
                    out.append(Button.text(text, resize=resize, single_use=once))
            rows.append(out)
        return rows
    return None


def _default_client_factory(session: Any, api_id: int, api_hash: str, **kwargs):
    from telethon import TelegramClient
    return TelegramClient(session, api_id, api_hash, **kwargs)


class TelethonBotAdapter(PlatformAdapter):
    platform = "telegram"
    supports_inline_keyboard = True
    supports_reply_keyboard = True
    supports_contact_button = True

    def __init__(
        self,
        *,
        bot_token: str,
        api_id: int,
        api_hash: str,
        pool,
        session_path: str = "",
        client_factory: Callable[..., Any] = _default_client_factory,
        connect_timeout: float = 20.0,
        health_interval: float = 180.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._token = bot_token
        self._api_id = api_id
        self._api_hash = api_hash
        self._pool = pool
        self._session_path = session_path
        self._factory = client_factory
        self._timeout = connect_timeout
        self._health_interval = health_interval
        self._clock = clock
        self._client: Any = None
        self._link = None
        self._last_ok = 0.0
        self._queue: asyncio.Queue[Update] = asyncio.Queue(maxsize=2000)
        self._last_id = 0
        self._messages: OrderedDict[str, Any] = OrderedDict()
        self._callbacks: OrderedDict[str, Any] = OrderedDict()
        self._lock = asyncio.Lock()

    # ---- connection ---------------------------------------------------------
    def _new_client(self, link):
        if self._session_path:
            session: Any = self._session_path      # SQLite file: update state + entity cache
            catch_up = True
        else:
            from telethon.sessions import StringSession
            session, catch_up = StringSession(), False
        extra = dict(receive_updates=True, catch_up=catch_up, sequential_updates=True,
                     connection_retries=1, retry_delay=1, request_retries=2,
                     timeout=self._timeout, flood_sleep_threshold=60, **_DEVICE)
        with warnings.catch_warnings():
            # MTProxy does not use python-socks; Telethon warns regardless.
            warnings.filterwarnings("ignore", message="proxy argument will be ignored")
            client = self._factory(session, self._api_id, self._api_hash,
                                   **extra, **connection_for(link))
        client.parse_mode = None        # texts are plain; Telethon defaults to Markdown
        return client

    def _register(self, client) -> None:
        from telethon import events
        client.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        client.add_event_handler(self._on_callback, events.CallbackQuery())
        from telethon.tl.types import UpdateNewMessage
        client.add_event_handler(self._on_raw, events.Raw(UpdateNewMessage))

    async def _ensure_connected(self) -> None:
        if self._client is not None:
            return
        async with self._lock:
            if self._client is not None:
                return
            links = await self._pool.candidates()
            results: list[dict] = []
            try:
                for link in links:
                    started = self._clock()
                    client = self._new_client(link)
                    try:
                        await asyncio.wait_for(client.connect(), self._timeout)
                        if not await asyncio.wait_for(client.is_user_authorized(), self._timeout):
                            await asyncio.wait_for(client.sign_in(bot_token=self._token),
                                                   self._timeout)
                    except asyncio.CancelledError:
                        await self._quiet_disconnect(client)
                        raise
                    except Exception as exc:  # noqa: BLE001 - any failure = next proxy
                        await self._quiet_disconnect(client)
                        name = type(exc).__name__
                        if name in _FATAL_AUTH:
                            raise BotApiError("start", "401 bot token or api credentials invalid") from None
                        logger.info("telegram connection via %s failed (%s)", _where(link), name)
                        results.append({"id": getattr(link, "id", None), "ok": False})
                        continue
                    latency = int((self._clock() - started) * 1000)
                    results.append({"id": getattr(link, "id", None), "ok": True,
                                    "latency_ms": latency})
                    self._register(client)
                    self._client, self._link = client, link
                    self._last_ok = self._clock()
                    logger.info("telegram connected via %s in %d ms", _where(link), latency)
                    return
            finally:
                await self._pool.report(results)
            raise BotApiError("connect", "no proxy could reach Telegram" if links
                              else "no proxy configured", network=True)

    @staticmethod
    async def _quiet_disconnect(client) -> None:
        try:
            await asyncio.wait_for(client.disconnect(), 10)
        except Exception:  # noqa: BLE001 - closing a broken connection
            logger.debug("disconnect failed", exc_info=True)

    async def _drop(self) -> None:
        client, self._client, self._link = self._client, None, None
        if client is not None:
            await self._quiet_disconnect(client)

    async def _health(self) -> None:
        """Ping on the live connection every ``health_interval`` s; a failure
        drops it so the next ``get_updates`` reconnects through the next proxy."""
        client = self._client
        if client is None:
            return
        if not client.is_connected():
            await self._fail_link("disconnected")
        if self._clock() - self._last_ok < self._health_interval:
            return
        from telethon.tl.functions.help import GetNearestDcRequest
        started = self._clock()
        try:
            await asyncio.wait_for(client(GetNearestDcRequest()), self._timeout)
        except Exception as exc:  # noqa: BLE001
            await self._fail_link(type(exc).__name__)
        self._last_ok = self._clock()
        await self._pool.report([{"id": getattr(self._link, "id", None), "ok": True,
                                  "latency_ms": int((self._last_ok - started) * 1000)}])

    async def _fail_link(self, reason: str) -> None:
        link = self._link
        logger.warning("telegram connection via %s lost (%s); switching proxy", _where(link), reason)
        await self._drop()
        await self._pool.report([{"id": getattr(link, "id", None), "ok": False}])
        raise BotApiError("ping", reason, network=True)

    # ---- updates in ---------------------------------------------------------
    def _next_id(self) -> int:
        # Strictly increasing across restarts (the engine stores the last id).
        self._last_id = max(self._last_id + 1, time.time_ns() // 1000)
        return self._last_id

    def _remember(self, cache: OrderedDict, key: str, value: Any) -> None:
        cache[key] = value
        while len(cache) > _CACHE_SIZE:
            cache.popitem(last=False)

    def _push(self, update: Update) -> None:
        update["update_id"] = self._next_id()
        try:
            self._queue.put_nowait(update)
        except asyncio.QueueFull:
            logger.error("telegram update queue full; update dropped")

    @staticmethod
    def _sender_dict(sender: Any, sender_id: Any) -> dict:
        if sender is None:
            return {"id": sender_id}
        return {"id": getattr(sender, "id", sender_id),
                "first_name": getattr(sender, "first_name", None),
                "last_name": getattr(sender, "last_name", None),
                "username": getattr(sender, "username", None)}

    async def _on_message(self, event) -> None:
        msg = event.message
        try:
            sender = await event.get_sender()
        except Exception:  # noqa: BLE001 - entity lookup failed; the id is enough
            sender = None
        if getattr(sender, "bot", False):
            return
        chat_id = event.chat_id
        ref = f"{chat_id}:{msg.id}"
        message: dict[str, Any] = {
            "message_id": msg.id,
            "chat": {"id": chat_id, "type": "private" if event.is_private else "group"},
            "from": self._sender_dict(sender, event.sender_id),
            "text": getattr(msg, "message", None) or "",
        }
        contact = getattr(msg, "contact", None)
        if contact is not None:
            message["contact"] = {
                "phone_number": getattr(contact, "phone_number", None),
                "first_name": getattr(contact, "first_name", None),
                "last_name": getattr(contact, "last_name", None),
                # 0 = the contact is not a Telegram account (or id hidden): never equals the sender
                "user_id": getattr(contact, "user_id", None) or None,
            }
        file = getattr(msg, "file", None)
        if getattr(msg, "photo", None) is not None:
            self._remember(self._messages, ref, msg)
            message["photo"] = [{"file_id": ref, "file_size": getattr(file, "size", None)}]
        elif getattr(msg, "document", None) is not None and file is not None:
            self._remember(self._messages, ref, msg)
            message["document"] = {"file_id": ref, "mime_type": getattr(file, "mime_type", None),
                                   "file_name": getattr(file, "name", None),
                                   "file_size": getattr(file, "size", None)}
        self._push({"message": message})

    async def _on_raw(self, update) -> None:
        """v2.18.0: what a mini app sent (a service message: NewMessage never shows these)."""
        message = getattr(update, "message", None)
        action = getattr(message, "action", None)
        if type(action).__name__ != "MessageActionWebViewDataSentMe":
            return
        peer = getattr(message, "peer_id", None)
        user_id = getattr(peer, "user_id", None)
        if user_id is None:
            return
        data = getattr(action, "data", "")
        self._push({"message": {
            "message_id": getattr(message, "id", 0),
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id},
            "text": "",
            "web_app_data": {"data": data},
        }})

    async def _on_callback(self, event) -> None:
        data = getattr(event, "data", b"") or b""
        callback_id = str(event.query.query_id)
        self._remember(self._callbacks, callback_id, event)
        self._push({"callback_query": {
            "id": callback_id,
            "data": data.decode("utf-8", "replace"),
            "message": {"message_id": event.message_id,
                        "chat": {"id": event.chat_id,
                                 "type": "private" if event.is_private else "group"}},
        }})

    async def get_updates(
        self, offset: int | None = None, timeout: int = 25, limit: int = 100
    ) -> list[Update]:
        await self._ensure_connected()
        await self._health()
        updates: list[Update] = []
        deadline = self._clock() + max(0, timeout)
        while not updates:
            if not self._queue.empty():
                break
            remaining = deadline - self._clock()
            if remaining <= 0:
                return updates
            try:
                updates.append(await asyncio.wait_for(self._queue.get(), min(remaining, 5.0)))
            except asyncio.TimeoutError:
                if self._client is None or not self._client.is_connected():
                    await self._fail_link("disconnected")
        while len(updates) < limit and not self._queue.empty():
            updates.append(self._queue.get_nowait())
        return updates

    # ---- calls out ----------------------------------------------------------
    async def _call(self, method: str, make) -> Any:
        """Run ``make(client)``; map Telethon/network failures to BotApiError."""
        await self._ensure_connected()
        try:
            return await asyncio.wait_for(make(self._client), self._timeout * 3)
        except BotApiError:
            raise
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            await self._drop()          # reconnect (next proxy) on the next call
            raise BotApiError(method, "timeout" if isinstance(exc, asyncio.TimeoutError)
                              else "network error", network=True) from None
        except ValueError:
            raise BotApiError(method, "unknown chat") from None
        except Exception as exc:  # noqa: BLE001 - Telethon RPC errors
            raise BotApiError(method, type(exc).__name__) from None

    async def send_text(
        self, chat_id: str | int, text: str, reply_markup: dict | None = None
    ) -> dict | None:
        buttons = to_buttons(reply_markup)
        chunks = split_text(text)
        sent = None
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            sent = await self._call("sendMessage", lambda c, chunk=chunk, last=last: c.send_message(
                int(chat_id), chunk, buttons=buttons if last else None, link_preview=False))
        return {"message_id": getattr(sent, "id", None)}

    async def _resolve(self, ref: str):
        msg = self._messages.get(ref)
        if msg is not None:
            return msg
        chat, _, mid = str(ref).partition(":")
        if not chat.lstrip("-").isdigit() or not mid.isdigit():
            return None
        return await self._call("getFile", lambda c: c.get_messages(int(chat), ids=int(mid)))

    async def send_photo(
        self,
        chat_id: str | int,
        photo: str,
        caption: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict | None:
        msg = await self._resolve(photo)
        media = getattr(msg, "media", None)
        if media is None:
            raise BotApiError("sendPhoto", "unknown photo")
        buttons = to_buttons(reply_markup)
        sent = await self._call("sendPhoto", lambda c: c.send_file(
            int(chat_id), media, caption=(caption or "")[:1024], buttons=buttons))
        return {"message_id": getattr(sent, "id", None)}

    async def send_photo_bytes(
        self, chat_id: str | int, png: bytes, caption: str | None = None
    ) -> dict | None:
        import io

        buffer = io.BytesIO(png)
        buffer.name = "card.png"
        sent = await self._call("sendPhoto", lambda c: c.send_file(
            int(chat_id), buffer, caption=(caption or "")[:1024], force_document=False))
        return {"message_id": getattr(sent, "id", None)}

    async def send_document_bytes(
        self, chat_id: str | int, data: bytes, filename: str, caption: str | None = None,
        content_type: str = "application/pdf",
    ) -> dict | None:
        import io

        buffer = io.BytesIO(data)
        buffer.name = filename
        sent = await self._call("sendDocument", lambda c: c.send_file(
            int(chat_id), buffer, caption=(caption or "")[:1024], force_document=True))
        return {"message_id": getattr(sent, "id", None)}

    async def edit_text(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict | None:
        buttons = to_buttons(reply_markup)
        edited = await self._call("editMessageText", lambda c: c.edit_message(
            int(chat_id), int(message_id), split_text(text)[0], buttons=buttons, link_preview=False))
        return {"message_id": getattr(edited, "id", message_id)}

    async def answer_callback(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        event = self._callbacks.pop(str(callback_query_id), None)
        if event is None:
            return
        await self._call("answerCallbackQuery", lambda c: event.answer(
            (text or None), alert=bool(show_alert)))

    async def download_file_ref(
        self, file_ref: str, max_bytes: int | None = None
    ) -> bytes | None:
        msg = await self._resolve(file_ref)
        media = getattr(msg, "media", None)
        if media is None:
            return None
        declared = getattr(getattr(msg, "file", None), "size", None)
        if max_bytes is not None and isinstance(declared, int) and declared > max_bytes:
            raise BotApiError("getFile", "too large")

        async def fetch(client) -> bytes:
            chunks: list[bytes] = []
            received = 0
            async for chunk in client.iter_download(media):
                received += len(chunk)
                if max_bytes is not None and received > max_bytes:
                    raise BotApiError("getFile", "too large")      # cut off, never held whole
                chunks.append(bytes(chunk))
            return b"".join(chunks)
        return await self._call("getFile", fetch)

    async def aclose(self) -> None:
        await self._drop()
        await self._pool.aclose()


def _where(link) -> str:
    return "direct" if link is None else link.masked()
