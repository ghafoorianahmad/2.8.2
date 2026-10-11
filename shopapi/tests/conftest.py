"""Shared test fixtures with a fake accounting layer (no real SQL)."""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.accounting_writer import WriteResult
from app.config import Settings
from app.db_own import OwnDB
from app.main import create_app


def h(role: str) -> dict:
    return {"X-API-Key": f"{role}-key"}


class FakeReader:
    """Minimal in-memory stand-in for AccountingReader."""

    def __init__(self, products=None, groups=None, person_codes=None, persons=None):
        self.products = products if products is not None else {}
        self.groups = groups if groups is not None else []
        self.person_codes = set(person_codes or [])
        self.persons = persons or {}

    def list_groups(self):
        return self.groups

    def ping(self):
        if getattr(self, "down", False):
            raise RuntimeError("accounting down")
        return True

    def list_products(self, *, q=None, group=None, in_stock=True, page=1, page_size=20,
                      level=3, our_reservations=None):
        our = our_reservations or {}
        items = []
        for code, p in self.products.items():
            if p.get("unit_price", 0) <= 0:  # mirrors the reader's "{col} > 0" filter
                continue
            if group is not None and p.get("group") != group:
                continue
            if q and q not in p["name"]:
                continue
            avail = max(0.0, p["stock"] - p.get("open", 0.0) - our.get(code, 0.0))
            if in_stock and avail <= 0:
                continue
            items.append({**p, "code": code, "available_qty": avail})
        total = len(items)
        start = (page - 1) * page_size
        return {"total": total, "page": page, "page_size": page_size,
                "items": items[start:start + page_size]}

    def get_products_for_order(self, codes, level, our_reservations=None):
        our = our_reservations or {}
        out = {}
        for code in codes:
            p = self.products.get(code)
            if p is None:
                continue
            avail = max(0.0, p["stock"] - p.get("open", 0.0) - our.get(code, 0.0))
            out[code] = {**p, "code": code, "available_qty": avail}
        return out

    def person_code_exists(self, code):
        return code in self.person_codes

    def find_person_by_mobile(self, mobile):
        return self.persons.get(mobile)


class FakeWriter:
    """Fake accounting writer.

    Mirrors the two properties the API relies on: a unique Codlp per order
    (allocated under a lock, as the real sp_getapplock does) and idempotency
    per order id (as the real Sharhlp='API-<id>' check does). `committed=False`
    simulates a dry-run (rolled back).
    """

    def __init__(self, committed: bool = True):
        self.committed = committed
        self.calls = []
        self._lock = threading.Lock()
        self._counter = 1000
        self._by_order: dict[int, int] = {}

    def write_order(self, our_order_id, person_code, items, dry_run=None):
        with self._lock:
            idempotent = our_order_id in self._by_order
            if not idempotent:
                self._counter += 1
                self._by_order[our_order_id] = self._counter
            codlp = self._by_order[our_order_id]
        self.calls.append((our_order_id, person_code, items, dry_run))
        return WriteResult(
            accounting_order_no=codlp,
            person_code=person_code,
            datelp="1405/07/13",
            mablp=0,
            status_code=0,
            usercode=1,
            anbarcode=1,
            items=items,
            idempotent=idempotent,
            committed=self.committed,
            rolled_back=not self.committed,
        )


@pytest.fixture
def settings():
    return Settings(
        accounting_driver="ODBC Driver 17 for SQL Server",
        accounting_server=r".\SQLEXPRESS",
        accounting_database="hesab5",
        bot_api_key="bot-key",
        site_api_key="site-key",
        admin_api_key="admin-key",
        sqlite_path=":memory:",
        bank_account_text="pay to account 123",
        # TestClient connects as host "testclient"; loopback rules have own tests.
        service_keys_local_only=False,
    )


@pytest.fixture
def db(settings):
    return OwnDB(":memory:")


@pytest.fixture
def reader():
    return FakeReader()


@pytest.fixture
def writer():
    return FakeWriter()


@pytest.fixture
def client(settings, db, reader, writer):
    from app.routers.auth import login_limiter

    login_limiter.reset()
    app = create_app()
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_db] = lambda: db
    app.dependency_overrides[deps.get_reader] = lambda: reader
    app.dependency_overrides[deps.get_writer] = lambda: writer
    return TestClient(app)


def seed_products(reader):
    """Populate the fake reader with a few products."""
    reader.products = {
        101: {"name": "Widget A", "group": 1, "stock": 10.0, "open": 2.0,
              "unit_price": 100.0, "image": None},
        102: {"name": "Widget B", "group": 1, "stock": 0.0, "open": 0.0,
              "unit_price": 50.0, "image": None},
        103: {"name": "Widget C", "group": 2, "stock": 5.0, "open": 0.0,
              "unit_price": 0.0, "image": None},  # price 0 -> not for sale
        104: {"name": "Widget D", "group": 2, "stock": 5.0, "open": 0.0,
              "unit_price": 30.0, "image": None},
    }
    reader.person_codes = {7001}
    reader.groups = [{"code": 1, "name": "Group 1"}, {"code": 2, "name": "Group 2"}]


def register_and_approve(client, platform="bale", chat_id="111", person_code=7001,
                         phone="09120000000"):
    client.post("/users/register", json={
        "platform": platform, "chat_id": chat_id, "name": "Ali", "phone": phone,
    }, headers=h("bot"))
    user = client.get(f"/users/{platform}/{chat_id}", headers=h("bot")).json()
    client.post(f"/admin/users/{user['id']}/approve", json={"person_code": person_code},
                headers=h("admin"))
    return user["id"]
