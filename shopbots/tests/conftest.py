"""Test fixtures: fake Bot API and fake shopapi served through httpx.MockTransport.

No real network access, no real tokens (the strings below are clearly fake and
only exist so the tests can assert they never leak into logs).
"""
from __future__ import annotations

import asyncio
import contextlib
import json

import httpx
import pytest

from app.config import Settings
from app.engine import BotEngine
from app.platforms import BaleAdapter, TelegramAdapter
from app.shopapi import ShopApiClient
from app.store import Store

BALE_TOKEN = "TESTTOKEN-BALE-000"
TELEGRAM_TOKEN = "TESTTOKEN-TG-000"
BOT_KEY = "test-bot-key"
ADMIN_KEY = "test-admin-key"
ADMIN_CHAT = "9001"
CUSTOMER_CHAT = "5005"
OTHER_CHAT = "5006"


# ============================ fake Bot API ==================================
class FakeBotApi:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        self.sent: list[dict] = []
        self.photos: list[dict] = []
        self.edited: list[dict] = []
        self.answered: list[dict] = []
        self.fail_methods: set[str] = set()
        self.raise_on: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        payload = {}
        if request.content:
            try:
                payload = json.loads(request.content.decode())
            except ValueError:
                payload = {}
        self.calls.append((method, payload))
        if method in self.raise_on:
            raise httpx.ConnectError("bot api unreachable")
        if method in self.fail_methods:
            return httpx.Response(200, json={"ok": False, "description": "forced failure"})
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return httpx.Response(200, json={"ok": True, "result": updates})
        if method == "sendMessage":
            self.sent.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 100 + len(self.sent)}})
        if method == "sendPhoto":
            self.photos.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 200 + len(self.photos)}})
        if method == "editMessageText":
            self.edited.append(payload)
            return httpx.Response(200, json={"ok": True, "result": True})
        if method == "answerCallbackQuery":
            self.answered.append(payload)
            return httpx.Response(200, json={"ok": True, "result": True})
        if method == "getFile":
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "photos/p.jpg"}})
        return httpx.Response(200, json={"ok": True, "result": True})

    # --- assertions helpers ---
    def texts(self, chat_id=None) -> list[str]:
        return [
            str(p.get("text", ""))
            for p in self.sent
            if chat_id is None or str(p.get("chat_id")) == str(chat_id)
        ]

    def last_text(self, chat_id=None) -> str:
        found = self.texts(chat_id)
        return found[-1] if found else ""

    def edited_texts(self, chat_id=None) -> list[str]:
        return [
            str(p.get("text", ""))
            for p in self.edited
            if chat_id is None or str(p.get("chat_id")) == str(chat_id)
        ]

    def last_text_any(self, chat_id=None) -> str:
        """Last message body for a chat, whether it was sent, edited or a photo caption."""
        latest = ""
        for method, payload in self.calls:
            if method not in ("sendMessage", "editMessageText", "sendPhoto"):
                continue
            if chat_id is not None and str(payload.get("chat_id")) != str(chat_id):
                continue
            latest = str(payload.get("text") or payload.get("caption") or "")
        return latest

    def buttons_for(self, chat_id) -> list[list[tuple[str, str]]]:
        """Inline keyboard of the last message for a chat (sent *or* edited)."""
        result: list[list[tuple[str, str]]] = []
        for method, payload in self.calls:
            if method not in ("sendMessage", "editMessageText", "sendPhoto"):
                continue
            if str(payload.get("chat_id")) != str(chat_id):
                continue
            rows = (payload.get("reply_markup") or {}).get("inline_keyboard")
            if rows:
                result = [
                    [(b.get("text", ""), b.get("callback_data", "")) for b in row] for row in rows
                ]
        return result

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]

    def raw(self) -> str:
        return json.dumps(
            {"calls": self.calls, "photos": self.photos, "edited": self.edited, "answered": self.answered},
            ensure_ascii=False,
            default=str,
        )


# ============================ fake shopapi ==================================
class FakeShopApi:
    def __init__(self):
        self.users: dict[tuple[str, str], dict] = {}
        self.orders: dict[int, dict] = {}
        self.groups = [{"code": 1, "name": "گروه یک"}, {"code": 2, "name": "گروه دو"}]
        self.products = [
            {"code": 101, "name": "کالای الف", "group": 1, "unit_price": 1000.0,
             "available_qty": 10.0, "image": None},
            {"code": 102, "name": "کالای ب", "group": 1, "unit_price": 2000.0,
             "available_qty": 5.0, "image": None},
            {"code": 103, "name": "کالای ج", "group": 2, "unit_price": 3000.0,
             "available_qty": 0.0, "image": None},
            {"code": 104, "name": "کالای د", "group": 2, "unit_price": 4000.0,
             "available_qty": 7.0, "image": None},
        ]
        self.requests: list[tuple[str, str, str]] = []
        self.down = False
        self.person_match: dict | None = None
        self.approve_payment_fails = False
        #: ACCOUNTING_WRITE_ENABLED=false: approve-payment rehearses and keeps the status
        self.dry_run_writes = False
        self.events: list[dict] = []
        self._next_user = 1
        self._next_order = 1

    # --- helpers ---
    @staticmethod
    def _ok(data) -> httpx.Response:
        return httpx.Response(200, json=data)

    @staticmethod
    def _err(status: int, detail: str) -> httpx.Response:
        return httpx.Response(status, json={"detail": detail})

    def add_user(self, platform: str, chat_id, *, name="علی", phone="09121234567",
                 status="pending", person_code=None) -> dict:
        user = {
            "id": self._next_user, "platform": platform, "chat_id": str(chat_id),
            "name": name, "phone": phone, "status": status,
            "person_code": person_code, "created_at": "t",
        }
        self._next_user += 1
        self.users[(platform, str(chat_id))] = user
        return user

    def add_event(self, kind: str, ref_id: int) -> None:
        self.events.append({"id": len(self.events) + 1, "ts": "t", "kind": kind,
                            "ref_id": ref_id, "actor": "staff:admin"})

    def _order_public(self, order: dict) -> dict:
        return {k: v for k, v in order.items() if not k.startswith("_")}

    # --- request handler ---
    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("shopapi unreachable")
        path = request.url.path
        method = request.method.upper()
        key = request.headers.get("X-API-Key", "")
        self.requests.append((method, path, key))
        body = {}
        if request.content:
            try:
                body = json.loads(request.content.decode())
            except ValueError:
                body = {}
        params = dict(request.url.params)

        # API key separation: admin routes need the admin key, the rest the bot key
        if path.startswith("/admin/"):
            if key != ADMIN_KEY:
                return self._err(401, "Invalid API key")
        elif path != "/health" and key != BOT_KEY:
            return self._err(401, "Invalid API key")

        if method == "GET" and path == "/health":
            return self._ok({"status": "ok"})

        if method == "GET" and path == "/groups":
            return self._ok(self.groups)

        if method == "GET" and path == "/products":
            items = self.products
            group = params.get("group")
            if group is not None:
                items = [p for p in items if str(p["group"]) == str(group)]
            q = params.get("q")
            if q:
                items = [p for p in items if q in p["name"]]
            if str(params.get("in_stock", "true")).lower() != "false":
                items = [p for p in items if p["available_qty"] > 0]
            page = int(params.get("page", 1))
            page_size = int(params.get("page_size", 5))
            start = (page - 1) * page_size
            return self._ok({
                "total": len(items), "page": page, "page_size": page_size,
                "items": items[start:start + page_size],
            })

        if method == "POST" and path == "/users/register":
            platform = str(body.get("platform"))
            chat_id = str(body.get("chat_id"))
            existing = self.users.get((platform, chat_id))
            if existing:
                return self._ok(existing)
            return self._ok(self.add_user(platform, chat_id, name=body.get("name", ""),
                                          phone=body.get("phone", "")))

        if method == "GET" and path.startswith("/admin/users"):
            status_filter = params.get("status")
            users = [u for u in self.users.values() if not status_filter or u["status"] == status_filter]
            return self._ok(users)

        if method == "POST" and path.startswith("/admin/users/") and path.endswith("/approve"):
            user_id = int(path.split("/")[3])
            user = next((u for u in self.users.values() if u["id"] == user_id), None)
            if user is None:
                return self._err(404, "User not found")
            user["status"] = "approved"
            user["person_code"] = body.get("person_code")
            return self._ok(user)

        if method == "POST" and path.startswith("/admin/users/") and path.endswith("/reject"):
            user_id = int(path.split("/")[3])
            user = next((u for u in self.users.values() if u["id"] == user_id), None)
            if user is None:
                return self._err(404, "User not found")
            user["status"] = "rejected"
            return self._ok(user)

        if method == "GET" and path == "/admin/persons/match":
            if self.person_match is None:
                return self._err(404, "No matching person")
            return self._ok(self.person_match)

        if method == "GET" and path == "/admin/events":
            last = self.events[-1]["id"] if self.events else 0
            if "after" not in params:
                return self._ok({"last_id": last, "items": []})
            after = int(params["after"])
            items = [e for e in self.events if e["id"] > after]
            return self._ok({"last_id": items[-1]["id"] if items else min(after, last),
                             "items": items})

        if method == "GET" and path == "/admin/orders":
            status_filter = params.get("status")
            orders = [o for o in self.orders.values() if not status_filter or o["status"] == status_filter]
            return self._ok([self._order_public(o) for o in orders])

        if method == "POST" and path.startswith("/admin/orders/") and path.endswith("/approve-payment"):
            order_id = int(path.split("/")[3])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            if self.approve_payment_fails:
                return self._err(409, "Insufficient stock for product 101")
            if self.dry_run_writes:
                return self._ok(self._order_public(order))
            order["status"] = "written"
            order["accounting_order_no"] = 777
            return self._ok(self._order_public(order))

        if method == "POST" and path.startswith("/admin/orders/") and path.endswith("/reject-payment"):
            order_id = int(path.split("/")[3])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            order["status"] = "rejected"
            return self._ok(self._order_public(order))

        if method == "GET" and path.startswith("/users/") and path.endswith("/orders"):
            parts = path.split("/")
            platform, chat_id = parts[2], parts[3]
            user = self.users.get((platform, chat_id))
            if user is None:
                return self._err(404, "User not found")
            mine = [o for o in self.orders.values()
                    if o["_platform"] == platform and o["_chat_id"] == chat_id]
            return self._ok([self._order_public(o) for o in mine])

        if method == "GET" and path.startswith("/users/"):
            parts = path.split("/")
            platform, chat_id = parts[2], parts[3]
            user = self.users.get((platform, chat_id))
            if user is None:
                return self._err(404, "User not found")
            return self._ok(user)

        if method == "POST" and path == "/orders":
            platform = str(body.get("platform"))
            chat_id = str(body.get("chat_id"))
            user = self.users.get((platform, chat_id))
            if user is None:
                return self._err(404, "User not found")
            if user["status"] != "approved":
                return self._err(403, "User is not approved")
            items = []
            total = 0.0
            for line in body.get("items", []):
                product = next((p for p in self.products if p["code"] == line["kala_code"]), None)
                if product is None or product["unit_price"] <= 0:
                    return self._err(422, f"Product {line['kala_code']} is not available for sale")
                if product["available_qty"] < line["qty"]:
                    return self._err(409, f"Insufficient stock for product {line['kala_code']}")
                items.append({
                    "kala_code": line["kala_code"], "name": product["name"],
                    "qty": line["qty"], "unit_price": product["unit_price"],
                })
                total += float(line["qty"]) * float(product["unit_price"])
            order_id = self._next_order
            self._next_order += 1
            order = {
                "id": order_id, "status": "awaiting_payment", "price_level": 3, "total": total,
                "reserve_until": "t+12h", "accounting_order_no": None, "created_at": "t",
                "items": items, "payment_instructions": "واریز به کارت 1234",
                "_platform": platform, "_chat_id": chat_id,
            }
            self.orders[order_id] = order
            return self._ok(self._order_public(order))

        if method == "POST" and path.startswith("/orders/") and path.endswith("/receipt"):
            order_id = int(path.split("/")[2])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            platform = params.get("platform")
            chat_id = params.get("chat_id")
            if (not platform or not chat_id or order["_platform"] != platform
                    or order["_chat_id"] != str(chat_id)):
                return self._err(404, "Order not found")
            if order["status"] != "awaiting_payment":
                return self._err(409, f"Order in status {order['status']}")
            order["status"] = "receipt_uploaded"
            order["receipt_ref"] = body.get("receipt_ref")
            return self._ok(self._order_public(order))

        if method == "GET" and path.startswith("/orders/"):
            order_id = int(path.split("/")[2])
            order = self.orders.get(order_id)
            if order is None:
                return self._err(404, "Order not found")
            platform = params.get("platform")
            chat_id = params.get("chat_id")
            if platform and chat_id:
                if order["_platform"] != platform or order["_chat_id"] != str(chat_id):
                    return self._err(404, "Order not found")
            return self._ok(self._order_public(order))

        return self._err(404, f"no route for {method} {path}")


# ============================ update builders ===============================
def message_update(update_id: int, chat_id, *, text=None, contact=None, photo=None,
                   chat_type="private") -> dict:
    message = {"message_id": update_id, "chat": {"id": chat_id, "type": chat_type}}
    if text is not None:
        message["text"] = text
    if contact is not None:
        message["contact"] = contact
    if photo is not None:
        message["photo"] = photo
    return {"update_id": update_id, "message": message}


def callback_update(update_id: int, chat_id, data, *, chat_type="private") -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb-{update_id}",
            "data": data,
            "message": {"message_id": update_id, "chat": {"id": chat_id, "type": chat_type}},
        },
    }


async def push_message(engine, platform, update_id, chat_id, **kwargs) -> bool:
    return await engine.handle_update(platform, message_update(update_id, chat_id, **kwargs))


async def push_callback(engine, platform, update_id, chat_id, data, **kwargs) -> bool:
    return await engine.handle_update(platform, callback_update(update_id, chat_id, data, **kwargs))


# ============================ fixtures ======================================
@pytest.fixture
def settings():
    return Settings(
        shopapi_base_url="http://shopapi.test",
        bot_api_key=BOT_KEY,
        admin_api_key=ADMIN_KEY,
        bale_token=BALE_TOKEN,
        telegram_token=TELEGRAM_TOKEN,
        bale_api_base="https://bale.test",
        telegram_api_base="https://telegram.test",
        admin_chat_ids=(f"bale:{ADMIN_CHAT}", f"telegram:{ADMIN_CHAT}"),
        sqlite_path=":memory:",
        poll_timeout=1,
        admin_sweep_seconds=30,
        rate_limit_messages=20,
        rate_limit_window=60.0,
        product_page_size=2,
    )


@pytest.fixture
def bot_apis():
    return {"bale": FakeBotApi(), "telegram": FakeBotApi()}


@pytest.fixture
def shopapi():
    return FakeShopApi()


@pytest.fixture
def store():
    return Store(":memory:")


@contextlib.asynccontextmanager
async def bot_env(settings, store, shopapi, bot_apis, rate_limiter=None):
    clients: list[httpx.AsyncClient] = []
    adapters = {}
    for platform, adapter_cls, base, token in (
        ("bale", BaleAdapter, settings.bale_api_base, settings.bale_token),
        ("telegram", TelegramAdapter, settings.telegram_api_base, settings.telegram_token),
    ):
        client = httpx.AsyncClient(transport=httpx.MockTransport(bot_apis[platform].handler))
        clients.append(client)
        adapters[platform] = adapter_cls(token=token, api_base=base, client=client)
    api_client = httpx.AsyncClient(transport=httpx.MockTransport(shopapi.handler))
    clients.append(api_client)
    api = ShopApiClient(settings, client=api_client)
    engine = BotEngine(settings, store, api, adapters, rate_limiter=rate_limiter)
    try:
        yield engine, adapters, api
    finally:
        for client in clients:
            await client.aclose()


@pytest.fixture
def env(settings, store, shopapi, bot_apis):
    """Run one async scenario with a fully wired engine inside a single event loop."""

    def _run(scenario, rate_limiter=None):
        async def wrapper():
            async with bot_env(settings, store, shopapi, bot_apis, rate_limiter) as ctx:
                return await scenario(*ctx)

        return asyncio.run(wrapper())

    return _run
