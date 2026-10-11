"""Concurrency: no overselling and no duplicate accounting order numbers.

The fake accounting layer allocates Codlp under a lock and is idempotent per
order id, mirroring the real writer's sp_getapplock + Sharhlp behavior.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app import deps
from app.main import create_app

from .conftest import FakeReader, h, register_and_approve


def _app_client(settings, db, reader, writer) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_db] = lambda: db
    app.dependency_overrides[deps.get_reader] = lambda: reader
    app.dependency_overrides[deps.get_writer] = lambda: writer
    return TestClient(app)


def _product_reader(stock: float) -> FakeReader:
    reader = FakeReader()
    reader.products = {
        200: {"name": "Bulk", "group": 1, "stock": float(stock), "open": 0.0,
              "unit_price": 10.0, "image": None},
    }
    reader.person_codes = {7001}
    return reader


def _order_body(qty: float = 1) -> dict:
    return {"platform": "bale", "chat_id": "111",
            "items": [{"kala_code": 200, "qty": qty}]}


def _upload_receipt(client, order_id):
    return client.post(
        f"/orders/{order_id}/receipt",
        json={"receipt_ref": "R-1"},
        params={"platform": "bale", "chat_id": "111"},
        headers=h("bot"),
    )


def test_concurrent_orders_do_not_oversell(settings, db, writer):
    reader = _product_reader(10)
    client = _app_client(settings, db, reader, writer)
    register_and_approve(client)

    def place(_):
        return client.post("/orders", json=_order_body(1), headers=h("bot")).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(place, range(20)))

    assert codes.count(201) == 10, codes
    assert codes.count(409) == 10, codes
    assert db.pending_reservations().get(200, 0.0) == 10.0


def test_concurrent_approvals_get_unique_codlp(settings, db, writer):
    reader = _product_reader(100)
    client = _app_client(settings, db, reader, writer)
    register_and_approve(client)

    order_ids = []
    for _ in range(10):
        order = client.post("/orders", json=_order_body(1), headers=h("bot")).json()
        _upload_receipt(client, order["id"])
        order_ids.append(order["id"])

    def approve(order_id):
        return client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(approve, order_ids))

    assert all(r.status_code == 200 for r in results)
    numbers = [r.json()["accounting_order_no"] for r in results]
    assert len(set(numbers)) == len(numbers), numbers  # no duplicate Codlp
    assert len(writer.calls) == 10


def test_concurrent_double_approval_writes_once(settings, db, writer):
    reader = _product_reader(100)
    client = _app_client(settings, db, reader, writer)
    register_and_approve(client)
    order = client.post("/orders", json=_order_body(1), headers=h("bot")).json()
    _upload_receipt(client, order["id"])

    def approve(_):
        return client.post(
            f"/admin/orders/{order['id']}/approve-payment", headers=h("admin")
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(approve, range(10)))

    assert codes.count(200) == 1, codes
    assert codes.count(409) == 9, codes
    assert len(writer.calls) == 1  # written exactly once


def test_concurrent_receipt_upload_creates_one_payment(settings, db, writer):
    reader = _product_reader(100)
    client = _app_client(settings, db, reader, writer)
    register_and_approve(client)
    order = client.post("/orders", json=_order_body(1), headers=h("bot")).json()

    def upload(_):
        return _upload_receipt(client, order["id"]).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(upload, range(10)))

    assert codes.count(200) == 1, codes
    assert codes.count(409) == 9, codes
    with db._lock:
        payments = db._conn.execute(
            "SELECT COUNT(*) AS n FROM payments WHERE order_id=?", (order["id"],)
        ).fetchone()["n"]
    assert payments == 1
