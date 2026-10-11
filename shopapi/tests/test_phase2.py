"""Phase 2: contact verification, pending limits, receipts, tracking,
statement, closed mode and the single-product endpoint."""
import base64

from app import receipts, tracking
from app.accounting_writer import PersonResult
from app.statement import build_statement

from .conftest import h, register_and_approve, seed_products

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def register(client, chat_id="111", phone="09120000000", name="Ali"):
    return client.post("/users/register", json={
        "platform": "bale", "chat_id": chat_id, "name": name, "phone": phone,
    }, headers=h("bot"))


def order(client, chat_id="111", items=None):
    return client.post("/orders", json={
        "platform": "bale", "chat_id": chat_id,
        "items": items or [{"kala_code": 101, "qty": 1}],
    }, headers=h("bot"))


def events(db):
    return [e["kind"] for e in db.list_events(0, 500)]


# ---- verification (§3) ----------------------------------------------------
def test_known_mobile_is_approved_at_once(client, reader, db):
    seed_products(reader)
    reader.persons = {"09121234567": {"code": 7001}}
    r = register(client, phone="+989121234567")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["person_code"] == 7001
    assert body["phone"] == "09121234567"          # normalized
    assert "customer_auto_approved" in events(db)
    assert "customer_registered" not in events(db)


def test_unknown_mobile_waits_for_staff(client, reader, db):
    seed_products(reader)
    r = register(client)
    assert r.json()["status"] == "pending"
    assert "customer_registered" in events(db)


def test_not_a_mobile_is_refused(client, reader):
    assert register(client, phone="12345").status_code == 422


def test_person_already_linked_stays_pending(client, reader):
    seed_products(reader)
    reader.persons = {"09121234567": {"code": 7001}}
    assert register(client, "1", "09121234567").json()["status"] == "approved"
    # same accounting person, another Bale account
    assert register(client, "2", "09121234567").json()["status"] == "pending"


def test_accounting_down_means_pending_not_error(client, reader):
    seed_products(reader)
    reader.persons = {"09121234567": {"code": 7001}}
    reader.down = True
    r = register(client, phone="09121234567")
    assert r.status_code == 200 and r.json()["status"] == "pending"


def test_pending_customer_is_rematched_on_new_contact(client, reader):
    seed_products(reader)
    assert register(client).json()["status"] == "pending"
    # the shop entered the customer in the accounting software meanwhile
    reader.persons = {"09120000000": {"code": 7001}}
    assert register(client).json()["status"] == "approved"


def test_approve_without_code_creates_person_with_edited_name(client, reader, writer, db):
    seed_products(reader)
    user_id = register(client, name="🦄 xx").json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve",
                    json={"first_name": "علی", "last_name": "رضایی"}, headers=h("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["person_code"] == 8001
    assert body["name"] == "علی رضایی"
    assert ("create_person", "علی", "رضایی", "09120000000") in writer.calls


def test_approve_without_code_needs_last_name(client, reader):
    seed_products(reader)
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", json={"first_name": "x"},
                    headers=h("admin"))
    assert r.status_code == 422


def test_approve_create_person_dry_run_is_honest(client, reader, writer):
    seed_products(reader)
    writer.committed = False
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", json={"last_name": "رضایی"},
                    headers=h("admin"))
    assert r.status_code == 409 and "disabled" in r.json()["detail"]
    assert client.get("/users/bale/111", headers=h("bot")).json()["status"] == "pending"


def test_approve_create_person_links_existing_mobile(client, reader, writer):
    seed_products(reader)
    writer.person_result = PersonResult(person_code=7001, existing=True)
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", json={"last_name": "x"},
                    headers=h("admin"))
    assert r.status_code == 200 and r.json()["person_code"] == 7001


def test_approve_create_person_shared_mobile_needs_code(client, reader, writer):
    seed_products(reader)
    writer.person_result = PersonResult(person_code=7001, existing=True, ambiguous=True)
    user_id = register(client).json()["id"]
    r = client.post(f"/admin/users/{user_id}/approve", json={"last_name": "x"},
                    headers=h("admin"))
    assert r.status_code == 409


# ---- pending customers' limits --------------------------------------------
def test_pending_customer_orders_within_limit(client, reader, settings):
    seed_products(reader)
    settings.pending_max_order_items = 3
    settings.pending_max_order_total = 1000
    register(client)
    r = order(client, items=[{"kala_code": 101, "qty": 2}])
    assert r.status_code == 201
    assert r.json()["customer_pending"] is True
    # the open order counts: 2 + 2 > 3
    assert order(client, items=[{"kala_code": 101, "qty": 2}]).status_code == 422
    assert order(client, items=[{"kala_code": 104, "qty": 1}]).status_code == 201


def test_pending_customer_amount_limit(client, reader, settings):
    seed_products(reader)
    settings.pending_max_order_total = 150
    register(client)
    assert order(client, items=[{"kala_code": 101, "qty": 2}]).status_code == 422


def test_rejected_customer_cannot_order(client, reader):
    seed_products(reader)
    user_id = register(client).json()["id"]
    client.post(f"/admin/users/{user_id}/reject", headers=h("admin"))
    assert order(client).status_code == 403


def test_payment_of_pending_customer_waits_for_approval(client, reader, writer):
    seed_products(reader)
    user_id = register(client).json()["id"]
    order_id = order(client).json()["id"]
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "f1"}, headers=h("bot"))
    r = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))
    assert r.status_code == 409 and "not approved" in r.json()["detail"]
    client.post(f"/admin/users/{user_id}/approve", json={"person_code": 7001}, headers=h("admin"))
    r = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))
    assert r.status_code == 200 and r.json()["status"] == "written"


# ---- receipts -------------------------------------------------------------
def _upload(client, order_id, data, chat_id="111"):
    return client.post(
        f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": chat_id},
        json={"receipt_ref": "file-1", "data_b64": base64.b64encode(data).decode()},
        headers=h("bot"),
    )


def test_receipt_image_is_stored_and_served(client, reader, settings, tmp_path):
    settings.receipts_dir = str(tmp_path)
    seed_products(reader)
    register_and_approve(client)
    order_id = order(client).json()["id"]
    r = _upload(client, order_id, PNG)
    assert r.status_code == 200 and r.json()["has_receipt"] is True
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1 and stored[0].name.startswith(f"order{order_id}_")
    img = client.get(f"/admin/orders/{order_id}/receipt", headers=h("admin"))
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png" and img.content == PNG
    # customers cannot fetch it through the admin route
    assert client.get(f"/admin/orders/{order_id}/receipt", headers=h("bot")).status_code == 403


def test_receipt_rejects_non_images_and_big_files(client, reader, settings, tmp_path):
    settings.receipts_dir = str(tmp_path)
    settings.receipt_max_bytes = 1000
    seed_products(reader)
    register_and_approve(client)
    order_id = order(client).json()["id"]
    assert _upload(client, order_id, b"%PDF-1.4 not an image").status_code == 422
    assert _upload(client, order_id, JPEG + b"0" * 2000).status_code == 422
    assert client.get(f"/orders/{order_id}", params={"platform": "bale", "chat_id": "111"},
                      headers=h("bot")).json()["status"] == "awaiting_payment"
    assert _upload(client, order_id, JPEG).status_code == 200


def test_receipt_helpers():
    assert receipts.sniff(JPEG) == ("image/jpeg", "jpg")
    assert receipts.sniff(b"GIF89a") is None


def test_receipt_resolve_stays_inside_folder(tmp_path):
    (tmp_path / "a.png").write_bytes(PNG)
    assert receipts.resolve(tmp_path, "a.png") is not None
    assert receipts.resolve(tmp_path, "../a.png") is None


# ---- tracking -------------------------------------------------------------
def _written_order(client):
    register_and_approve(client)
    order_id = order(client).json()["id"]
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "f1"}, headers=h("bot"))
    body = client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin")).json()
    return order_id, body["accounting_order_no"]


def test_invoice_sync_partial_then_full(client, reader, db):
    seed_products(reader)
    order_id, codlp = _written_order(client)
    assert tracking.sync_invoices(db, reader) == 0          # not invoiced yet
    reader.invoices = {codlp: {"ordered": 2, "invoiced": 1}}
    assert tracking.sync_invoices(db, reader) == 1
    assert tracking.sync_invoices(db, reader) == 0          # recorded once
    reader.invoices = {codlp: {"ordered": 2, "invoiced": 2}}
    r = client.post("/admin/orders/sync-invoices", headers=h("admin"))
    assert r.json() == {"changed": 1}
    kinds = events(db)
    assert kinds.count("order_partially_invoiced") == 1 and kinds.count("order_invoiced") == 1
    got = client.get(f"/orders/{order_id}", params={"platform": "bale", "chat_id": "111"},
                     headers=h("bot")).json()
    assert got["invoice_state"] == "full"


def test_ship_order(client, reader, db):
    seed_products(reader)
    order_id, _ = _written_order(client)
    r = client.post(f"/admin/orders/{order_id}/ship", headers=h("admin"))
    assert r.status_code == 200 and r.json()["shipped_at"]
    client.post(f"/admin/orders/{order_id}/ship", headers=h("admin"))   # idempotent
    assert events(db).count("order_shipped") == 1


def test_cannot_ship_unpaid_order(client, reader):
    seed_products(reader)
    register_and_approve(client)
    order_id = order(client).json()["id"]
    assert client.post(f"/admin/orders/{order_id}/ship", headers=h("admin")).status_code == 409


# ---- statement ------------------------------------------------------------
def _row(date, debit=0.0, credit=0.0, kind="f"):
    return {"id": 1, "date": date, "kind": kind, "doc_no": "1", "debit": debit,
            "credit": credit, "description": "x" * 100}


def test_statement_running_balance_newest_first(client, reader):
    seed_products(reader)
    register_and_approve(client)
    reader.ledger = {7001: [
        _row("1405/01/01", debit=1000),
        _row("1405/01/02", credit=400, kind="d"),
        _row("1405/01/03", debit=100),
    ]}
    r = client.get("/users/bale/111/statement", params={"page_size": 2}, headers=h("bot"))
    assert r.status_code == 200
    body = r.json()
    assert body["balance"] == 700 and body["side"] == "debtor" and body["total"] == 3
    first, second = body["items"]
    assert first["date"] == "1405/01/03" and first["balance"] == 700
    assert second["kind"] == "سند" and second["balance"] == 600
    assert len(first["description"]) == 60


def test_statement_opening_balance_when_rows_are_cut():
    data = {"rows": [_row("1405/02/01", debit=10)], "total_debit": 510, "total_credit": 0}
    page = build_statement(data, 1, 10)
    assert page["items"][0]["balance"] == 510 and page["balance"] == 510


def test_statement_only_for_approved_bot_customers(client, reader):
    seed_products(reader)
    register(client)
    assert client.get("/users/bale/111/statement", headers=h("bot")).status_code == 403
    assert client.get("/users/bale/999/statement", headers=h("bot")).status_code == 404
    register_and_approve(client, chat_id="222", phone="09120000002")
    assert client.get("/users/bale/222/statement", headers=h("site")).status_code == 403


# ---- closed mode and single product ---------------------------------------
def test_shop_closed_toggle(client, reader, db):
    assert client.get("/shop/state", headers=h("bot")).json()["closed"] is False
    r = client.put("/admin/shop/state", json={"closed": True}, headers=h("admin"))
    assert r.status_code == 200 and r.json()["closed"] is True
    assert client.get("/shop/state", headers=h("bot")).json()["closed"] is True
    assert client.put("/admin/shop/state", json={"closed": False},
                      headers=h("bot")).status_code == 403
    assert "shop_closed" in events(db)


def test_single_product_for_deep_link(client, reader):
    seed_products(reader)
    r = client.get("/products/101", headers=h("bot"))
    assert r.status_code == 200 and r.json()["available_qty"] == 8
    assert client.get("/products/102", headers=h("bot")).json()["available_qty"] == 0
    assert client.get("/products/103", headers=h("bot")).status_code == 404   # price 0
    assert client.get("/products/999", headers=h("bot")).status_code == 404


def test_admin_get_user_and_order_has_user_id(client, reader):
    seed_products(reader)
    user_id = register_and_approve(client)
    assert client.get(f"/admin/users/{user_id}", headers=h("admin")).json()["chat_id"] == "111"
    assert order(client).json()["user_id"] == user_id
