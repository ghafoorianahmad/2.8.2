"""Fake Telethon client and fake shopapi (no network)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx


@dataclass
class FakeFile:
    mime_type: str = "application/pdf"
    size: int = 100
    name: str = "list.pdf"


def fake_message(mid: int, *, text: str = "", pdf: bytes | None = None, image: bool = False,
                 urls: list[str] | None = None, button_urls: list[str] | None = None,
                 name: str = "list.pdf"):
    msg = SimpleNamespace(id=mid, date=datetime(2026, 10, 12, 8, mid % 60, tzinfo=timezone.utc),
                          message=text, entities=None, reply_markup=None, document=None, file=None,
                          payload=None)
    if urls:
        msg.entities = [SimpleNamespace(url=u) for u in urls]
    if button_urls:
        msg.reply_markup = SimpleNamespace(rows=[SimpleNamespace(
            buttons=[SimpleNamespace(url=u) for u in button_urls])])
    if pdf is not None:
        msg.document = object()
        msg.file = FakeFile(size=len(pdf), name=name)
        msg.payload = pdf
    elif image:
        msg.document = object()
        msg.file = FakeFile(mime_type="image/jpeg", name="a.jpg")
        msg.payload = b"\xff\xd8\xff"
    return msg


class FakeTelegram:
    """Shared 'Telegram' state: channels, which proxies work, auth status."""

    def __init__(self):
        self.channels: dict[str, list] = {}
        self.dead_proxies: set[tuple[str, int]] = set()
        self.direct_ok = True
        self.authorized = True
        self.ping_fails = False
        self.clients: list["FakeClient"] = []
        self.calls: list[str] = []
        self.code = "12345"
        self.password = ""

    def factory(self, session, api_id, api_hash, **kwargs):
        client = FakeClient(self, session, api_id, api_hash, kwargs)
        self.clients.append(client)
        return client


class FakeClient:
    """The subset of ``telethon.TelegramClient`` that the gateway uses."""

    def __init__(self, tg: FakeTelegram, session, api_id, api_hash, kwargs):
        self.tg = tg
        self.session_str = session
        self.kwargs = kwargs
        self.connected = False
        self.session = SimpleNamespace(save=lambda: "1FAKE-SESSION-STRING")

    @property
    def proxy(self):
        return self.kwargs.get("proxy")

    async def connect(self):
        proxy = self.proxy
        if proxy is None and not self.tg.direct_ok:
            raise ConnectionError("blocked")
        if proxy is not None and (proxy[0], proxy[1]) in self.tg.dead_proxies:
            raise OSError("proxy down")
        self.connected = True
        self.tg.calls.append(f"connect:{proxy[0] if proxy else 'direct'}:{bool(self.session_str)}")

    async def disconnect(self):
        self.connected = False

    async def is_user_authorized(self):
        return (bool(self.session_str) or self.signed_in) and self.tg.authorized

    # ---- login (scripts/login.py) ----
    signed_in = False

    async def send_code_request(self, phone):
        self.tg.calls.append("send_code")
        return SimpleNamespace(phone_code_hash="HASH")

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
        from telethon.errors import (PasswordHashInvalidError, PhoneCodeInvalidError,
                                     SessionPasswordNeededError)
        if password is not None:
            if password != self.tg.password:
                raise PasswordHashInvalidError(request=None)
            self.signed_in = True
            return
        assert phone_code_hash == "HASH"
        if code != self.tg.code:
            raise PhoneCodeInvalidError(request=None)
        if self.tg.password:
            raise SessionPasswordNeededError(request=None)
        self.signed_in = True

    async def __call__(self, request):
        if self.tg.ping_fails or not self.connected:
            raise ConnectionError("ping failed")
        self.tg.calls.append(type(request).__name__)
        return SimpleNamespace(country="IR")

    async def iter_messages(self, entity, min_id=0, limit=None):
        assert self.connected
        self.tg.calls.append(f"iter:{entity}:{min_id}:{limit}")
        msgs = sorted((m for m in self.tg.channels.get(entity, []) if m.id > min_id),
                      key=lambda m: -m.id)
        for m in msgs[:limit]:
            yield m

    async def download_media(self, message, file=None):
        assert file is bytes
        self.tg.calls.append(f"download:{message.id}")
        return message.payload


@dataclass
class FakeShopApi:
    """The ``/worker/*`` endpoints of shopapi, as an httpx MockTransport."""
    state: dict[str, str] = field(default_factory=dict)
    pool: list[dict] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    pricelists: list[dict] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    down: bool = False
    keys_seen: set[str] = field(default_factory=set)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down")
        self.keys_seen.add(request.headers.get("X-API-Key", ""))
        body = json.loads(request.content) if request.content else None
        path, method = request.url.path, request.method
        if path == "/worker/state" and method == "GET":
            return httpx.Response(200, json=dict(self.state))
        if path == "/worker/state" and method == "PUT":
            self.state[body["key"]] = body["value"]
            return httpx.Response(200, json=body)
        if path == "/worker/proxies":
            return httpx.Response(200, json=self.pool)
        if path == "/worker/proxies/report":
            self.reports.extend(body["results"])
            return httpx.Response(200, json={"recorded": len(body["results"])})
        if path == "/worker/proxies/candidates":
            self.candidates.append(body)
            return httpx.Response(200, json={"added": len(body["links"]), "invalid": 0})
        if path == "/worker/pricelists":
            self.pricelists.append(body)
            return httpx.Response(200, json={"outcome": "imported", "list_id": len(self.pricelists),
                                             "reasons": []})
        if path == "/worker/alerts":
            self.alerts.append(body["kind"])
            return httpx.Response(200, json={"sent": True})
        return httpx.Response(404, json={"detail": "Not Found"})


SECRET16 = "0123456789abcdef0123456789abcdef"


def pool_entry(pid: int, host: str, kind: str = "dd", state: str = "main") -> dict:
    secret = {"dd": "dd" + SECRET16, "plain": SECRET16,
              "ee": "ee" + SECRET16 + b"example.com".hex()}[kind]
    return {"id": pid, "host": host, "port": 443, "secret": secret, "state": state}
