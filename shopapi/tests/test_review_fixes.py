"""Regression tests for the HIGH/MEDIUM issues found in the security review.

See REVIEW.md for the finding each test covers.
"""
from __future__ import annotations

import pyodbc

from app.accounting_reader import AccountingReader, compute_available
from app.accounting_writer import AccountingWriter
from app.config import Settings
from app.security import _role_for_key

from .conftest import h, register_and_approve, seed_products
from .test_writer import FakeConn


# ---- M1: API keys compared in constant time / admin isolation --------------
def test_key_role_matching():
    s = Settings(bot_api_key="bot-key", site_api_key="site-key", admin_api_key="admin-key")
    assert _role_for_key(s, "bot-key") == "bot"
    assert _role_for_key(s, "site-key") == "site"
    assert _role_for_key(s, "admin-key") == "admin"
    assert _role_for_key(s, "nope") is None
    assert _role_for_key(s, "") is None


# ---- Admin /system-info (added for the ShopAdmin desktop console) ----------
def test_system_info_requires_admin(client):
    assert client.get("/admin/system-info").status_code == 401
    assert client.get("/admin/system-info", headers=h("bot")).status_code == 403
    assert client.get("/admin/system-info", headers=h("site")).status_code == 403
    assert client.get("/admin/system-info", headers=h("admin")).status_code == 200


def test_system_info_reports_write_flag_and_hides_secrets(client):
    body = client.get("/admin/system-info", headers=h("admin")).json()
    # The desktop console needs this flag to warn about dry-run mode.
    assert body["accounting_write_enabled"] is False
    assert body["max_order_qty"] == 10000
    assert body["allow_shared_person_code"] is False
    # No key material may ever be exposed by a read-only status endpoint.
    blob = str(body)
    for secret in ("admin-key", "bot-key", "site-key"):
        assert secret not in blob
    for leaked_field in ("admin_api_key", "bot_api_key", "site_api_key", "accounting_password"):
        assert leaked_field not in body


def test_admin_endpoints_reject_bot_and_site_keys(client):
    assert client.get("/admin/users", headers=h("bot")).status_code == 403
    assert client.get("/admin/users", headers=h("site")).status_code == 403
    assert client.get("/admin/users", headers=h("admin")).status_code == 200
    assert client.get("/admin/users", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/admin/users").status_code == 401


# ---- M2: availability is never negative -----------------------------------
def test_availability_is_never_negative(client, reader):
    assert compute_available(5, 6, 0) == 0.0
    assert compute_available(0, 0, 0) == 0.0
    reader.products = {
        300: {"name": "Over", "group": 1, "stock": 1.0, "open": 5.0,
              "unit_price": 10.0, "image": None},
    }
    r = client.get("/products", params={"in_stock": "false"}, headers=h("bot"))
    assert r.json()["items"][0]["available_qty"] == 0.0


# ---- M3: quantity is positive and bounded ---------------------------------
def test_quantity_bounds(client, reader):
    seed_products(reader)
    register_and_approve(client)
    url = "/orders"
    payload = {"platform": "bale", "chat_id": "111",
               "items": [{"kala_code": 101, "qty": 1}]}

    for bad_qty in (0, -1, 2_000_000):
        body = {**payload, "items": [{"kala_code": 101, "qty": bad_qty}]}
        assert client.post(url, json=body, headers=h("bot")).status_code == 422

    # above the configurable per-item maximum
    body = {**payload, "items": [{"kala_code": 101, "qty": 20000}]}
    assert client.post(url, json=body, headers=h("bot")).status_code == 422

    # NaN / Infinity must be rejected (raw JSON, since these are not valid JSON numbers)
    for token in ("NaN", "Infinity"):
        raw = ('{"platform":"bale","chat_id":"111","items":'
               f'[{{"kala_code":101,"qty":{token}}}]}}')
        r = client.post(url, content=raw,
                        headers={**h("bot"), "Content-Type": "application/json"})
        assert r.status_code == 422, token

    # too many distinct line items
    many = [{"kala_code": 101, "qty": 1} for _ in range(101)]
    assert client.post(url, json={**payload, "items": many},
                       headers=h("bot")).status_code == 422


# ---- M4: accounting DB unreachable -> clear 503, no leak ------------------
def test_accounting_db_unreachable_returns_503(client, reader):
    def boom():
        raise pyodbc.Error("08001", "[ODBC] SQL Server not found; SELECT * FROM secret")

    reader.list_groups = boom
    r = client.get("/groups", headers=h("bot"))
    assert r.status_code == 503
    assert r.json()["detail"] == "Accounting database unavailable"
    assert "ODBC" not in r.text and "SELECT" not in r.text


# ---- M5: a person_code cannot be reused by another user -------------------
def test_person_code_cannot_be_reused(client, reader, settings):
    seed_products(reader)
    register_and_approve(client, chat_id="111", person_code=7001)

    client.post("/users/register", json={
        "platform": "bale", "chat_id": "222", "name": "Bob", "phone": "09121111111",
    }, headers=h("bot"))
    u2 = client.get("/users/bale/222", headers=h("bot")).json()

    clash = client.post(f"/admin/users/{u2['id']}/approve",
                        json={"person_code": 7001}, headers=h("admin"))
    assert clash.status_code == 409

    settings.allow_shared_person_code = True
    allowed = client.post(f"/admin/users/{u2['id']}/approve",
                          json={"person_code": 7001}, headers=h("admin"))
    assert allowed.status_code == 200
    assert allowed.json()["person_code"] == 7001


# ---- M7: query timeout is applied to accounting connections ---------------
def test_query_timeout_applied(monkeypatch):
    captured = {}

    class FakeConn:
        def __init__(self):
            self.timeout = 0

    def fake_connect(conn_str, timeout=None):
        captured["connect_timeout"] = timeout
        return FakeConn()

    monkeypatch.setattr("app.accounting_reader.pyodbc.connect", fake_connect)
    settings = Settings(accounting_connect_timeout=3, accounting_query_timeout=7)
    conn = AccountingReader(settings).connection()
    assert captured["connect_timeout"] == 3
    assert conn.timeout == 7


# ---- M8: a receipt can only be attached to your own order -----------------
def test_receipt_upload_requires_order_ownership(client, reader):
    seed_products(reader)
    register_and_approve(client, chat_id="111")
    register_and_approve(client, chat_id="222", phone="09121111111")
    order = client.post("/orders", json={
        "platform": "bale", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot")).json()

    other = client.post(f"/orders/{order['id']}/receipt", json={"receipt_ref": "R-2"},
                        params={"platform": "bale", "chat_id": "222"}, headers=h("bot"))
    assert other.status_code == 404

    no_proof = client.post(f"/orders/{order['id']}/receipt", json={"receipt_ref": "R-3"},
                           headers=h("bot"))
    assert no_proof.status_code == 404

    owner = client.post(f"/orders/{order['id']}/receipt", json={"receipt_ref": "R-1"},
                        params={"platform": "bale", "chat_id": "111"}, headers=h("bot"))
    assert owner.status_code == 200
    assert owner.json()["status"] == "receipt_uploaded"

    # admin may act on any order
    order2 = client.post("/orders", json={
        "platform": "bale", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot")).json()
    admin_ok = client.post(f"/orders/{order2['id']}/receipt", json={"receipt_ref": "R-4"},
                           headers=h("admin"))
    assert admin_ok.status_code == 200


# ---- H1: a dry-run write must NOT mark the order as written ---------------
def test_approve_payment_dry_run_is_not_marked_written(client, reader, writer):
    seed_products(reader)
    writer.committed = False  # simulates ACCOUNTING_WRITE_ENABLED=false
    register_and_approve(client)
    order = client.post("/orders", json={
        "platform": "bale", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot")).json()
    client.post(f"/orders/{order['id']}/receipt", json={"receipt_ref": "R-1"},
                params={"platform": "bale", "chat_id": "111"}, headers=h("bot"))

    r = client.post(f"/admin/orders/{order['id']}/approve-payment", headers=h("admin"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "receipt_uploaded"   # nothing was written to accounting
    assert body["accounting_order_no"] is None    # so it stays retryable

    # a real (committed) write still marks it written
    writer.committed = True
    r2 = client.post(f"/admin/orders/{order['id']}/approve-payment", headers=h("admin"))
    assert r2.json()["status"] == "written"
    assert r2.json()["accounting_order_no"] is not None


def test_approve_payment_idempotent_replay_is_marked_written(client, reader, writer):
    seed_products(reader)
    register_and_approve(client)
    order = client.post("/orders", json={
        "platform": "bale", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot")).json()
    client.post(f"/orders/{order['id']}/receipt", json={"receipt_ref": "R-1"},
                params={"platform": "bale", "chat_id": "111"}, headers=h("bot"))

    # The header already exists in the accounting DB from an earlier real write.
    writer.committed = False
    writer._by_order[order["id"]] = 4242

    r = client.post(f"/admin/orders/{order['id']}/approve-payment", headers=h("admin"))
    assert r.status_code == 200
    assert r.json()["status"] == "written"
    assert r.json()["accounting_order_no"] == 4242


# ---- H2: the writer locks before its idempotency check --------------------
def test_writer_takes_lock_before_idempotency_check():
    conn = FakeConn(max_codlp=5)
    settings = Settings(accounting_database="hesab5", accounting_write_enabled=False)
    writer = AccountingWriter(settings, connection_factory=lambda: conn)
    writer.write_order(1, 7001, [(101, 1.0, 100.0)])

    sqls = [sql.upper() for sql, _ in conn.executed]
    lock_idx = next(i for i, s in enumerate(sqls) if "SP_GETAPPLOCK" in s)
    sharhlp_idx = next(i for i, s in enumerate(sqls) if "SHARHLP" in s and "SELECT" in s)
    assert lock_idx < sharhlp_idx
