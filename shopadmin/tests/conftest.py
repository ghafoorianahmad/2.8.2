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
            "BANK_ACCOUNT_TEXT": "حساب قدیم", "RECEIPT_DEADLINE_MINUTES": "30",
            "ALLOW_SHARED_PERSON_CODE": "false", "BALE_TOKEN": "123:secret",
        }
        self.settings_puts: list[dict] = []
        self.restarts = 0
        #: order id -> stored receipt image
        self.receipts: dict[int, bytes] = {}
        self.shop_closed = False
        self.sales_reason = "list"
        self.sales_actions: list[str] = []
        self.approve_bodies: list[dict] = []
        # ---- Phase 3: distributor price list / mapping / proxies ----
        self.pricelists: list[dict] = []
        self.price_rows: list[dict] = []
        self.price_uploads: list[dict] = []
        self.upload_outcome = "active"
        self.proxies: list[dict] = []
        self.proxy_adds: list[dict] = []
        # ---- Phase 6b: site catalog models ----
        self.catalog_models: list[dict] = []
        self.catalog_items: list[dict] = []
        self.catalog_imports: list[list] = []
        self.catalog_checks = 0
        self.catalog_last_check: dict | None = None
        # ---- v2.4.0: forgot password ----
        self.pw_requests: dict[int, dict] = {}
        # ---- v2.6.0: product groups, item requests, payment card ----
        self.product_groups: list[dict] = []
        self.group_puts: list[dict] = []
        self.item_requests: list[dict] = []
        self.payment_ready = True
        self.catalog_ready = True
        self.phone_groups_ready = True
        # ---- v2.6.1: replies to item requests ----
        self.item_request_messages: dict[int, list[dict]] = {}
        self.message_fail: str = ""
        # ---- v2.8.0: ownership, timeline, activity, archive, purchase requests ----
        self.timelines: dict[tuple[str, int], list[dict]] = {}
        self.activity_rows: list[dict] = []
        self.activity_params: list[dict] = []
        self.archived_orders: list[dict] = []
        self.archived_requests: list[dict] = []
        self.assigned: list[tuple[str, int, int]] = []
        self.stock_confirms: list[dict] = []
        self.suggestions: dict[str, dict] = {}

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
        out = {k: row[k] for k in ("id", "username", "full_name", "role", "active",
                                   "must_change_password", "locked", "created_at",
                                   "last_login_at")}
        # v2.7.0: a row may carry the server's effective permissions and ticks
        for key in ("permissions", "extra_permissions", "removed_permissions"):
            if key in row:
                out[key] = row[key]
        return out

    # ---- request handler -------------------------------------------------
    def _sales_state(self) -> dict:
        reason = self.sales_reason if self.shop_closed or self.sales_reason == "manual_open" \
            else "list"
        if self.shop_closed and reason in ("list", "manual_open"):
            reason = "manual_close"
        return {"closed": self.shop_closed, "sales_open": not self.shop_closed,
                "reason": reason, "message_fa": "فروش گوشی بسته است." if self.shop_closed
                else "فروش گوشی باز است.", "until": None, "list_date": "1405/07/22",
                "list_slot": "morning", "override_by": "", "receipt_deadline_minutes": 30,
                "payment_ready": self.payment_ready, "catalog_ready": self.catalog_ready,
                "phone_groups_ready": self.phone_groups_ready}

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

        if path == "/auth/forgot":
            row = self.find_staff(body.get("username", ""))
            rid = 10 ** 9 + len(self.pw_requests)
            token = f"secret-{len(self.pw_requests) + 1}"
            if row is not None and row["active"]:
                rid = len(self.pw_requests) + 1
                self.pw_requests[rid] = {"id": rid, "staff_id": row["id"], "token": token,
                                         "status": "pending", "created_at": TS}
            return reply(200, {"request_id": rid, "token": token})
        if path in ("/auth/forgot/status", "/auth/forgot/complete"):
            req = self.pw_requests.get(body.get("request_id"))
            if req is None or req["token"] != body.get("token"):
                if path.endswith("status"):
                    return reply(200, {"status": "pending"})
                return detail(403, "Request is not approved")
            if path.endswith("status"):
                return reply(200, {"status": req["status"]})
            if req["status"] != "approved":
                return detail(403, "Request is not approved")
            owner = self.staff[req["staff_id"]]
            if body["new_password"] == owner["password"]:
                return detail(422, "New password must differ from the old one")
            owner["password"] = body["new_password"]
            owner["must_change_password"] = False
            for t in [t for t, uid in self.tokens.items() if uid == owner["id"]]:
                self.tokens.pop(t)
            req["status"] = "used"
            return reply(200, {"ok": True})
        if path == "/auth/console-login":
            if request.headers.get("X-API-Key") != self.service_key:
                return detail(403, "Not permitted for this account")
            row = next((r for r in self.staff.values()
                        if r["role"] == "super_admin" and r["active"]), None)
            if row is None:
                return detail(409, "No super admin exists yet")
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

        if path.startswith("/admin/password-requests"):
            if user["role"] not in ("super_admin", "admin"):
                return detail(403, "Not permitted for this account")
            if request.method == "GET":
                return reply(200, [
                    {"id": r["id"], "staff_id": r["staff_id"],
                     "username": self.staff[r["staff_id"]]["username"],
                     "full_name": self.staff[r["staff_id"]]["full_name"],
                     "role": self.staff[r["staff_id"]]["role"],
                     "created_at": TS, "expires_at": TS}
                    for r in self.pw_requests.values() if r["status"] == "pending"])
            req = self.pw_requests.get(int(path.split("/")[3]))
            if req is None or req["status"] != "pending":
                return detail(404, "No such pending request")
            req["status"] = "approved" if path.endswith("/approve") else "rejected"
            return reply(200, {"ok": True})

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

        handled = self._v280(request, path, body, user, reply, detail)
        if handled is not None:
            return handled

        if path == "/admin/system-info":
            return reply(200, {
                "accounting_write_enabled": self.write_enabled,
                "write_allowed_on_host": self.write_enabled,
                "price_level_bot": 1,
                "price_level_site": 1,
                "receipt_deadline_minutes": 30,
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
            self.approve_bodies.append(body)
            for customer in self.customers:
                if customer["id"] == user_id:
                    code = body.get("person_code")
                    if code is None:
                        # create a person (recipe 5.1): only when writes are enabled
                        if not self.write_enabled:
                            return detail(
                                409, "Accounting writes are disabled; the person was not created")
                        code = 9000 + user_id
                        customer["name"] = f"{body.get('first_name') or ''} {body['last_name']}".strip()
                    customer["status"] = "approved"
                    customer["person_code"] = code
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
            mine = request.url.params.get("mine") == "true"
            return reply(200, [o for o in self.orders if o["status"] == wanted
                               and (not mine or o.get("owned_by_me"))])

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

        if path == "/admin/product-groups":
            if request.method == "PUT":
                if user["role"] not in ("super_admin", "admin"):
                    return detail(403, "Not permitted for this account")
                self.group_puts.append(body)
                by = {g["code"]: g for g in body.get("groups", [])}
                for group in self.product_groups:
                    if group["code"] in by:
                        group.update(show_in_bot=by[group["code"]]["show_in_bot"],
                                     is_phone=by[group["code"]]["is_phone"],
                                     price_on_inquiry=by[group["code"]].get("price_on_inquiry",
                                                                            False))
            return reply(200, self.product_groups)

        if path == "/admin/item-requests" and request.method == "GET":
            status = request.url.params.get("status")
            kind = request.url.params.get("kind")
            return reply(200, [r for r in self.item_requests
                               if (not status or r["status"] == status)
                               and (not kind or r.get("kind", "unavailable") == kind)])

        if path.startswith("/admin/item-requests/") and path.endswith("/messages"):
            request_id = int(path.split("/")[3])
            if not any(r["id"] == request_id for r in self.item_requests):
                return detail(404, "Request not found")
            rows = self.item_request_messages.setdefault(request_id, [])
            if request.method == "POST":
                if self.message_fail:
                    return detail(409, self.message_fail)
                text = str(body.get("text") or "").strip()
                if not text:
                    return detail(422, "Message is empty")
                row = {"id": sum(len(v) for v in self.item_request_messages.values()) + 1,
                       "request_id": request_id, "text": text, "status": "pending", "error": "",
                       "created_at": "2026-10-15T08:00:05+00:00",
                       "created_by": user["username"], "sent_at": None}
                rows.append(row)
                return reply(201, row)
            return reply(200, rows)

        if path.startswith("/admin/item-requests/") and path.endswith("/note"):
            request_id = int(path.split("/")[3])
            row = next((r for r in self.item_requests if r["id"] == request_id), None)
            if row is None:
                return detail(404, "Request not found")
            row.update(admin_note=body.get("note", ""), note_at="2026-10-15T08:00:00+00:00",
                       note_by=user["username"])
            return reply(200, row)

        if path.startswith("/admin/item-requests/") and request.method == "GET" \
                and path.count("/") == 3:
            request_id = int(path.split("/")[3])
            row = next((r for r in self.item_requests if r["id"] == request_id), None)
            return reply(200, row) if row else detail(404, "Request not found")

        if path.startswith("/admin/item-requests/") and path.endswith("/status"):
            request_id = int(path.split("/")[3])
            row = next((r for r in self.item_requests if r["id"] == request_id), None)
            if row is None:
                return detail(404, "Request not found")
            row["status"] = body.get("status")
            return reply(200, row)

        if path == "/admin/shop/state":
            if request.method == "PUT":
                if user["role"] not in ("super_admin", "admin"):
                    return detail(403, "Not permitted for this account")
                self.shop_closed = bool(body.get("closed"))
            return reply(200, self._sales_state())

        if path == "/admin/sales/action" and request.method == "POST":
            if user["role"] not in ("super_admin", "admin"):
                return detail(403, "Not permitted for this account")
            action = body.get("action")
            if action not in ("open", "close", "holiday"):
                return detail(422, [{"loc": ["body", "action"], "msg": "bad"}])
            self.sales_actions.append(action)
            self.shop_closed = action != "open"
            self.sales_reason = {"open": "manual_open", "close": "manual_close",
                                 "holiday": "holiday"}[action]
            return reply(200, self._sales_state())

        if path.startswith("/admin/orders/") and path.endswith("/receipt"):
            data = self.receipts.get(int(path.split("/")[3]))
            if data is None:
                return detail(404, "No receipt image")
            return httpx.Response(200, content=data, headers={"content-type": "image/png"},
                                  request=request)

        if path.startswith("/admin/orders/") and path.endswith("/ship"):
            order_id = int(path.split("/")[3])
            for order in self.orders:
                if order["id"] == order_id:
                    if order["status"] not in ("approved", "written"):
                        return detail(409, f"Order in status {order['status']}; cannot ship")
                    phone = str(body.get("courier_phone") or "")
                    if phone and not 7 <= len(phone) <= 15:
                        return detail(422, "Invalid courier phone")
                    order["shipped_at"] = TS
                    order["courier_name"] = body.get("courier_name") or None
                    order["courier_phone"] = phone or None
                    self.ship_bodies = getattr(self, "ship_bodies", []) + [body]
                    return reply(200, order)
            return detail(404, "Order not found")

        if path.startswith("/admin/orders/") and path.endswith("/payment-info"):
            # v2.8.2: «ارسال اطلاعات پرداخت»
            order_id = int(path.split("/")[3])
            for order in self.orders:
                if order["id"] == order_id:
                    if order["status"] != "awaiting_payment":
                        return detail(409, f"Order in status {order['status']}; "
                                           f"payment details not needed")
                    order["payment_info"] = {k: v for k, v in body.items() if v}
                    order["payment_info_at"] = TS
                    order["owned"] = order["owned_by_me"] = True
                    self.payment_bodies = getattr(self, "payment_bodies", []) + [body]
                    return reply(200, order)
            return detail(404, "Order not found")

        if path.startswith("/admin/orders/") and path.endswith("/cancel"):
            order_id = int(path.split("/")[3])
            order = next((o for o in self.orders if o["id"] == order_id), None)
            if order is None:
                return detail(404, "Order not found")
            if order["status"] not in ("awaiting_payment", "receipt_uploaded"):
                return detail(409, f"Order in status {order['status']}; cannot be cancelled")
            order["status"] = "cancelled"
            order["cancel_reason"] = "staff"
            return reply(200, order)

        if path.startswith("/admin/orders/") and path.endswith("/reject-payment"):
            order_id = int(path.split("/")[3])
            for order in self.orders:
                if order["id"] == order_id:
                    order["status"] = "rejected"
                    return reply(200, order)
            return detail(404, "Order not found")

        if path.startswith("/admin/catalog-models"):
            return self._catalog_admin(request, path, body, user, reply, detail)

        if path.startswith(("/admin/pricelists", "/admin/price-mappings", "/admin/proxies")):
            return self._pricelist_admin(request, path, body, user, reply, detail)

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

    # ---- v2.8.0 endpoints ---------------------------------------------------------
    def _v280(self, request, path, body, user, reply, detail):
        params = request.url.params
        manager = user["role"] in ("super_admin", "admin")
        if path == "/admin/assignees":
            return reply(200, [{"id": r["id"], "name": r["full_name"]} for r in self.staff.values()
                               if r["id"] != user["id"] and r["active"]])
        if path == "/admin/activity":
            if not manager:
                return detail(403, "Managers only")
            self.activity_params.append(dict(params))
            return reply(200, self.activity_rows)
        if path == "/admin/archive/orders":
            return reply(200, self.archived_orders)
        if path == "/admin/archive/item-requests":
            return reply(200, self.archived_requests)
        if path == "/admin/price-mappings/suggestions":
            return reply(200, self.suggestions.get(params.get("row_key"), {"items": []}))
        parts = path.split("/")
        if len(parts) == 5 and parts[2] in ("orders", "item-requests") and parts[3].isdigit():
            kind = "order" if parts[2] == "orders" else "request"
            ident = int(parts[3])
            action = parts[4]
            rows = self.orders if kind == "order" else self.item_requests
            row = next((r for r in rows if r["id"] == ident), None)
            if action == "timeline":
                return reply(200, self.timelines.get((kind, ident), []))
            if row is None and action in ("claim", "assign", "confirm-stock", "unavailable"):
                return detail(404, "Order not found" if kind == "order" else "Request not found")
            if action == "claim":
                row.update(owned=True, owned_by_me=True, owner_id=user["id"])
                return reply(200, row)
            if action == "assign":
                self.assigned.append((kind, ident, int(body.get("staff_id"))))
                row.update(owned=True, owned_by_me=body.get("staff_id") == user["id"])
                return reply(200, row)
            if action == "confirm-stock":
                self.stock_confirms.append({"id": ident, **body})
                if not body.get("kala_code") and not row.get("kala_code"):
                    return detail(422, "Choose the product")
                row.update(status="done", outcome="confirmed", order_id=900)
                order = self.add_order(id=900, status="awaiting_payment", request_id=ident)
                return reply(200, order)
            if action == "unavailable":
                row.update(status="done", outcome="unavailable")
                self.item_request_messages.setdefault(ident, []).append(
                    {"id": 1, "request_id": ident, "text": "با پوزش، موجود نیست",
                     "status": "pending", "error": "", "created_at": TS, "created_by": "",
                     "sent_at": None})
                return reply(200, row)
        return None

    # ---- Phase 3 helpers / endpoints ---------------------------------------
    def add_price_row(self, description: str, color: str, *, section: str = "iPHONE",
                      kind: str = "شرکتی", naghd: int | None = 52000, raval: int | None = 52500,
                      action: str | None = None, kala_code: int | None = None,
                      color_label: str = "", auto: bool = False) -> dict:
        row = {"id": len(self.price_rows) + 1, "section": section, "description": description,
               "kind": kind, "color": color, "naghd": naghd, "raval": raval,
               "row_key": f"{description}|{kind}|{color}".lower(),
               "price_rial": raval * 10_000 if raval else (naghd * 10_000 + 5_000_000 if naghd else None),
               "action": action, "kala_code": kala_code, "color_label": color_label,
               "mapping_id": len(self.price_rows) + 101 if action else None,
               "auto": int(auto), "auto_reason": "same_model" if auto else ""}
        self.price_rows.append(row)
        return row

    def add_pricelist(self, status: str = "active", list_date: str = "1405/07/19", **kwargs) -> dict:
        row = {"id": len(self.pricelists) + 1, "list_date": list_date, "source": "telegram",
               "status": status, "row_count": len(self.price_rows), "created_at": TS,
               "reason": None}
        row.update(kwargs)
        self.pricelists.append(row)
        return row

    def _pricelist_admin(self, request, path, body, user, reply, detail):
        method = request.method
        can_manage = user["role"] in ("super_admin", "admin")
        parts = path.strip("/").split("/")
        if path.startswith("/admin/proxies"):
            if user["role"] != "super_admin":
                return detail(403, "Not permitted for this account")
            if path == "/admin/proxies" and method == "GET":
                return reply(200, self.proxies)
            if path == "/admin/proxies" and method == "POST":
                self.proxy_adds.append(body)
                if "proxy?" not in body.get("link", ""):
                    return detail(422, "Not a valid proxy link")
                row = {"id": len(self.proxies) + 1, "host": "new.example", "port": 443,
                       "kind": "dd", "state": "main" if body.get("main") else "probation",
                       "stability": 0.5, "good_days": 0, "checked_days": 0,
                       "last_ok_at": None, "failing_now": False, "secret_masked": "dd…abcd"}
                self.proxies.append(row)
                return reply(201, row)
            proxy = next((p for p in self.proxies if p["id"] == int(parts[2])), None)
            if proxy is None:
                return detail(404, "Proxy not found")
            if method == "DELETE":
                self.proxies.remove(proxy)
                return httpx.Response(204, request=request)
            proxy["state"] = body["state"]
            return reply(200, proxy)

        if method != "GET" and not can_manage:
            return detail(403, "Not permitted for this account")
        if path == "/admin/pricelists" and method == "GET":
            return reply(200, list(reversed(self.pricelists)))
        if path == "/admin/pricelists" and method == "POST":
            self.price_uploads.append(body)
            return reply(200, {"outcome": self.upload_outcome, "list_id": 9, "list_date": "1405/07/20",
                               "row_count": 195, "reasons": ["تغییر قیمت ۲۰٪"],
                               "auto_mapped": getattr(self, "upload_auto", 0)})
        if path == "/admin/pricelists/rows":
            plist = self.pricelists[-1] if self.pricelists else None
            rows = list(self.price_rows)
            counts = {"unmapped": sum(1 for r in rows if r["action"] is None),
                      "mapped": sum(1 for r in rows if r["action"] == "map"),
                      "ignored": sum(1 for r in rows if r["action"] == "ignore"),
                      "auto": sum(1 for r in rows if r["action"] and r.get("auto")),
                      "all": len(rows)} if plist else {}
            sections = list(dict.fromkeys(r["section"] for r in rows))
            section = request.url.params.get("section")
            if section:
                rows = [r for r in rows if r["section"] == section]
            wanted = request.url.params.get("filter", "all")
            state = {"unmapped": None, "mapped": "map", "ignored": "ignore"}
            if wanted in state:
                rows = [r for r in rows if r["action"] == state[wanted]]
            elif wanted == "auto":
                rows = [r for r in rows if r["action"] and r.get("auto")]
            if plist is None:
                return reply(200, {"list": None, "sections": [], "rows": [], "counts": {}})
            return reply(200, {"list": plist, "sections": sections, "rows": rows, "counts": counts})
        if path.startswith("/admin/pricelists/") and parts[-1] in ("approve", "reject"):
            plist = next((p for p in self.pricelists if p["id"] == int(parts[2])), None)
            if plist is None:
                return detail(404, "Price list not found")
            if plist["status"] != "held":
                return detail(409, f"Price list is {plist['status']}")
            plist["status"] = "active" if parts[-1] == "approve" else "rejected"
            return reply(200, plist)
        if path == "/admin/price-mappings" and method == "PUT":
            row = next((r for r in self.price_rows if r["row_key"] == body["row_key"]), None)
            if row is None:
                return detail(404, "Row not found in the current list")
            row.update(action=body["action"], kala_code=body.get("kala_code"),
                       color_label=body.get("color_label", ""), mapping_id=row["id"] + 100)
            return reply(200, {"id": row["mapping_id"], **body})
        if path == "/admin/price-mappings/ignore":
            done = 0
            for row in self.price_rows:
                if row["row_key"] in body["row_keys"]:
                    row.update(action="ignore", kala_code=None, mapping_id=row["id"] + 100)
                    done += 1
            return reply(200, {"ignored": done})
        if path == "/admin/price-mappings/auto" and method == "POST":
            self.auto_runs = getattr(self, "auto_runs", 0) + 1
            return reply(200, {"auto_mapped": 2})
        if path.startswith("/admin/price-mappings/") and parts[-1] == "confirm":
            row = next((r for r in self.price_rows if r["mapping_id"] == int(parts[2])), None)
            if row is None:
                return detail(404, "Mapping not found")
            row["auto"] = 0
            return reply(200, {"id": row["mapping_id"], "auto": 0})
        if path.startswith("/admin/price-mappings/") and method == "DELETE":
            row = next((r for r in self.price_rows if r["mapping_id"] == int(parts[2])), None)
            if row is None:
                return detail(404, "Mapping not found")
            row.update(action=None, kala_code=None, color_label="", mapping_id=None)
            return httpx.Response(204, request=request)
        return detail(404, "Not Found")

    # ---- Phase 6b helpers / endpoints --------------------------------------
    def add_catalog_model(self, slug: str, name: str, brand: str = "Apple", *,
                          hidden: bool = False, aliases: str = "") -> dict:
        model = {"id": len(self.catalog_models) + 1, "slug": slug, "name": name, "brand": brand,
                 "aliases": aliases, "hidden": hidden}
        self.catalog_models.append(model)
        return model

    def add_catalog_item(self, model_id: int, kala_code: int, name: str, *, label: str = "",
                         state: str = "ok", current_name: str = "", score=None,
                         candidates=None) -> dict:
        item = {"id": len(self.catalog_items) + 1, "model_id": model_id, "kala_code": kala_code,
                "label": label, "confirmed_name": name, "current_name": current_name or name,
                "state": state, "score": score, "candidates": candidates or [],
                "pricelist_rows": 0}
        self.catalog_items.append(item)
        return item

    def _catalog_out(self, model: dict) -> dict:
        items = [i for i in self.catalog_items if i["model_id"] == model["id"]]
        status = "unmapped" if not items else "review" if model["hidden"] else "ok"
        return {**model, "status": status, "item_count": len(items),
                "drifted_count": sum(1 for i in items if i["state"] == "drifted"),
                "missing_count": sum(1 for i in items if i["state"] == "missing")}

    def _catalog_detail(self, model: dict) -> dict:
        return {"model": self._catalog_out(model),
                "items": [i for i in self.catalog_items if i["model_id"] == model["id"]]}

    def _catalog_admin(self, request, path, body, user, reply, detail):
        method = request.method
        parts = path.strip("/").split("/")
        if method != "GET" and user["role"] not in ("super_admin", "admin"):
            return detail(403, "Not permitted for this account")
        if path == "/admin/catalog-models" and method == "GET":
            models = [self._catalog_out(m) for m in self.catalog_models]
            counts = {k: sum(1 for m in models if m["status"] == k)
                      for k in ("unmapped", "ok", "review")}
            counts["drifted"] = sum(1 for m in models if m["drifted_count"])
            counts["all"] = len(models)
            return reply(200, {"models": models, "counts": counts,
                               "last_check": self.catalog_last_check})
        if path == "/admin/catalog-models/import":
            self.catalog_imports.append(body["models"])
            added = 0
            for m in body["models"]:
                if not any(x["slug"] == m["slug"] for x in self.catalog_models):
                    self.add_catalog_model(m["slug"], m["name"], m.get("brand", ""),
                                           aliases="\n".join(m.get("aliases") or []))
                    added += 1
            return reply(200, {"added": added, "updated": 0,
                               "unchanged": len(body["models"]) - added})
        if path == "/admin/catalog-models/check":
            self.catalog_checks += 1
            hidden = [m["slug"] for m in self.catalog_models if m["hidden"]]
            self.catalog_last_check = {"at": TS, "checked": len(self.catalog_items), "drifted": 0,
                                       "missing": 0, "newly_hidden": hidden, "alert_sent": 0}
            return reply(200, self.catalog_last_check)
        if parts[2] == "items":
            item = next((i for i in self.catalog_items if i["id"] == int(parts[3])), None)
            if item is None:
                return detail(404, "Item not found")
            model = next(m for m in self.catalog_models if m["id"] == item["model_id"])
            if method == "DELETE":
                self.catalog_items.remove(item)
            elif parts[-1] == "accept":
                item.update(state="ok", confirmed_name=item["current_name"], score=1.0)
            else:
                if body.get("kala_code"):
                    product = self.products.get(int(body["kala_code"]))
                    if product is None:
                        return detail(422, "Product not found in accounting (or inactive)")
                    item.update(kala_code=int(body["kala_code"]), confirmed_name=product["name"],
                                current_name=product["name"], state="ok", candidates=[])
                if body.get("label") is not None:
                    item["label"] = body["label"]
            return reply(200, self._catalog_detail(model))
        model = next((m for m in self.catalog_models if m["id"] == int(parts[2])), None)
        if model is None:
            return detail(404, "Model not found")
        if len(parts) == 3 and method == "GET":
            return reply(200, self._catalog_detail(model))
        if len(parts) == 3 and method == "PATCH":
            model.update({k: v for k, v in body.items() if k in ("name", "brand", "aliases")})
            return reply(200, self._catalog_detail(model))
        if parts[-1] == "suggestions":
            taken = {i["kala_code"]: next(m["slug"] for m in self.catalog_models
                                          if m["id"] == i["model_id"])
                     for i in self.catalog_items}
            query = (request.url.params.get("q") or model["name"]).lower()
            rows = [{"code": c, "name": p["name"], "score": 0.9, "taken_by": taken.get(c)}
                    for c, p in self.products.items()
                    if any(w in p["name"].lower() for w in query.split())]
            return reply(200, rows)
        if parts[-1] == "items" and method == "POST":
            code = int(body["kala_code"])
            if any(i["kala_code"] == code for i in self.catalog_items):
                return detail(409, "Product already mapped to model x")
            product = self.products.get(code)
            if product is None:
                return detail(422, "Product not found in accounting (or inactive)")
            self.add_catalog_item(model["id"], code, product["name"], label=body.get("label", ""))
            return reply(201, self._catalog_detail(model))
        if parts[-1] == "confirm":
            items = [i for i in self.catalog_items if i["model_id"] == model["id"]]
            if any(i["state"] == "missing" for i in items):
                return detail(409, "Replace or remove products missing from accounting")
            for i in items:
                i.update(state="ok", confirmed_name=i["current_name"])
            model["hidden"] = False
            return reply(200, self._catalog_detail(model))
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
                secret = key.endswith("TOKEN")
                out[key] = {"secret": True, "set": bool(value)} if secret else \
                    {"secret": False, "value": value}
            return reply(200, {"settings": out})
        if path == "/admin/server/settings" and request.method == "PUT":
            values = body.get("values") or {}
            bad = {k: "cannot be changed remotely" for k in values if k not in self.server_settings}
            if "RECEIPT_DEADLINE_MINUTES" in values and not str(values["RECEIPT_DEADLINE_MINUTES"]).isdigit():
                bad["RECEIPT_DEADLINE_MINUTES"] = "must be a whole number between 5 and 1440"
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
            for key in ("extra_permissions", "removed_permissions"):
                if key in body:
                    row[key] = body[key]
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
            for key in ("full_name", "role", "active", "extra_permissions",
                        "removed_permissions"):
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
        if parts[-1] == "reset-default":
            target["password"] = "12345"
            target["must_change_password"] = True
            for t in [t for t, uid in self.tokens.items() if uid == target["id"]]:
                self.tokens.pop(t)
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


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Tests never read a real .env (a developer's ACCOUNTING_STATUS_CODE=0 or
    tokens would change results). Opt out only for live runs:
    SHOP_TESTS_USE_DOTENV=1."""
    if os.environ.get("SHOP_TESTS_USE_DOTENV") == "1":
        return
    import dotenv

    # app.main imports load_dotenv inside the function, so patch the source.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
