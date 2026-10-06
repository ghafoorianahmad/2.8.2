"""Shared pytest fixtures for ShopAdmin.

No test touches the network: the shopapi client is driven by an
``httpx.MockTransport`` around :class:`FakeShopApi`, and all local storage uses
SQLite files in a temporary folder. Staff accounts and sessions live in the
fake server, exactly as they live in the real one.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest

# Make the project importable when pytest is run from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Never let a stray Qt platform plugin failure break a headless run.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.api_client import ShopApiClient  # noqa: E402
from app.auth import AuthService  # noqa: E402
from app.permissions import Principal  # noqa: E402
from app.store import Store  # noqa: E402

OWNER_PASSWORD = "Secret123"
OWNER_TOKEN = "owner-token"
SERVICE_KEY = "service-key"
TS = "2025-01-01T10:00:00+00:00"


@pytest.fixture(autouse=True)
def _isolated_credentials(tmp_path, monkeypatch):
    """Keep «remember me» tokens out of the real Credential Manager."""
    from app import credentials

    monkeypatch.setenv("SHOPADMIN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(credentials, "keyring_available", lambda: False)
    yield


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(tmp_path / "shopadmin_test.db")
    yield s
    s.close()


@pytest.fixture
def memory_store() -> Store:
    s = Store(":memory:")
    yield s
    s.close()


# --------------------------------------------------------------------------
# fake shopapi
# --------------------------------------------------------------------------
class FakeShopApi:
    """A small in-memory stand-in for shopapi, including staff sign-in."""

    PUBLIC = ("/health", "/auth/status", "/auth/login", "/auth/bootstrap")

    def __init__(self, service_key: str = SERVICE_KEY) -> None:
        self.service_key = service_key
        self.customers: list[dict] = []
        self.orders: list[dict] = []
        self.products: dict[int, dict] = {}
        self.groups: list[dict] = []
        self.persons: dict[str, dict] = {}
        self.write_enabled = True
        self.requests: list[tuple[str, str]] = []
        self.headers_seen: list[dict] = []
        self.force_status: int | None = None
        self.force_detail: object = None
        self.offline = False
        self.staff: dict[int, dict] = {}
        self.tokens: dict[str, int] = {}
        self.events: list[dict] = []
        self.login_bodies: list[dict] = []
        self.tls_fingerprint = ":".join(["AB"] * 32)
        self.server_settings: dict[str, str] = {
            "BANK_ACCOUNT_TEXT": "حساب قدیم", "RESERVE_HOURS": "12",
            "ALLOW_SHARED_PERSON_CODE": "false", "TELEGRAM_TOKEN": "123:secret", "BALE_TOKEN": "",
        }
        self.settings_puts: list[dict] = []
        self.restarts = 0

    # ---- helpers used by tests ------------------------------------------
    def add_staff(self, username: str, password: str = OWNER_PASSWORD, role: str = "operator",
                  full_name: str = "", *, must_change: bool = False, active: bool = True) -> dict:
        staff_id = max(self.staff, default=0) + 1
        row = {"id": staff_id, "username": username, "full_name": full_name or username,
               "role": role, "password": password, "active": active, "locked": False,
               "must_change_password": must_change, "failed": 0,
               "created_at": TS, "last_login_at": None}
        self.staff[staff_id] = row
        return row

    def issue_token(self, username: str, token: str | None = None) -> str:
        row = self.find_staff(username)
        token = token or f"tok-{username}-{len(self.tokens) + 1}"
        self.tokens[token] = row["id"]
        return token

    def find_staff(self, username: str) -> dict | None:
        for row in self.staff.values():
            if row["username"].lower() == str(username).lower():
                return row
        return None

    def add_event(self, kind: str, ref_id: int | None = None) -> dict:
        event = {"id": len(self.events) + 1, "ts": TS, "kind": kind, "ref_id": ref_id,
                 "actor": "bot"}
        self.events.append(event)
        return event

    def add_customer(self, **kwargs) -> dict:
        row = {
            "id": len(self.customers) + 1,
            "platform": "telegram",
            "chat_id": str(1000 + len(self.customers)),
            "name": "مشتری نمونه",
            "phone": "09120000000",
            "status": "pending",
            "person_code": None,
            "created_at": TS,
        }
        row.update(kwargs)
        self.customers.append(row)
        return row

    def add_order(self, **kwargs) -> dict:
        row = {
            "id": len(self.orders) + 1,
            "status": "receipt_uploaded",
            "price_level": 1,
            "total": 250000.0,
            "reserve_until": None,
            "accounting_order_no": None,
            "created_at": TS,
            "items": [
                {"kala_code": 101, "name": "کالای نمونه", "qty": 2.0, "unit_price": 125000.0}
            ],
            "payment_instructions": None,
            "user_name": "مشتری نمونه",
        }
        row.update(kwargs)
        self.orders.append(row)
        return row

    @staticmethod
    def staff_out(row: dict) -> dict:
        return {k: row[k] for k in ("id", "username", "full_name", "role", "active",
                                    "must_change_password", "locked", "created_at",
                                    "last_login_at")}

    # ---- request handler -------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        self.headers_seen.append(dict(request.headers))

        def reply(status: int, payload) -> httpx.Response:
            return httpx.Response(status, json=payload, request=request)

        def detail(status: int, text: str) -> httpx.Response:
            return reply(status, {"detail": text})

        if self.offline:
            raise httpx.ConnectError("offline", request=request)

        if self.force_status is not None:
            status, forced = self.force_status, self.force_detail
            # One-shot: a test that forces one error must not poison the next call.
            self.force_status = None
            self.force_detail = None
            return reply(status, {"detail": forced})

        body = json.loads(request.content or b"{}") if request.content else {}

        # ---- public ------------------------------------------------------
        if path == "/health":
            return reply(200, {"status": "ok"})
        if path == "/auth/status":
            return reply(200, {"bootstrap_required": not self.staff})
        if path == "/auth/bootstrap":
            if request.headers.get("X-API-Key") != self.service_key:
                return detail(401, "Invalid API key")
            if self.staff:
                return detail(409, "Staff accounts already exist")
            row = self.add_staff(body["username"], body["password"], "super_admin",
                                 body.get("full_name", ""))
            return reply(201, self.staff_out(row))
        if path == "/auth/login":
            self.login_bodies.append(body)
            row = self.find_staff(body.get("username", ""))
            if row is None:
                return detail(401, "Invalid username or password")
            if row["locked"]:
                return detail(423, "Account temporarily locked")
            if body.get("password") != row["password"]:
                row["failed"] += 1
                if row["failed"] >= 5:
                    row["locked"] = True
                return detail(401, "Invalid username or password")
            if not row["active"]:
                return detail(403, "Account disabled")
            row["failed"] = 0
            token = self.issue_token(row["username"])
            return reply(200, {"token": token, "expires_at": "2099-01-01T00:00:00+00:00",
                               "user": self.staff_out(row), "permissions": []})

        # ---- everything else needs a staff session ---------------------
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return detail(401, "Sign-in required")
        user = self.staff.get(self.tokens.get(auth[7:], -1))
        if user is None or not user["active"]:
            return detail(401, "Session expired or invalid")
        token = auth[7:]
        is_super = user["role"] == "super_admin"

        if path == "/auth/logout":
            self.tokens.pop(token, None)
            return reply(200, {"ok": True})
        if path == "/auth/me":
            return reply(200, {"user": self.staff_out(user), "permissions": []})
        if path == "/auth/change-password":
            if body.get("current_password") != user["password"]:
                return detail(403, "Current password is wrong")
            user["password"] = body["new_password"]
            user["must_change_password"] = False
            for other in [t for t, uid in self.tokens.items() if uid == user["id"] and t != token]:
                self.tokens.pop(other)
            return reply(200, {"ok": True})

        if user["must_change_password"]:
            return detail(403, "Password change required")

        if path.startswith("/admin/staff") or path == "/admin/audit":
            if not is_super:
                return detail(403, "Not permitted for this account")
            return self._staff_admin(request, path, body, user, reply, detail)

        if path.startswith("/admin/server"):
            if not is_super:
                return detail(403, "Not permitted for this account")
            return self._server_admin(request, path, body, reply, detail)

        if path == "/admin/events":
            after = request.url.params.get("after")
            last = self.events[-1]["id"] if self.events else 0
            if after is None:
                return reply(200, {"last_id": last, "items": []})
            items = [e for e in self.events if e["id"] > int(after)]
            return reply(200, {"last_id": items[-1]["id"] if items else min(int(after), last),
                               "items": items})

        if path == "/admin/system-info":
            return reply(200, {
                "accounting_write_enabled": self.write_enabled,
                "write_allowed_on_host": self.write_enabled,
                "price_level_bot": 1,
                "price_level_site": 1,
                "reserve_hours": 12,
                "max_order_qty": 10000,
                "allow_shared_person_code": False,
                "bank_account_text": None,
            })

        if path == "/admin/users":
            wanted = request.url.params.get("status")
            return reply(200, [c for c in self.customers if not wanted or c["status"] == wanted])

        if path == "/admin/persons/match":
            match = self.persons.get(request.url.params.get("mobile", ""))
            if match is None:
                return detail(404, "No matching person")
            return reply(200, match)

        if path.startswith("/admin/users/") and path.endswith("/approve"):
            user_id = int(path.split("/")[3])
            for customer in self.customers:
                if customer["id"] == user_id:
                    customer["status"] = "approved"
                    customer["person_code"] = body.get("person_code")
                    return reply(200, customer)
            return detail(404, "User not found")

        if path.startswith("/admin/users/") and path.endswith("/reject"):
            user_id = int(path.split("/")[3])
            for customer in self.customers:
                if customer["id"] == user_id:
                    customer["status"] = "rejected"
                    return reply(200, customer)
            return detail(404, "User not found")

        if path == "/admin/orders":
            wanted = request.url.params.get("status") or "receipt_uploaded"
            return reply(200, [o for o in self.orders if o["status"] == wanted])

        if path == "/admin/orders/expire":
            return reply(200, {"expired": 0})

        if path.startswith("/admin/orders/") and path.endswith("/approve-payment"):
            order_id = int(path.split("/")[3])
            for order in self.orders:
                if order["id"] == order_id:
                    if order["status"] != "receipt_uploaded":
                        return detail(409, f"Order in status {order['status']}; cannot approve")
                    order["status"] = "written"
                    order["accounting_order_no"] = 5001
                    return reply(200, order)
            return detail(404, "Order not found")

        if path.startswith("/admin/orders/") and path.endswith("/reject-payment"):
            order_id = int(path.split("/")[3])
            for order in self.orders:
                if order["id"] == order_id:
                    order["status"] = "rejected"
                    return reply(200, order)
            return detail(404, "Order not found")

        if path == "/products":
            query = (request.url.params.get("q") or "").strip()
            group = request.url.params.get("group")
            rows = list(self.products.values())
            if query:
                rows = [p for p in rows if query in p["name"]]
            if group:
                rows = [p for p in rows if str(p.get("group")) == str(group)]
            return reply(200, {"total": len(rows), "page": 1, "page_size": 50, "items": rows})

        if path == "/groups":
            return reply(200, self.groups)

        return detail(404, "Not Found")

    def _server_admin(self, request, path, body, reply, detail):
        if path == "/admin/server/status":
            return reply(200, {
                "version": "2.0.0", "python": "3.12", "started_at": TS, "uptime_seconds": 93784,
                "accounting": {"ok": True, "latency_ms": 12},
                "accounting_server": ".\\SQLEXPRESS", "accounting_database": "hesab5 t",
                "accounting_write_enabled": False, "write_allowed_on_host": False,
                "tls_fingerprint": self.tls_fingerprint, "restart_available": True,
                "settings_editable": True,
                "components": {"bots": {"configured": ["bale"], "platforms": {
                    "bale": {"running": True, "last_ok_at": TS, "consecutive_errors": 0}}}},
                "counts": {"customers_pending": 2, "orders_awaiting_payment": 1,
                           "orders_receipt_uploaded": 3, "staff": len(self.staff)},
            })
        if path == "/admin/server/settings" and request.method == "GET":
            out = {}
            for key, value in self.server_settings.items():
                secret = key.endswith("TOKEN") or key == "PROXY_URL"
                out[key] = {"secret": True, "set": bool(value)} if secret else \
                    {"secret": False, "value": value}
            return reply(200, {"settings": out})
        if path == "/admin/server/settings" and request.method == "PUT":
            values = body.get("values") or {}
            bad = {k: "cannot be changed remotely" for k in values if k not in self.server_settings}
            if "RESERVE_HOURS" in values and not str(values["RESERVE_HOURS"]).isdigit():
                bad["RESERVE_HOURS"] = "must be a whole number between 1 and 168"
            if bad:
                return reply(422, {"detail": {"message": "Invalid settings", "fields": bad}})
            self.settings_puts.append(dict(values))
            self.server_settings.update(values)
            return reply(200, {"ok": True, "restart_required": True})
        if path == "/admin/server/logs":
            return reply(200, {"lines": ["2025-01-01 INFO started", "2025-01-01 INFO ready"]})
        if path == "/admin/server/restart":
            self.restarts += 1
            return reply(200, {"ok": True})
        return detail(404, "Not Found")

    def _staff_admin(self, request, path, body, user, reply, detail):
        parts = path.strip("/").split("/")
        if path == "/admin/audit":
            return reply(200, [])
        if path == "/admin/staff" and request.method == "GET":
            return reply(200, [self.staff_out(r) for r in self.staff.values()])
        if path == "/admin/staff" and request.method == "POST":
            if self.find_staff(body["username"]):
                return detail(409, "Username already exists")
            row = self.add_staff(body["username"], body["password"], body["role"],
                                 body.get("full_name", ""),
                                 must_change=body.get("must_change_password", True))
            return reply(201, self.staff_out(row))
        target = self.staff.get(int(parts[2])) if len(parts) > 2 else None
        if target is None:
            return detail(404, "Staff account not found")
        supers = [r for r in self.staff.values() if r["role"] == "super_admin" and r["active"]
                  and r["id"] != target["id"]]
        if request.method == "PATCH":
            removing = (body.get("role") not in (None, "super_admin")) or body.get("active") is False
            if removing and target["role"] == "super_admin" and not supers:
                return detail(409, "Cannot remove the last super admin")
            for key in ("full_name", "role", "active"):
                if key in body:
                    target[key] = body[key]
            return reply(200, self.staff_out(target))
        if request.method == "DELETE":
            if target["id"] == user["id"]:
                return detail(409, "Cannot delete your own account")
            del self.staff[target["id"]]
            return reply(200, {"ok": True})
        if parts[-1] == "password":
            target["password"] = body["password"]
            target["must_change_password"] = body.get("must_change_password", True)
            return reply(200, self.staff_out(target))
        if parts[-1] == "unlock":
            target["locked"] = False
            target["failed"] = 0
            return reply(200, self.staff_out(target))
        return detail(404, "Not Found")


@pytest.fixture
def fake_api() -> FakeShopApi:
    fake = FakeShopApi()
    fake.add_staff("owner", OWNER_PASSWORD, "super_admin", "مالک فروشگاه")
    fake.issue_token("owner", OWNER_TOKEN)
    return fake


def make_client(fake: FakeShopApi, token: str = OWNER_TOKEN,
                base_url: str = "http://shopapi.test") -> ShopApiClient:
    return ShopApiClient(base_url, token, transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def api(fake_api) -> ShopApiClient:
    client = make_client(fake_api)
    yield client
    client.close()


@pytest.fixture
def auth(store, fake_api) -> AuthService:
    client = make_client(fake_api, token="")
    yield AuthService(store, client)
    client.close()


@pytest.fixture
def super_admin(fake_api) -> Principal:
    row = fake_api.find_staff("owner")
    return Principal(user_id=row["id"], username="owner", full_name=row["full_name"],
                     role="super_admin")


@pytest.fixture
def make_user(fake_api):
    def _make(username="staff", full_name="کارمند", password=OWNER_PASSWORD, role="operator"):
        row = fake_api.add_staff(username, password, role, full_name)
        return Principal(user_id=row["id"], username=username, full_name=full_name, role=role)
    return _make


@pytest.fixture
def seeded_store(store):
    """A configured store, ready for UI-level tests."""
    store.configure_connection("http://shopapi.test")
    store.set_setting("wizard_completed", True)
    return store


@pytest.fixture(scope="session")
def admin_qapp():
    """A themed QApplication with RTL direction, shared by every Qt test."""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from app.ui import theme

    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.apply_theme(app)
    return app


@pytest.fixture
def top_level_windows(admin_qapp):
    """Close every top-level window a test opened, before its store is closed."""
    from PySide6.QtWidgets import QApplication

    yield

    for widget in QApplication.topLevelWidgets():
        try:
            if widget.isVisible():
                widget.close()
        except RuntimeError:
            pass  # the C++ object is already gone
    admin_qapp.processEvents()
