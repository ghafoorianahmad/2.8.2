"""v2.8.2: per-section permissions (migrated), visibility everywhere, payment
details per order, no «برمی‌دارم», the bot's dry checkout check."""
from __future__ import annotations

from app import staff as st
from app.db_own import OwnDB

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff
from .test_v260 import events


def _order(client, chat_id="111") -> int:
    r = client.post("/orders", json={"platform": "bale", "chat_id": chat_id, "items": [
        {"kala_code": 101, "qty": 1}]}, headers=h("bot"))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- 10: sections, «تغییر» implies «دیدن», old ticks migrated ------------------------------------
def test_sections_and_labels():
    assert st.ALL_PERMISSIONS == set(st.PERMISSION_LABELS)
    assert "assign.view" not in st.ALL_PERMISSIONS and "assign.edit" in st.ALL_PERMISSIONS
    assert st.with_implied({"groups.edit"}) == {"groups.edit", "groups.view"}
    eff = st.effective_permissions("operator", "pricelist.edit", "")
    assert {"pricelist.edit", "pricelist.view", "events.view"} <= eff


def test_old_ticks_are_migrated_on_start(tmp_path):
    path = tmp_path / "old.db"
    db = OwnDB(path)
    sales = db.create_staff("mina", "", "operator", "x")
    boss = db.create_staff("boss", "", "super_admin", "x")
    plain = db.create_staff("reza", "", "operator", "x")
    db.update_staff(sales["id"], perm_grant="view,shop.state,orders.assign",
                    perm_revoke="requests.handle")
    db.update_staff(boss["id"], perm_grant="", perm_revoke="server.manage,staff.manage")
    db._conn.close()
    again = OwnDB(path)
    mina = again.get_staff(sales["id"])
    eff = st.effective_permissions(mina["role"], mina["perm_grant"], mina["perm_revoke"])
    assert {"dashboard.view", "products.view", "reports.view", "sales.edit", "assign.edit",
            "orders.edit"} <= eff
    assert "requests.view" not in eff and "requests.edit" not in eff
    chief = again.get_staff(boss["id"])
    eff = st.effective_permissions(chief["role"], chief["perm_grant"], chief["perm_revoke"])
    assert "server.edit" not in eff and "staff.edit" not in eff and "orders.edit" in eff
    assert again.get_staff(plain["id"])["perm_grant"] == ""              # nothing to move
    again._conn.close()
    assert OwnDB(path).get_staff(sales["id"])["perm_grant"] == mina["perm_grant"]  # idempotent


def test_view_without_edit_is_read_only(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    client.post("/item-requests", json={"platform": "bale", "chat_id": "111",
                                        "text": "گوشی"}, headers=h("bot"))
    looker = staff(db, "operator", "looker")
    row = db.get_staff_by_username("looker")
    db.update_staff(row["id"], perm_revoke="requests.edit,orders.edit")
    items = client.get("/admin/item-requests", headers=looker)
    assert items.status_code == 200
    req_id = items.json()[0]["id"]
    assert client.put(f"/admin/item-requests/{req_id}/note", json={"note": "x"},
                      headers=looker).status_code == 403
    order_id = _order(client)
    assert client.post(f"/admin/orders/{order_id}/payment-info", headers=looker,
                       json={"card_number": "6037991122334455"}).status_code == 403
    assert client.get("/admin/permission-sections", headers=looker).status_code == 403
    sections = client.get("/admin/permission-sections",
                          headers=staff(db, "super_admin", "boss")).json()
    assert sections[0] == {"key": "dashboard", "label": "داشبورد", "view": "dashboard.view",
                           "edit": None}


# ---- 8: no «برمی‌دارم»; the first action takes; the second user is told -------------------------
def test_claim_is_gone_and_payment_details_take_the_order(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    order_id = _order(client)
    mina, sara = staff(db, "operator", "mina"), staff(db, "operator", "sara")
    assert client.post(f"/admin/orders/{order_id}/claim", headers=mina).status_code in (404, 405)
    # opening does not take it
    assert client.get(f"/admin/orders/{order_id}", headers=mina).status_code == 200
    assert db.get_order(order_id)["owner_id"] is None
    r = client.post(f"/admin/orders/{order_id}/payment-info", headers=mina, json={
        "card_number": "۶۰۳۷ ۹۹۱۱ ۲۲۳۳ ۴۴۵۵", "holder": "  فروشگاه  ", "bank": "",
        "sheba": "12 3456 7890 1234 5678 9012 34"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["owned_by_me"] and body["reserve_until"] and body["payment_info_at"]
    assert body["payment_info"] == {"card_number": "6037-9911-2233-4455", "holder": "فروشگاه",
                                    "sheba": "IR123456789012345678901234"}
    assert "order_payment_info" in events(db)
    # sara is too late: the order is no longer hers to see or touch
    assert client.post(f"/admin/orders/{order_id}/payment-info", headers=sara,
                       json={"card_number": "6037991122334455"}).status_code == 404
    steps = client.get(f"/admin/orders/{order_id}/timeline", headers=mina).json()
    assert [s["action"] for s in steps] == ["claim", "payment_info"]


def test_payment_details_are_checked(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    order_id = _order(client)
    boss = staff(db, "super_admin", "boss")
    url = f"/admin/orders/{order_id}/payment-info"
    for body, word in (({"holder": "x"}, "Enter a card"), ({"card_number": "1234"}, "16-digit"),
                       ({"sheba": "IR12"}, "sheba")):
        r = client.post(url, json=body, headers=boss)
        assert r.status_code == 422 and word in r.json()["detail"]
    assert client.post(url, json={"account_number": "0123-456"}, headers=boss).status_code == 200
    # the manager's action also takes a free order
    assert db.get_order(order_id)["owner_id"] == db.get_staff_by_username("boss")["id"]
    client.post(f"/admin/orders/{order_id}/cancel", headers=boss)
    assert client.post(url, json={"account_number": "1"}, headers=boss).status_code == 409


def test_order_without_payment_details_never_times_out(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    order_id = _order(client)
    assert db.get_order(order_id)["reserve_until"] is None
    assert db.overdue_awaiting_orders("9999-01-01T00:00:00+00:00") == []


def test_bot_check_creates_nothing(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    r = client.post("/orders", params={"check": "true"}, json={
        "platform": "bale", "chat_id": "111", "items": [{"kala_code": 101, "qty": 1}]},
        headers=h("bot"))
    assert r.status_code == 200 and r.json()["status"] == "check" and r.json()["id"] == 0
    assert db.query_orders() == [] and "order_created" not in events(db)
    r = client.post("/orders", params={"check": "true"}, json={
        "platform": "bale", "chat_id": "111", "items": [{"kala_code": 101, "qty": 999}]},
        headers=h("bot"))
    assert r.status_code == 409 and "stock" in r.json()["detail"]


# ---- 9: a sales user sees their own work and new work only ---------------------------------------
def test_visibility_of_orders_customers_and_events(client, db, reader):
    seed_products(reader)
    reader.person_codes = {7001, 7002}
    register_and_approve(client)
    register_and_approve(client, chat_id="222", person_code=7002, phone="09120000002")
    mine_id, other_id = _order(client), _order(client, "222")
    mina, sara = staff(db, "operator", "mina"), staff(db, "operator", "sara")
    boss = staff(db, "super_admin", "boss")
    cursor = client.get("/admin/events", headers=mina).json()["last_id"]
    for who, oid in ((mina, mine_id), (sara, other_id)):
        assert client.post(f"/admin/orders/{oid}/payment-info", headers=who,
                           json={"card_number": "6037991122334455"}).status_code == 200
    listed = [o["id"] for o in client.get("/admin/orders", params={"status": "awaiting_payment"},
                                          headers=mina).json()]
    assert listed == [mine_id]
    all_ids = {o["id"] for o in client.get("/admin/orders", params={"status": "awaiting_payment"},
                                           headers=boss).json()}
    assert all_ids == {mine_id, other_id}
    # customers: only the one of her own order
    names = {u["chat_id"] for u in client.get("/admin/users", headers=mina).json()}
    assert names == {"111"}
    other_user = db.get_order(other_id)["user_id"]
    assert client.get(f"/admin/users/{other_user}", headers=mina).status_code == 404
    assert len(client.get("/admin/users", headers=boss).json()) == 2
    # the notification feed tells her about her own order only
    feed = client.get("/admin/events", params={"after": cursor}, headers=mina).json()["items"]
    refs = {(e["kind"], e["ref_id"]) for e in feed}
    assert ("order_payment_info", mine_id) in refs and ("order_payment_info", other_id) not in refs
    # finished and nobody's: not «new work» any more
    db.set_owner("order", other_id, None)
    client.post(f"/admin/orders/{other_id}/cancel", headers=boss)
    assert client.get(f"/admin/orders/{other_id}", headers=mina).status_code == 404


def test_no_fixed_payment_settings():
    from app import control

    for key in ("PAYMENT_CARD_NUMBER", "PAYMENT_SHEBA", "PAYMENT_OWNER", "BANK_ACCOUNT_TEXT"):
        assert key not in control.EDITABLE
