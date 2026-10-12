"""Telethon connection options for an MTProto proxy."""
from __future__ import annotations

from .proxies import ProxyLink


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
