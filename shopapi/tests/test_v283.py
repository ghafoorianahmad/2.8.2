"""v2.8.3: own activity only, no ownerless finished work for sales users, no
colleague names, payment-info reminders, nightly archive of abandoned orders,
always-on daily work, «انتقال همهٔ کارهای باز»."""
from __future__ import annotations

from datetime import datetime, timezone

from app import archive
from app import staff as st
from app.db_own import OwnDB

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff


def _order(client, chat_id="111") -> int:
    r = client.post("/orders", json={"platform": "bale", "chat_id": chat_id, "items": [
        {"kala_code": 101, "qty": 1}]}, headers=h("bot"))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sid(db, username: str) -> int:
    return int(db.get_staff_by_username(username)["id"])


# ---- 1: «گزارش فعالیت» of a non-manager = their own actions only ----------------------------------
def test_activity_of_a_sales_user_is_only_their_own(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    mina = staff(db, "operator", "mina")
    reza = staff(db, "operator", "reza")
    for name in ("mina", "reza"):
        db.update_staff(_sid(db, name), perm_grant="activity.view")
    first, second = _order(client), _order(client)
    assert client.post(f"/admin/orders/{first}/cancel", headers=mina).status_code == 200
    assert client.post(f"/admin/orders/{second}/cancel", headers=reza).status_code == 200
    # handed from reza to mina by the manager: still not «her» action
    boss = staff(db, "super_admin", "boss")
    third = _order(client)
    client.post(f"/admin/orders/{third}/payment-info", headers=reza,
                json={"card_number": "6037991122334455"})
    assert client.post(f"/admin/orders/{third}/assign", headers=boss,
                       json={"staff_id": _sid(db, "mina")}).status_code == 200
    rows = client.get("/admin/activity", headers=mina,
                      params={"staff_id": _sid(db, "reza")}).json()
    assert rows and all(r["is_me"] for r in rows)
    assert {r["target_id"] for r in rows} == {first}
    assert all(r["actor_name"] is None and r["to_name"] is None for r in rows)
    everything = client.get("/admin/activity", headers=boss).json()
    moved = [r for r in everything if r["action"] == "assign"]
    assert moved and moved[0]["from_name"] == "Test" and moved[0]["to_name"] == "Test"


# ---- 2: ownerless finished / accepted orders are the manager's only ------------------------------
def test_ownerless_written_orders_are_hidden_from_sales_users(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    open_id, done_id = _order(client), _order(client)
    db.set_order_status(done_id, "written")
    sales = staff(db, "operator", "mina")
    seen = {o["id"] for o in client.get("/admin/orders", params={"status": ""},
                                        headers=sales).json()}
    assert open_id in seen and done_id not in seen
    assert client.get(f"/admin/orders/{done_id}", headers=sales).status_code == 404
    boss = staff(db, "super_admin", "boss")
    assert done_id in {o["id"] for o in client.get("/admin/orders", params={"status": ""},
                                                   headers=boss).json()}
    # once it is hers it is visible again
    db.set_owner("order", done_id, _sid(db, "mina"))
    assert client.get(f"/admin/orders/{done_id}", headers=sales).status_code == 200


# ---- 3: who opened / closed phone sales: a name for the manager only ------------------------------
def test_sales_override_name_is_hidden(client, db, reader):
    seed_products(reader)
    boss = staff(db, "super_admin", "boss")
    assert client.post("/admin/sales/action", json={"action": "close"},
                       headers=boss).status_code == 200
    sales = staff(db, "operator", "mina")
    state = client.get("/admin/shop/state", headers=sales).json()
    assert state["override_by"] == ""
    assert "boss" in client.get("/admin/shop/state", headers=boss).json()["override_by"]
    db.update_staff(_sid(db, "mina"), perm_grant="sales.edit")
    mine = client.post("/admin/sales/action", json={"action": "open"}, headers=sales).json()
    assert mine["override_by"] == "شما"


# ---- 5: payment-info reminders ---------------------------------------------------------------------
def test_payment_info_due_goes_to_owner_or_everyone(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    free, taken, done = _order(client), _order(client), _order(client)
    mina = staff(db, "operator", "mina")
    reza = staff(db, "operator", "reza")
    boss = staff(db, "super_admin", "boss")
    db.set_owner("order", taken, _sid(db, "reza"))
    assert client.post(f"/admin/orders/{done}/payment-info", headers=mina,
                       json={"card_number": "6037991122334455"}).status_code == 200

    def due(headers):
        r = client.get("/admin/orders/payment-info-due", headers=headers)
        assert r.status_code == 200, r.text
        return {o["id"] for o in r.json()}

    assert due(mina) == {free}
    assert due(reza) == {free, taken}
    assert due(boss) == {free}               # reza's own order is reza's reminder
    # never cancelled because nobody sent the details
    from app import order_timeout

    assert order_timeout.cancel_overdue(db) == []
    assert db.get_order(free)["status"] == "awaiting_payment"


# ---- 7: nightly archive of abandoned, ownerless orders ---------------------------------------------
def test_nightly_archive_of_abandoned_orders(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    by_customer, lapsed, owned, open_id = (_order(client) for _ in range(4))
    db.cancel_order_locally(by_customer, "customer")
    db.cancel_order_locally(lapsed, "receipt_timeout")
    db.cancel_order_locally(owned, "customer")
    db.set_owner("order", owned, db.create_staff("mina", "", "operator", "x")["id"])
    request = db.add_item_request(db.get_order(by_customer)["user_id"], None, "x", "x")
    db.update_item_request(request["id"], order_id=by_customer)
    late = datetime(2099, 1, 1, 0, 30, tzinfo=timezone.utc)
    counts = archive.run_nightly_due(db, now=late)
    assert counts == {"orders": 2, "requests": 1}
    assert db.get_order(by_customer)["archived_at"] and db.get_order(lapsed)["archived_at"]
    assert not db.get_order(owned)["archived_at"] and not db.get_order(open_id)["archived_at"]
    assert archive.run_nightly_due(db, now=late) is None            # once per night
    boss = staff(db, "super_admin", "boss")
    archived = {o["id"] for o in client.get("/admin/archive/orders", headers=boss).json()}
    assert {by_customer, lapsed} <= archived


def test_nightly_due_time():
    noon = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)          # 11:30 Tehran
    due = archive.last_nightly_due(noon).astimezone(archive.TEHRAN)
    assert (due.day, due.hour, due.minute) == (20, 23, 59)


# ---- 9: always-on daily work, migrated -------------------------------------------------------------
def test_always_on_sections_are_not_ticks(tmp_path):
    assert not {key for key, *_ in st.SECTIONS} & st.ALWAYS_SECTIONS
    assert {"dashboard.view", "orders.view", "orders.edit", "requests.view", "requests.edit",
            "archive.view", "reports.view", "customers.view", "customers.edit",
            "assign.edit"} == set(st.ALWAYS_PERMISSIONS)
    path = tmp_path / "old.db"
    db = OwnDB(path)
    row = db.create_staff("mina", "", "operator", "x")
    db.update_staff(row["id"], perm_grant="pricelist.edit,assign.edit",
                    perm_revoke="orders.edit,customers.edit,groups.view")
    db._conn.close()
    again = OwnDB(path).get_staff(row["id"])
    assert again["perm_grant"] == "pricelist.edit" and again["perm_revoke"] == "groups.view"
    eff = st.effective_permissions(again["role"], again["perm_grant"], again["perm_revoke"])
    assert st.ALWAYS_PERMISSIONS <= eff and "pricelist.edit" in eff
    assert "products.view" not in eff


def test_dashboard_does_not_open_the_catalog(client, db, reader):
    seed_products(reader)
    sales = staff(db, "operator", "mina")
    assert client.get("/products", headers=sales).status_code == 403
    assert client.get("/admin/product-groups", headers=sales).status_code == 403


# ---- 10: «انتقال همهٔ کارهای باز» -------------------------------------------------------------------
def test_transfer_all_open_work(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    mina = staff(db, "operator", "mina")
    staff(db, "operator", "reza")
    boss = staff(db, "super_admin", "boss")
    first, second, finished = _order(client), _order(client), _order(client)
    for order_id in (first, second, finished):
        db.set_owner("order", order_id, _sid(db, "mina"))
    client.post(f"/admin/orders/{finished}/cancel", headers=mina)
    request = db.add_item_request(db.get_order(first)["user_id"], None, "x", "x")
    db.set_owner("request", request["id"], _sid(db, "mina"))
    url = f"/admin/staff/{_sid(db, 'mina')}/transfer-open"
    assert client.post(url, json={"staff_id": _sid(db, "reza")}, headers=mina).status_code == 403
    assert client.post(url, json={"staff_id": _sid(db, "mina")}, headers=boss).status_code == 422
    r = client.post(url, json={"staff_id": _sid(db, "reza")}, headers=boss)
    assert r.status_code == 200 and r.json() == {"orders": 2, "requests": 1}
    assert db.get_order(first)["owner_id"] == _sid(db, "reza")
    assert db.get_order(finished)["owner_id"] == _sid(db, "mina")
    history = client.get(f"/admin/orders/{first}/timeline", headers=boss).json()
    assert history[-1]["action"] == "assign" and "bulk" in history[-1]["detail"]
    assert history[-1]["from_name"] and history[-1]["to_name"]
