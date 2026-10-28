"""shopapi ``/worker/*`` client (WORKER_API_KEY, loopback only)."""
from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from .config import Settings


class ApiError(Exception):
    """shopapi unreachable or refused the call (message never holds the key)."""


class WorkerApi:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        verify: Any = settings.shopapi_ca_file or True
        self._client = httpx.AsyncClient(
            base_url=settings.shopapi_base_url,
            headers={"X-API-Key": settings.worker_api_key},
            timeout=httpx.Timeout(60.0, connect=10.0),
            verify=verify,
            trust_env=False,          # never send the key through a system proxy
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, body: Any = None) -> Any:
        try:
            resp = await self._client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise ApiError(f"shopapi unreachable ({type(exc).__name__})") from None
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str(resp.json().get("detail", ""))[:200]
            except (ValueError, AttributeError):
                pass
            raise ApiError(f"shopapi {method} {path} -> {resp.status_code} {detail}".rstrip())
        return resp.json() if resp.content else None

    async def get_state(self) -> dict[str, str]:
        return await self._call("GET", "/worker/state")

    async def put_state(self, key: str, value: str) -> None:
        await self._call("PUT", "/worker/state", {"key": key, "value": value})

    async def put_json_state(self, key: str, value: Any) -> None:
        await self.put_state(key, json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    async def proxies(self) -> list[dict]:
        return await self._call("GET", "/worker/proxies")

    async def report(self, results: list[dict]) -> dict:
        return await self._call("POST", "/worker/proxies/report", {"results": results})

    async def candidates(self, links: list[str], source: str, *,
                         tested: list[dict] | None = None,
                         failed: list[str] | None = None) -> dict:
        """v2.9.0: ``tested`` = links that answered our test (with latency), added to
        the pool; ``failed`` = links that did not (kept as retired, never retested)."""
        body: dict = {"links": links, "source": source[:100]}
        if tested is not None:
            body["tested"] = tested
        if failed is not None:
            body["failed"] = failed
        return await self._call("POST", "/worker/proxies/candidates", body)

    async def unknown(self, links: list[str]) -> list[str]:
        """v2.9.0: the links the server has never seen (worth testing)."""
        result = await self._call("POST", "/worker/proxies/unknown", {"links": links})
        return list((result or {}).get("unknown") or [])

    async def post_pricelist(self, data: bytes, *, source_ref: str, posted_at: str | None,
                             latest: bool = False) -> dict:
        """``latest`` (v2.9.1): this is the newest list post that still exists in the
        channel (an edited post, or the one left after the newest was deleted)."""
        body = {
            "data_b64": base64.b64encode(data).decode("ascii"),
            "source_ref": source_ref[:200],
            "posted_at": posted_at,
        }
        if latest:
            body["latest"] = True
        return await self._call("POST", "/worker/pricelists", body)

    async def post_note(self, text: str, *, source_ref: str, posted_at: str | None) -> dict:
        """v2.9.1: a text post of the price channel after the list (a correction
        «اصلاحیه», «فروش بسته», …); shopapi decides what it is."""
        return await self._call("POST", "/worker/pricelist-notes", {
            "text": text[:4000], "source_ref": source_ref[:200], "posted_at": posted_at,
        })

    async def sync_channels(self, channels: list[dict]) -> dict:
        """v2.9.1: the channels the account has joined -> their roles."""
        return await self._call("POST", "/worker/telegram/channels", {"channels": channels})

    async def post_channel_file(self, *, channel: str, title: str, data: bytes = b"",
                                text: str = "", file_name: str = "", source_ref: str = "",
                                posted_at: str | None = None) -> dict:
        """v2.14.0: a post of another price channel (file or text) for «لیست‌های دریافتی»."""
        return await self._call("POST", "/worker/channel-files", {
            "channel": channel[:120], "title": title[:120],
            "data_b64": base64.b64encode(data).decode("ascii") if data else "",
            "text": text[:60_000], "file_name": file_name[:200], "source_ref": source_ref[:200],
            "posted_at": posted_at})

    async def channel_roles(self) -> dict:
        """v2.9.1: {"pricelist": [ref], "proxy": [ref, ...]} chosen in «تنظیمات سرور»."""
        return await self._call("GET", "/worker/telegram/roles") or {}

    async def alert(self, kind: str) -> dict:
        return await self._call("POST", "/worker/alerts", {"kind": kind})
