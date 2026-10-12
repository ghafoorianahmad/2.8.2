"""The MTProto proxy pool as the Telegram bot sees it.

Ranking is done by shopapi (``/worker/proxies``: historical stability, probation,
see REQUIREMENTS §6); this module only reads that ranking and reports what the
bot's own connection attempts found, with the same endpoints and result format
as shoptg. The link parsing and the fake-TLS connector are the shared
``tgproxy`` package. Keys are never logged.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from tgproxy import ProxyLink, from_pool, parse_proxy_link

logger = logging.getLogger("shopbots.tgpool")


class ProxyPool:
    """Candidates best first: pool ranking, the local ``TG_PROXY`` links, then
    direct (``None``) when allowed."""

    def __init__(
        self,
        *,
        base_url: str,
        worker_api_key: str,
        ca_file: str = "",
        local_proxies: tuple[str, ...] = (),
        allow_direct: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._local = local_proxies
        self._allow_direct = allow_direct
        self._client: httpx.AsyncClient | None = None
        if worker_api_key:
            verify: Any = ca_file or True
            self._client = httpx.AsyncClient(
                base_url=base_url.rstrip("/"),
                headers={"X-API-Key": worker_api_key},
                timeout=httpx.Timeout(30.0, connect=10.0),
                verify=verify,
                trust_env=False,          # never send the key through a system proxy
                transport=transport,
            )
        else:
            logger.warning("WORKER_API_KEY is not set - the shared proxy pool is not used")
        self._warned = False

    async def _call(self, method: str, path: str, body: Any = None) -> Any:
        assert self._client is not None
        try:
            response = await self._client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise ConnectionError(f"shopapi unreachable ({type(exc).__name__})") from None
        if response.status_code >= 400:
            raise ConnectionError(f"shopapi {method} {path} -> {response.status_code}")
        return response.json() if response.content else None

    async def candidates(self) -> list[ProxyLink | None]:
        links: list[ProxyLink | None] = []
        if self._client is not None:
            try:
                for item in await self._call("GET", "/worker/proxies"):
                    link = from_pool(item)
                    if link is not None:
                        links.append(link)
                self._warned = False
            except (ConnectionError, ValueError, TypeError) as exc:
                if not self._warned:
                    logger.warning("proxy pool unavailable: %s", exc)
                    self._warned = True
        known = {(p.host, p.port, p.secret) for p in links if p}
        for raw in self._local:
            link = parse_proxy_link(raw)
            if link is not None and (link.host, link.port, link.secret) not in known:
                links.append(link)
        if self._allow_direct:
            links.append(None)
        return links

    async def report(self, results: list[dict]) -> None:
        """``[{"id": pool id, "ok": bool, "latency_ms": int}]``; local/direct entries have no id."""
        results = [r for r in results if r.get("id") is not None]
        if not results or self._client is None:
            return
        try:
            await self._call("POST", "/worker/proxies/report", {"results": results})
        except ConnectionError as exc:
            logger.warning("proxy report failed: %s", exc)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
