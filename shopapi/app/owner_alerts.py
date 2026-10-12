"""Direct Bale messages to the owner, for health alerts only (REQUIREMENTS §8).

Normal owner alerts (new order, pending customer, price list) travel through the
bot. Health alerts must also arrive when the bot itself is down, so the server
sends them here with the same ``BALE_TOKEN`` / ``ADMIN_CHAT_IDS`` from ``.env``.
Used by the health monitor and by the ShopSystem supervisor.

Never logs the token, a URL that contains it, a chat id or the message text.
"""
from __future__ import annotations

import logging
import os
from typing import Mapping

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BALE_API_BASE = "https://tapi.bale.ai"


def owner_chat_ids(raw: str | None = None) -> list[str]:
    """Bale chat ids from ``ADMIN_CHAT_IDS`` (``123`` or ``bale:123``)."""
    value = os.environ.get("ADMIN_CHAT_IDS", "") if raw is None else (raw or "")
    ids: list[str] = []
    for part in value.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            platform, _, part = part.partition(":")
            if platform.strip().lower() != "bale":
                continue  # leftover telegram:... entries are ignored
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.append(part)
    return ids


def configured(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return bool((env.get("BALE_TOKEN") or "").strip()
                and owner_chat_ids(env.get("ADMIN_CHAT_IDS") or ""))


def send_owner_alert(text: str, *, client: httpx.Client | None = None,
                     timeout: float = 15.0, env: Mapping[str, str] | None = None) -> int:
    """Send ``text`` to every owner chat; return how many were delivered.

    ``env`` defaults to the process environment; the supervisor passes the
    values it read from ``.env`` without putting them into its environment.
    """
    env = os.environ if env is None else env
    token = (env.get("BALE_TOKEN") or "").strip()
    chats = owner_chat_ids(env.get("ADMIN_CHAT_IDS") or "")
    if not token or not chats:
        return 0
    base = ((env.get("BALE_API_BASE") or "").strip() or DEFAULT_BALE_API_BASE).rstrip("/")
    url = f"{base}/bot{token}/sendMessage"
    own = client is None
    http = client or httpx.Client(timeout=timeout, trust_env=False)
    sent = 0
    try:
        for chat in chats:
            try:
                response = http.post(url, json={"chat_id": chat, "text": text})
                if response.status_code == 200:
                    sent += 1
                else:
                    logger.warning("owner alert not delivered (HTTP %s)", response.status_code)
            except httpx.HTTPError as exc:
                logger.warning("owner alert not delivered (%s)", type(exc).__name__)
    finally:
        if own:
            http.close()
    return sent
