"""PlatformAdapter interface and the shared Bot API HTTP implementation.

Privacy: errors raised here never contain the request URL (which embeds the bot
token) — only the method name and a short description.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Sequence

import httpx

# A row of buttons: every button is (label, callback_data).
ButtonRow = Sequence[tuple[str, str]]
InlineButtonRow = list[list[dict]]
Update = dict[str, Any]


class BotApiError(Exception):
    """A Bot API call failed. The message is safe to log (no token, no URL)."""

    def __init__(self, method: str, description: str, *, network: bool = False):
        super().__init__(f"{method}: {description}")
        self.method = method
        self.description = description
        #: True when the Bot API was not reached at all (network down).
        self.network = network


class PlatformAdapter(ABC):
    platform: str = ""
    supports_inline_keyboard: bool = True
    supports_reply_keyboard: bool = True
    supports_contact_button: bool = True

    @abstractmethod
    async def get_updates(
        self, offset: int | None = None, timeout: int = 25, limit: int = 100
    ) -> list[Update]: ...

    @abstractmethod
    async def send_text(
        self, chat_id: str | int, text: str, reply_markup: dict | None = None
    ) -> dict | None: ...

    @abstractmethod
    async def send_photo(
        self,
        chat_id: str | int,
        photo: str,
        caption: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict | None: ...

    async def send_photo_bytes(
        self, chat_id: str | int, png: bytes, caption: str | None = None
    ) -> dict | None:
        """Upload an in-memory image (the branded cards). Adapters override it."""
        raise BotApiError("sendPhoto", "upload not supported")

    async def send_document_bytes(
        self, chat_id: str | int, data: bytes, filename: str, caption: str | None = None,
        content_type: str = "application/pdf",
    ) -> dict | None:
        """Upload an in-memory file (the statement PDF). Adapters override it."""
        raise BotApiError("sendDocument", "upload not supported")

    @abstractmethod
    async def edit_text(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict | None: ...

    @abstractmethod
    async def answer_callback(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None: ...

    @abstractmethod
    async def download_file_ref(
        self, file_ref: str, max_bytes: int | None = None
    ) -> bytes | None:
        """The file's bytes; None when the platform has no file path for it.
        With ``max_bytes`` a larger file raises BotApiError("getFile", "too large")."""

    async def aclose(self) -> None:
        return None


# ---- reply markup builders -------------------------------------------------
def inline_keyboard(rows: Iterable[ButtonRow]) -> dict:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row] for row in rows
        ]
    }


def reply_keyboard(
    rows: Iterable[ButtonRow], one_time: bool = True, resize: bool = True
) -> dict:
    return {
        "keyboard": [[{"text": label} for label, _ in row] for row in rows],
        "one_time_keyboard": one_time,
        "resize_keyboard": resize,
    }


def contact_keyboard(label: str) -> dict:
    return {
        "keyboard": [[{"text": label, "request_contact": True}]],
        "one_time_keyboard": True,
        "resize_keyboard": True,
    }


def remove_keyboard() -> dict:
    return {"remove_keyboard": True}


class HttpBotAdapter(PlatformAdapter):
    """Bot API over HTTPS with httpx (no bot framework)."""

    def __init__(
        self,
        token: str,
        api_base: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 40.0,
        platform: str | None = None,
    ):
        if platform:
            self.platform = platform
        self._token = token or ""
        self._api_base = (api_base or "").rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout

    # ---- HTTP plumbing ---------------------------------------------------
    def _url(self, method: str) -> str:
        # Never expose this string: it contains the token.
        return f"{self._api_base}/bot{self._token}/{method}"

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self._client

    def _network_error(self, method: str, exc: httpx.HTTPError) -> BotApiError:
        """A log-safe description of a transport failure (never the URL)."""
        if isinstance(exc, httpx.TimeoutException):
            return BotApiError(method, "timeout", network=True)
        return BotApiError(method, "network error", network=True)

    async def _call(self, method: str, payload: dict | None = None) -> Any:
        client = await self._http()
        try:
            response = await client.post(self._url(method), json=payload or {})
        except httpx.HTTPError as exc:
            # `from None` keeps the original (URL-bearing) exception out of the traceback.
            raise self._network_error(method, exc) from None
        if response.status_code >= 400:
            raise BotApiError(method, f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise BotApiError(method, "invalid JSON response") from None
        if not isinstance(data, dict) or not data.get("ok", False):
            description = ""
            if isinstance(data, dict):
                description = str(data.get("description", "unknown error"))
            raise BotApiError(method, description or "unknown error")
        return data.get("result")

    # ---- PlatformAdapter -------------------------------------------------
    async def get_updates(
        self, offset: int | None = None, timeout: int = 25, limit: int = 100
    ) -> list[Update]:
        payload: dict[str, Any] = {
            "timeout": int(timeout),
            "limit": int(limit),
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = int(offset)
        result = await self._call("getUpdates", payload)
        return list(result or [])

    async def send_text(
        self, chat_id: str | int, text: str, reply_markup: dict | None = None
    ) -> dict | None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._call("sendMessage", payload)

    async def send_photo(
        self,
        chat_id: str | int,
        photo: str,
        caption: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict | None:
        payload: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption:
            payload["caption"] = caption
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._call("sendPhoto", payload)

    async def send_photo_bytes(
        self, chat_id: str | int, png: bytes, caption: str | None = None
    ) -> dict | None:
        """sendPhoto as a multipart upload (the card never touches the disk)."""
        client = await self._http()
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption[:1024]
        try:
            response = await client.post(
                self._url("sendPhoto"), data=data,
                files={"photo": ("card.png", png, "image/png")},
            )
        except httpx.HTTPError as exc:
            raise self._network_error("sendPhoto", exc) from None
        if response.status_code >= 400:
            raise BotApiError("sendPhoto", f"HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise BotApiError("sendPhoto", "invalid JSON response") from None
        if not isinstance(body, dict) or not body.get("ok", False):
            raise BotApiError("sendPhoto", str((body or {}).get("description", "unknown error")))
        return body.get("result")

    async def send_document_bytes(
        self, chat_id: str | int, data: bytes, filename: str, caption: str | None = None,
        content_type: str = "application/pdf",
    ) -> dict | None:
        """sendDocument as a multipart upload (nothing touches the disk)."""
        client = await self._http()
        form = {"chat_id": str(chat_id)}
        if caption:
            form["caption"] = caption[:1024]
        try:
            response = await client.post(
                self._url("sendDocument"), data=form,
                files={"document": (filename, data, content_type)},
            )
        except httpx.HTTPError as exc:
            raise self._network_error("sendDocument", exc) from None
        if response.status_code >= 400:
            raise BotApiError("sendDocument", f"HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise BotApiError("sendDocument", "invalid JSON response") from None
        if not isinstance(body, dict) or not body.get("ok", False):
            raise BotApiError("sendDocument", str((body or {}).get("description", "unknown error")))
        return body.get("result")

    async def edit_text(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict | None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "text": text,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._call("editMessageText", payload)

    async def answer_callback(
        self, callback_query_id: str, text: str | None = None, show_alert: bool = False
    ) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True
        await self._call("answerCallbackQuery", payload)

    async def download_file_ref(
        self, file_ref: str, max_bytes: int | None = None
    ) -> bytes | None:
        result = await self._call("getFile", {"file_id": file_ref})
        if not isinstance(result, dict):
            return None
        file_path = result.get("file_path")
        if not file_path:
            return None
        declared = result.get("file_size")
        if max_bytes is not None and isinstance(declared, int) and declared > max_bytes:
            raise BotApiError("getFile", "too large")
        client = await self._http()
        url = f"{self._api_base}/file/bot{self._token}/{file_path}"
        chunks: list[bytes] = []
        received = 0
        try:
            # Streamed so an oversized file is cut off instead of held in memory.
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise BotApiError("getFile", f"HTTP {response.status_code}")
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    if max_bytes is not None and received > max_bytes:
                        raise BotApiError("getFile", "too large")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise self._network_error("getFile", exc) from None
        return b"".join(chunks)

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
