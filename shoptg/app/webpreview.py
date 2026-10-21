"""Public web preview of a channel (``https://t.me/s/<channel>``), read-only.

v2.9.0: the proxy pool can be filled before the Telegram account is logged in or
while no proxy works yet (first start): the preview page of a public channel is
plain HTML and needs no account. It is often filtered too; then the account
(through a working proxy) is used instead. Only proxy links are taken from the
page; nothing is sent anywhere but a single GET.
"""
from __future__ import annotations

import html
import re
from typing import Callable

import httpx

PREVIEW_URL = "https://t.me/s/{channel}"
MAX_BYTES = 3 * 1024 * 1024
#: href / text forms of proxy links inside the page (HTML-escaped "&amp;")
_HREF = re.compile(r"""(?:tg://proxy\?|https?://(?:www\.)?(?:t|telegram)\.me/proxy\?)[^"'<>\s]+""",
                   re.IGNORECASE)


class PreviewError(Exception):
    """The preview page could not be read (message holds no secrets)."""


def links_in_page(page: str) -> list[str]:
    """Every proxy link in the page, newest post first, without duplicates."""
    found: list[str] = []
    for match in _HREF.finditer(page or ""):
        link = html.unescape(match.group(0)).rstrip(".,;")
        if link not in found:
            found.append(link)
    # the page lists posts oldest first: the newest links are the last ones
    found.reverse()
    return found


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})


async def fetch_links(channel: str, *,
                      client_factory: Callable[[], httpx.AsyncClient] = _default_client) -> list[str]:
    """Proxy links on the channel's public preview page (newest first)."""
    async with client_factory() as client:
        try:
            resp = await client.get(PREVIEW_URL.format(channel=channel))
        except httpx.HTTPError as exc:
            raise PreviewError(f"preview unreachable ({type(exc).__name__})") from None
    if resp.status_code != 200:
        raise PreviewError(f"preview answered {resp.status_code}")
    if len(resp.content) > MAX_BYTES:
        raise PreviewError("preview page too large")
    return links_in_page(resp.text)
