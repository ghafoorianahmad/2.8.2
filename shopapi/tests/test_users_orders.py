"""Registration/approval flow, ordering, ownership and reservation/expiry."""
from .conftest import h, register_and_approve, seed_products


def test_registration_is_idempotent(client, reader):
    seed_products(reader)
    payload = {"platform": "telegram", "chat_id": "111", "name": "Ali", "phone": "09120000000"}
    first = client.post("/users/register", json=payload, headers=h("bot"))
    second = client.post("/users/register", json=payload, headers=h("bot"))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "pending"


def test_pending_user_cannot_order(client, reader):
    seed_products(reader)
    client.post("/users/register", json={
        "platform": "telegram", "chat_id": "111", "name": "Ali", "phone": "09120000000",
    }, headers=h("bot"))
    r = client.post("/orders", json={
        "platform": "telegram", "chat_id": "111", "items": [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot"))
    assert r.status_code == 403


def test_approve_requires_existing_person_code(client, reader):
    seed_products(reader)
    user_id = register_and_approve(client, person_code=7001)
    # a fresh user with a bad person code
    client.post("/users/register", json={
        "platform": "telegram", "chat_id": "222", "name": "Bob", "phone": "09121111111",
    }, headers=h("bot"))
    u = client.get("/users/telegram/222", headers=h("bot")).json()
    r = client.post(f"/admin/users/{u['id']}/approve", json={"person_code": 9999},
                    headers=h("admin"))
    assert r.status_code == 422


def test_approval_flow_then_order(client, reader):
    seed_products(reader)
    register_and_approve(client)
    r = client.post("/orders", json={
        "platform": "telegram", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 2}],
    }, headers=h("bot"))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "awaiting_payment"
    assert body["total"] == 200.0
    assert body["items"][0]["kala_code"] == 101
    assert body["payment_instructions"] == "pay to account 123"


def test_order_rejects_insufficient_stock(client, reader):
    seed_products(reader)
    register_and_approve(client)
    # Widget A available = 8; ask for 9 -> conflict
    r = client.post("/orders", json={
        "platform": "telegram", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 9}],
    }, headers=h("bot"))
    assert r.status_code == 409


def test_customer_cannot_read_other_customer_order(client, reader):
    seed_products(reader)
    register_and_approve(client, chat_id="111")
    register_and_approve(client, chat_id="222", phone="09121111111")
    order = client.post("/orders", json={
        "platform": "telegram", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot")).json()

    # owner can read their own order
    ok = client.get(f"/orders/{order['id']}", params={"platform": "telegram", "chat_id": "111"},
                    headers=h("bot"))
    assert ok.status_code == 200

    # another customer cannot
    denied = client.get(f"/orders/{order['id']}",
                        params={"platform": "telegram", "chat_id": "222"}, headers=h("bot"))
    assert denied.status_code == 404

    # without ownership proof -> 404 (does not leak existence)
    no_proof = client.get(f"/orders/{order['id']}", headers=h("bot"))
    assert no_proof.status_code == 404

    # admin can read any order
    admin_ok = client.get(f"/orders/{order['id']}", headers=h("admin"))
    assert admin_ok.status_code == 200


def test_reservation_and_expiry(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    order = client.post("/orders", json={
        "platform": "telegram", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 3}],
    }, headers=h("bot")).json()

    # Widget A available = 10 - 2 - 3 = 5 while reserved
    r = client.get("/products", params={"in_stock": "false"}, headers=h("bot"))
    prod = {p["code"]: p for p in r.json()["items"]}[101]
    assert prod["available_qty"] == 5.0

    # force the reservation into the past, then expire
    with db._lock:
        db._conn.execute(
            "UPDATE orders SET reserve_until='2000-01-01T00:00:00+00:00' WHERE id=?",
            (order["id"],),
        )
        db._conn.commit()

    expired = client.post("/admin/orders/expire", headers=h("admin"))
    assert expired.status_code == 200
    assert expired.json() == {"expired": 1}

    # reservation freed -> available back to 8
    r2 = client.get("/products", params={"in_stock": "false"}, headers=h("bot"))
    prod2 = {p["code"]: p for p in r2.json()["items"]}[101]
    assert prod2["available_qty"] == 8.0


def test_admin_approve_payment_writes_order(client, reader, writer):
    seed_products(reader)
    register_and_approve(client)
    order = client.post("/orders", json={
        "platform": "telegram", "chat_id": "111",
        "items": [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot")).json()
    client.post(f"/orders/{order['id']}/receipt", json={"receipt_ref": "R-1"},
                params={"platform": "telegram", "chat_id": "111"}, headers=h("bot"))
    r = client.post(f"/admin/orders/{order['id']}/approve-payment", headers=h("admin"))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "written"
    assert body["accounting_order_no"] == 1001  # first allocation of the fake writer
    # writer was called once with the order id and person code
    assert len(writer.calls) == 1
    assert writer.calls[0][0] == order["id"]
    assert writer.calls[0][1] == 7001
