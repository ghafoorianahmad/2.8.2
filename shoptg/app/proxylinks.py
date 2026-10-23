"""Every proxy-link format of the proxy channels -> canonical ``tg://proxy`` links (v2.9.1).

@ProxyMTProto (checked 2026-10-23) posts each proxy as plain text
("Server: … / Port: … / Secret: …") with inline «Connect» buttons whose URLs are
``https://t.me/proxy?server=…&port=…&secret=…`` or ``https://t.me/webproxy?server=…
&secret=…`` (no port = 443). Hosts sometimes end with a dot, secrets come as hex or
base64url, and links in HTML / entities may be escaped. Everything found is turned
into ``tg://proxy?server=<host>&port=<port>&secret=<hex>``, which the shared parser
(``tgproxy``) and shopapi both accept, so only working canonical links travel on.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlsplit

from tgproxy import normalize_secret, parse_proxy_link

DEFAULT_PORT = 443

#: tg://proxy, t.me/proxy, t.me/webproxy (also telegram.me / telegram.dog, with or
#: without the scheme), up to the first character that cannot be part of a URL
_URL = re.compile(
    r"(?:tg://(?:proxy|webproxy)/?\?|(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/"
    r"(?:proxy|webproxy)/?\?)[^\s<>\"'\)\]]+",
    re.IGNORECASE,
)
#: "Server: x" / "Port: 443" / "Secret: ee…" (English or Persian labels, `code` marks)
_SERVER = re.compile(r"(?:server|host|سرور|آدرس)\s*[:：=]\s*[`'\"]?([A-Za-z0-9][A-Za-z0-9.\-]*)",
                     re.IGNORECASE)
_PORT = re.compile(r"(?:port|پورت)\s*[:：=]\s*[`'\"]?(\d{2,5})", re.IGNORECASE)
_SECRET = re.compile(r"(?:secret|سکرت|سیکرت)\s*[:：=]\s*[`'\"]?([A-Za-z0-9+/=_\-]{22,})",
                     re.IGNORECASE)


def canonical(host: str, port: str | int | None, secret: str) -> str | None:
    """A canonical ``tg://proxy`` link, or None when any part is invalid."""
    host = unquote(str(host or "")).strip().rstrip(".").lower()
    port_text = str(port or "").strip() or str(DEFAULT_PORT)
    hex_secret = normalize_secret(unquote(str(secret or "")).strip())
    if not host or not port_text.isdigit() or hex_secret is None:
        return None
    link = parse_proxy_link(f"tg://proxy?server={host}&port={int(port_text)}&secret={hex_secret}")
    return link.as_link() if link is not None else None


def from_url(raw: str) -> str | None:
    """One proxy URL in any accepted form -> canonical link (None if not a proxy)."""
    value = html.unescape(str(raw or "")).strip().rstrip(".,;")
    if not value:
        return None
    if not re.match(r"^[a-z]+://", value, re.IGNORECASE):
        value = "https://" + value
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme == "tg":
        if parts.netloc.lower() not in ("proxy", "webproxy"):
            return None
    elif scheme in ("http", "https"):
        if parts.netloc.lower() not in ("t.me", "www.t.me", "telegram.me", "telegram.dog") or \
                parts.path.rstrip("/").lower() not in ("/proxy", "/webproxy"):
            return None
    else:
        return None
    query = parse_qs(parts.query)
    return canonical((query.get("server") or [""])[0], (query.get("port") or [""])[0],
                     (query.get("secret") or [""])[0])


def from_text_blocks(text: str) -> list[str]:
    """Proxies written out as Server / Port / Secret lines (one or more per post)."""
    found: list[str] = []
    servers = list(_SERVER.finditer(text or ""))
    for index, match in enumerate(servers):
        end = servers[index + 1].start() if index + 1 < len(servers) else len(text)
        block = text[match.end():end]
        secret = _SECRET.search(block)
        if secret is None:
            continue
        port = _PORT.search(block)
        link = canonical(match.group(1), port.group(1) if port else "", secret.group(1))
        if link and link not in found:
            found.append(link)
    return found


def extract_all(texts: list[str]) -> list[str]:
    """Canonical proxy links in message texts, entity URLs and button URLs (in order,
    without duplicates)."""
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        candidates = [from_url(m.group(0)) for m in _URL.finditer(text)]
        candidates += from_text_blocks(_URL.sub(" ", text))
        for link in candidates:
            if link and link not in found:
                found.append(link)
    return found
