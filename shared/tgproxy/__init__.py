"""Shared Telegram MTProto proxy support (used by shoptg and shopbots).

``proxies``  - tg://proxy link parsing (no third-party imports)
``faketls``  - fake-TLS ("ee" secret) connection for Telethon 1.x
``connection`` - ``connection_for(link)``: TelegramClient kwargs for a proxy

Only ``proxies`` is imported eagerly; Telethon is imported when it is needed.
"""
from .proxies import ProxyLink, extract_links, from_pool, normalize_secret, parse_proxy_link

__all__ = ["ProxyLink", "extract_links", "from_pool", "normalize_secret", "parse_proxy_link"]
