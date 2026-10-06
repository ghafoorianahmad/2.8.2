"""Shared pytest fixtures for ShopAdmin.

No test touches the network: the shopapi client is driven by an
``httpx.MockTransport`` and all storage uses an in-memory SQLite database.
"""
from __future__ import annotations

import os
import re
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
from app.auth import AuthService, hash_password  # noqa: E402
from app.store import Store  # noqa: E402


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


@pytest.fixture
def auth(store) -> AuthService:
    return AuthService(store)


@pytest.fixture
def super_admin(auth):
    return auth.create_first_super_admin("owner", "مالک فروشگاه", "Secret123")


@pytest.fixture
def make_user(auth):
    def _make(username="staff", full_name="کارمند", password="Secret123", role="operator"):
        return auth.create_user(username, full_name, password, role)
    return _make


# --------------------------------------------------------------------------
# fake shopapi
# --------------------------------------------------------------------------
class FakeShopApi:
    """A tiny in-memory stand-in for shopapi used by the HTTP client tests."""

    def __init__(self, api_key: str = "admin-key") -> None:
        self.api_key = api_key
        self.customers: list[dict] = []
        self.orders: list[dict] = []
        self.products: dict[int, dict] = {}
        self.groups: list[dict] = []
        self.persons: dict[str, dict] = {}
        self.write_enabled = True
        self.requests: list[tuple[str, str]] = []
        self.force_status: int | None = None
        self.force_detail: object = None
        self.offline = False

    # ---- helpers used by tests ------------------------------------------
    def add_customer(self, **kwargs) -> dict:
        row = {
            "id": len(self.customers) + 1,
            "platform": "telegram",
            "chat_id": str(1000 + len(self.customers)),
            "name": "مشتری نمونه",
            "phone": "09120000000",
            "status": "pending",
            "person_code": None,
            "created_at": "2025-01-01T10:00:00+00:00",
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
            "created_at": "2025-01-01T10:00:00+00:00",
            "items": [
                {"kala_code": 101, "name": "کالای نمونه", "qty": 2.0, "unit_price": 125000.0}
            ],
            "payment_instructions": None,
            "user_name": "مشتری نمونه",
        }
        row.update(kwargs)
        self.orders.append(row)
        return row

    # ---- request handler -------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))

        if self.offline:
            raise httpx.ConnectError("offline", request=request)

        if self.force_status is not None:
            status, detail = self.force_status, self.force_detail
            # One-shot: a test that forces one error must not poison the next call.
            self.force_status = None
            self.force_detail = None
            return httpx.Response(status, json={"detail": detail}, request=request)

        if path != "/health":
            supplied = request.headers.get("X-API-Key", "")
            if not supplied:
                return httpx.Response(401, json={"detail": "Missing X-API-Key header"}, request=request)
            if supplied != self.api_key:
                return httpx.Response(401, json={"detail": "Invalid API key"}, request=request)

        if path == "/health":
            return httpx.Response(200, json={"status": "ok"}, request=request)

        if path == "/admin/system-info":
            return httpx.Response(
                200,
                json={
                    "accounting_write_enabled": self.write_enabled,
                    "write_allowed_on_host": self.write_enabled,
                    "price_level_bot": 1,
                    "price_level_site": 1,
                    "reserve_hours": 12,
                    "max_order_qty": 10000,
                    "allow_shared_person_code": False,
                    "bank_account_text": None,
                },
                request=request,
            )

        if path == "/admin/users":
            wanted = request.url.params.get("status")
            rows = [c for c in self.customers if not wanted or c["status"] == wanted]
            return httpx.Response(200, json=rows, request=request)

        if path == "/admin/persons/match":
            mobile = request.url.params.get("mobile", "")
            match = self.persons.get(mobile)
            if match is None:
                return httpx.Response(404, json={"detail": "No matching person"}, request=request)
            return httpx.Response(200, json=match, request=request)

        if path.startswith("/admin/users/") and path.endswith("/approve"):
            user_id = int(path.split("/")[3])
            import json as _json

            person_code = _json.loads(request.content or b"{}").get("person_code")
            for customer in self.customers:
                if customer["id"] == user_id:
                    customer["status"] = "approved"
                    customer["person_code"] = person_code
                    return httpx.Response(200, json=customer, request=request)
            return httpx.Response(404, json={"detail": "User not found"}, request=request)

        if path.startswith("/admin/users/") and path.endswith("/reject"):
            user_id = int(path.split("/")[3])
            for customer in self.customers:
                if customer["id"] == user_id:
                    customer["status"] = "rejected"
                    return httpx.Response(200, json=customer, request=request)
            return httpx.Response(404, json={"detail": "User not found"}, request=request)

        if path == "/admin/orders":
            wanted = request.url.params.get("status") or "receipt_uploaded"
            rows = [o for o in self.orders if o["status"] == wanted]
            return httpx.Response(200, json=rows, request=request)

        if path == "/admin/orders/expire":
            return httpx.Response(200, json={"expired": 0}, request=request)

        if path.startswith("/admin/orders/") and path.endswith("/approve-payment"):
            order_id = int(path.split("/")[3])
            for order in self.orders:
                if order["id"] == order_id:
                    if order["status"] != "receipt_uploaded":
                        return httpx.Response(
                            409,
                            json={"detail": f"Order in status {order['status']}; cannot approve"},
                            request=request,
                        )
                    order["status"] = "written"
                    order["accounting_order_no"] = 5001
                    return httpx.Response(200, json=order, request=request)
            return httpx.Response(404, json={"detail": "Order not found"}, request=request)

        if path.startswith("/admin/orders/") and path.endswith("/reject-payment"):
            order_id = int(path.split("/")[3])
            for order in self.orders:
                if order["id"] == order_id:
                    order["status"] = "rejected"
                    return httpx.Response(200, json=order, request=request)
            return httpx.Response(404, json={"detail": "Order not found"}, request=request)

        if path == "/products":
            query = (request.url.params.get("q") or "").strip()
            group = request.url.params.get("group")
            rows = list(self.products.values())
            if query:
                rows = [p for p in rows if query in p["name"]]
            if group:
                rows = [p for p in rows if str(p.get("group")) == str(group)]
            return httpx.Response(
                200,
                json={"total": len(rows), "page": 1, "page_size": 50, "items": rows},
                request=request,
            )

        if path == "/groups":
            return httpx.Response(200, json=self.groups, request=request)

        return httpx.Response(404, json={"detail": "Not Found"}, request=request)


@pytest.fixture
def fake_api() -> FakeShopApi:
    return FakeShopApi()


@pytest.fixture
def api(fake_api) -> ShopApiClient:
    client = ShopApiClient(
        "http://shopapi.test", "admin-key", transport=httpx.MockTransport(fake_api.handler)
    )
    yield client
    client.close()


@pytest.fixture
def seeded_store(store):
    """A configured store with a super admin, ready for UI-level tests."""
    store.configure_connection("http://shopapi.test", "admin-key")
    store.set_setting("wizard_completed", True)
    service = AuthService(store)
    service.create_first_super_admin("owner", "مالک فروشگاه", "Secret123")
    return store


@pytest.fixture(scope="session")
def admin_qapp():
    """A themed QApplication with RTL direction, shared by every Qt test.

    Lives here (not in a single test module) so any test file can use it.
    Skipped cleanly when PySide6 is not installed.
    """
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
    """Close every top-level window a test opened, before its store is closed.

    Without this, a window created by one test can still be alive while the next
    test runs, and Qt keeps delivering events to it — including to destroyed
    state such as a closed SQLite connection.
    """
    from PySide6.QtWidgets import QApplication

    yield

    for widget in QApplication.topLevelWidgets():
        try:
            if widget.isVisible():
                widget.close()
        except RuntimeError:
            pass  # the C++ object is already gone
    admin_qapp.processEvents()


def pytest_collection_modifyitems(config, items):
    """Attach the window-cleanup fixture to every test that builds Qt widgets.

    Done automatically so a newly written Qt test cannot forget it and leave a
    live window pointing at a closed database.
    """
    signature = re.compile(r"\b(ui_context|admin_qapp|qapp)\b")
    for item in items:
        path = str(getattr(item, "fspath", ""))
        if "test_ui" not in path and "test_service_manager" not in path:
            continue
        source = getattr(item, "obj", None)
        code = getattr(source, "__code__", None)
        if code is None:
            continue
        if signature.search(str(code.co_varnames)) and "top_level_windows" not in code.co_varnames:
            item.fixturenames.append("top_level_windows")
