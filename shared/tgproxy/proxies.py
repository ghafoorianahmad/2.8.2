"""MTProto proxy links (``tg://proxy`` / ``t.me/proxy``).

Same rules as ``shopapi/app/proxypool.py`` (kept in step by the tests in both
projects); duplicated so this worker runs on its own for the login and the
read-only check, before shopapi is installed on the server.
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9\-.]*[A-Za-z0-9])?$")
_LINK = re.compile(
    r"(?:tg://proxy\?|(?:https?://)?(?:www\.)?(?:t|telegram)\.me/proxy\?)[^\s<>\"')\]]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProxyLink:
    host: str
    port: int
    secret: str          # lowercase hex
    id: int | None = None   # shopapi pool id (None = local/.env proxy)

    @property
    def kind(self) -> str:
        """'ee' = fake-TLS, 'dd' = randomized padding, 'plain' = classic."""
        if self.secret.startswith("ee"):
            return "ee"
        if self.secret.startswith("dd"):
            return "dd"
        return "plain"

    @property
    def secret_bytes(self) -> bytes:
        return bytes.fromhex(self.secret)

    @property
    def tls_domain(self) -> str:
        """The fronting domain of a fake-TLS secret ('' for other kinds)."""
        if self.kind != "ee":
            return ""
        return self.secret_bytes[17:].decode("ascii", "replace")

    def masked(self) -> str:
        """Safe for logs and screens: host:port and the kind, never the secret."""
        return f"{self.host}:{self.port} ({self.kind})"

    def as_link(self) -> str:
        return f"tg://proxy?server={self.host}&port={self.port}&secret={self.secret}"

    def __repr__(self) -> str:  # never show the secret in tracebacks
        return f"ProxyLink({self.masked()}, id={self.id})"


def normalize_secret(raw: str) -> str | None:
    """Hex (any case) or base64/base64url -> lowercase hex; None if invalid."""
    value = (raw or "").strip()
    if not value:
        return None
    if re.fullmatch(r"[0-9a-fA-F]+", value) and len(value) % 2 == 0:
        data = bytes.fromhex(value)
    else:
        padded = value.replace("-", "+").replace("_", "/")
        padded += "=" * (-len(padded) % 4)
        try:
            data = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            return None
    if len(data) < 16:
        return None
    if data[:1] in (b"\xdd",) and len(data) != 17:
        return None
    if data[:1] not in (b"\xdd", b"\xee") and len(data) != 16:
        return None
    return data.hex()


def parse_proxy_link(text: str) -> ProxyLink | None:
    value = (text or "").strip()
    if not value:
        return None
    if value.lower().startswith(("t.me/", "telegram.me/", "www.t.me/")):
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() == "tg":
        if parts.netloc.lower() != "proxy":
            return None
    elif parts.scheme.lower() in ("http", "https"):
        if parts.netloc.lower() not in ("t.me", "www.t.me", "telegram.me") or \
                parts.path.rstrip("/").lower() != "/proxy":
            return None
    else:
        return None
    query = parse_qs(parts.query)
    host = unquote((query.get("server") or [""])[0]).strip()
    port_raw = (query.get("port") or [""])[0].strip()
    secret = normalize_secret(unquote((query.get("secret") or [""])[0]))
    if not host or not _HOST.match(host) or not port_raw.isdigit() or secret is None:
        return None
    port = int(port_raw)
    if not 0 < port < 65536:
        return None
    if secret.startswith("ee") and len(secret) <= 34:
        return None      # fake-TLS needs a domain after the 16-byte key
    return ProxyLink(host.lower(), port, secret)


def extract_links(texts: list[str]) -> list[str]:
    """Raw proxy link strings found in message texts / button / entity URLs."""
    found: list[str] = []
    for text in texts:
        for match in _LINK.finditer(text or ""):
            raw = match.group(0).rstrip(".,;")
            if parse_proxy_link(raw) is not None and raw not in found:
                found.append(raw)
    return found


def from_pool(item: dict) -> ProxyLink | None:
    """A ``/worker/proxies`` entry -> ProxyLink (None if malformed)."""
    try:
        secret = normalize_secret(str(item["secret"]))
        if secret is None:
            return None
        return ProxyLink(str(item["host"]).lower(), int(item["port"]), secret, int(item["id"]))
    except (KeyError, TypeError, ValueError):
        return None
