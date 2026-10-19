"""Shared test fixtures with a fake accounting layer (no real SQL)."""
from __future__ import annotations

import os
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
        #: recipe R5: {codlp: {"ordered", "invoiced"}}; a missing codlp = deleted
        self.invoices: dict = {}
        #: KOL rows for the statement: {person_code: [row, ...]} oldest first
        self.ledger: dict = {}

    def list_groups(self):
        return self.groups

    def ping(self):
        if getattr(self, "down", False):
            raise RuntimeError("accounting down")
        return True

    def list_products(self, *, q=None, group=None, in_stock=True, page=1, page_size=20,
                      level=3, our_reservations=None, include_codes=None, include_groups=None):
        our = our_reservations or {}
        extra = set(include_codes or ())
        extra_groups = set(include_groups or ())
        items = []
        for code, p in self.products.items():
            free = code in extra or p.get("group") in extra_groups
            if p.get("unit_price", 0) <= 0 and not free:  # the reader's "{col} > 0"
                continue
            if group is not None and p.get("group") != group:
                continue
            if q and q not in p["name"]:
                continue
            avail = max(0.0, p["stock"] - p.get("open", 0.0) - our.get(code, 0.0))
            if in_stock and avail <= 0 and not free:
                continue
            items.append({**p, "code": code, "available_qty": avail})
        total = len(items)
        start = (page - 1) * page_size
        return {"total": total, "page": page, "page_size": page_size,
                "items": items[start:start + page_size]}

    def product_names(self):
        if getattr(self, "down", False):
            raise RuntimeError("accounting down")
        return {code: p["name"] for code, p in self.products.items() if p.get("active", True)}

    def get_products_for_order(self, codes, level, our_reservations=None):
        our = our_reservations or {}
        out = {}
        for code in codes:
            p = self.products.get(code)
            if p is None or not p.get("active", True):
                continue
            avail = max(0.0, p["stock"] - p.get("open", 0.0) - our.get(code, 0.0))
            out[code] = {**p, "code": code, "available_qty": avail}
        return out

    def person_code_exists(self, code):
        return code in self.person_codes

    #: v2.6.0: {person code: "fname Name"} (fake names only)
    person_name_map: dict = {}

    def person_names(self, codes):
        return {int(c): self.person_name_map[int(c)] for c in codes
                if c is not None and int(c) in self.person_name_map}

    def find_person_by_mobile(self, mobile):
        if getattr(self, "down", False):
            raise RuntimeError("accounting down")
        return self.persons.get(mobile)

    def invoice_progress(self, codlps):
        return {c: self.invoices[c] for c in codlps if c in self.invoices}

    def invoice_numbers(self, codlps):
        nums = getattr(self, "invoice_nums", {})
        return {c: list(nums[c]) for c in codlps if c in nums}

    def customer_statement(self, person_code, max_rows=2000):
        rows = list(self.ledger.get(person_code, []))
        return {
            "rows": rows[-max_rows:],
            "total_debit": sum(r["debit"] for r in rows),
            "total_credit": sum(r["credit"] for r in rows),
        }


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

    #: what create_person returns: None = a new committed person 8001, 8002, ...
    person_result = None
    _next_person = 8000

    def create_person(self, first_name, last_name, mobile, address="", dry_run=None):
        from app.accounting_writer import PersonResult

        self.calls.append(("create_person", first_name, last_name, mobile))
        if self.person_result is not None:
            return self.person_result
        self._next_person += 1
        return PersonResult(person_code=self._next_person, committed=self.committed,
                            rolled_back=not self.committed)

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
        # v2.6.0: no valid card = no checkout (obviously fake test card).
        payment_card_number="6037-0000-1111-2222",
        # TestClient connects as host "testclient"; loopback rules have own tests.
        service_keys_local_only=False,
        # Sales windows (price list / Friday) have their own tests (test_v250.py).
        sales_windows_enabled=False,
        accounting_status_code=0,
        # v2.8.0: phones need stock in «سازه حساب» (own tests in test_v280.py).
        phone_stock_required=False,
    )


#: v2.6.0 product groups of the test data: 1 and 2 = accessories, 3 = phones.
TEST_GROUPS = [(1, True, False), (2, True, False), (3, True, True)]


@pytest.fixture
def db(settings):
    own = OwnDB(":memory:")
    own.set_group_settings(TEST_GROUPS, "test")
    return own


@pytest.fixture
def reader():
    return FakeReader()


@pytest.fixture
def writer():
    return FakeWriter()


@pytest.fixture
def client(settings, db, reader, writer):
    from app.routers.auth import forgot_limiter, login_limiter

    login_limiter.reset()
    forgot_limiter.reset()
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


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Tests never read a real .env (a developer's ACCOUNTING_STATUS_CODE=0 or
    tokens would change results). Opt out only for live runs:
    SHOP_TESTS_USE_DOTENV=1."""
    if os.environ.get("SHOP_TESTS_USE_DOTENV") == "1":
        return
    from app import config

    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    config.reset_settings()
