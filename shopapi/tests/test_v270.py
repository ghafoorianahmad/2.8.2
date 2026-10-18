"""v2.7.0: two roles («مدیر» / «کاربر فروش») with per-user ticks enforced by the API,
the old roles migrated, «ارسال شد» with an optional courier, and staff order cancel."""
from __future__ import annotations

import pytest

from app import staff as st
from app.db_own import OwnDB

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff
from .test_staff_auth import add_staff, bearer, login, owner_token
from .test_v260 import events


def _order(client, reader) -> int:
    seed_products(reader)
    register_and_approve(client)
    return client.post("/orders", json={"platform": "bale", "chat_id": "111", "items": [
        {"kala_code": 101, "qty": 1}]}, headers=h("bot")).json()["id"]


# ---- the permission model ------------------------------------------------------------------------
def test_two_roles_and_effective_permissions():
    assert st.STAFF_ROLES == ("super_admin", "operator")
    assert st.PERMISSIONS["super_admin"] == st.ALL_PERMISSIONS
    sales = st.PERMISSIONS["operator"]
    assert {st.P_ORDERS_VIEW, st.P_PAYMENTS_DECIDE, st.P_ORDERS_SHIP, st.P_ORDERS_CANCEL,
            st.P_REQUESTS, st.P_CUSTOMERS_VIEW} <= sales
    for admin_only in (st.P_VIEW, st.P_CUSTOMERS_DECIDE, st.P_SHOP_STATE, st.P_PRICELIST,
                       st.P_CATALOG, st.P_PROXIES, st.P_STAFF_MANAGE, st.P_SERVER_MANAGE):
        assert admin_only not in sales
    eff = st.effective_permissions("operator", "shop.state,bogus", ["orders.cancel"])
    assert st.P_SHOP_STATE in eff and st.P_ORDERS_CANCEL not in eff and "bogus" not in eff
    assert set(st.PERMISSION_LABELS) == set(st.ALL_PERMISSIONS)


def test_old_roles_are_migrated_on_start(tmp_path):
    path = tmp_path / "old.db"
    db = OwnDB(path)
    db.create_staff("boss", "", "admin", "x")
    db.create_staff("look", "", "viewer", "x")
    db._conn.close()
    again = OwnDB(path)
    roles = {r["username"]: r["role"] for r in again.list_staff()}
    assert roles == {"boss": "super_admin", "look": "operator"}


SALES_ALLOWED = [
    ("GET", "/admin/orders"), ("GET", "/admin/users"), ("GET", "/admin/item-requests"),
    ("GET", "/admin/events"), ("GET", "/admin/system-info"),
]
SALES_FORBIDDEN = [
    ("GET", "/admin/product-groups"), ("PUT", "/admin/product-groups"),
    ("GET", "/admin/pricelists"), ("GET", "/admin/pricelists/rows"),
    ("PUT", "/admin/price-mappings"), ("POST", "/admin/price-mappings/auto"),
    ("POST", "/admin/sales/action"), ("PUT", "/admin/shop/state"), ("GET", "/admin/shop/state"),
    ("GET", "/admin/server/settings"), ("GET", "/admin/server/status"),
    ("GET", "/admin/staff"), ("POST", "/admin/staff"), ("GET", "/admin/audit"),
    ("GET", "/admin/catalog-models"), ("GET", "/admin/proxies"),
    ("GET", "/admin/password-requests"), ("GET", "/products"), ("GET", "/groups"),
    ("POST", "/admin/users/1/approve"), ("POST", "/admin/users/1/reject"),
    ("POST", "/admin/orders/expire"), ("GET", "/admin/inquiries"),
]


def test_sales_user_reaches_only_its_pages(client, db, reader):
    seed_products(reader)
    sales = staff(db, "operator", "mina")
    for method, path in SALES_ALLOWED:
        assert client.request(method, path, headers=sales).status_code == 200, path
    for method, path in SALES_FORBIDDEN:
        r = client.request(method, path, headers=sales, json={})
        assert r.status_code == 403, (method, path, r.status_code)
    manager = staff(db, "super_admin", "boss")
    for method, path in (("GET", "/admin/product-groups"), ("GET", "/admin/pricelists"),
                         ("GET", "/admin/staff"), ("GET", "/products")):
        assert client.request(method, path, headers=manager).status_code == 200, path


def test_sales_user_works_orders(client, db, reader):
    order_id = _order(client, reader)
    sales = staff(db, "operator", "mina")
    assert client.post(f"/admin/orders/{order_id}/cancel", headers=sales).status_code == 200
    assert db.get_order(order_id)["status"] == "cancelled"
    assert db.get_order(order_id)["cancel_reason"] == "staff"
    assert "order_cancelled_by_staff" in events(db)


def test_per_user_ticks_are_enforced(client, db, reader):
    seed_products(reader)
    owner = owner_token(client)
    user = add_staff(client, owner, "mina", "operator")
    token = login(client, "mina").json()["token"]
    assert client.get("/admin/shop/state", headers=bearer(token)).status_code == 403
    # grant «باز و بسته کردن فروش» and the read-only view, take «لغو سفارش» away
    r = client.patch(f"/admin/staff/{user['id']}", headers=bearer(owner), json={
        "extra_permissions": ["shop.state", "view"], "removed_permissions": ["orders.cancel"]})
    assert r.status_code == 200
    body = r.json()
    assert body["extra_permissions"] == ["shop.state", "view"]
    assert "orders.cancel" not in body["permissions"] and "shop.state" in body["permissions"]
    # changed rights end the old session at once
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401
    token = login(client, "mina").json()["token"]
    me = client.get("/auth/me", headers=bearer(token)).json()
    assert "shop.state" in me["permissions"] and "orders.cancel" not in me["permissions"]
    assert client.get("/admin/shop/state", headers=bearer(token)).status_code == 200
    assert client.post("/admin/orders/1/cancel", headers=bearer(token)).status_code == 403
    assert client.patch(f"/admin/staff/{user['id']}", headers=bearer(owner),
                        json={"extra_permissions": ["root"]}).status_code == 422
    labels = client.get("/admin/permissions", headers=bearer(owner)).json()
    assert {p["name"] for p in labels} == set(st.ALL_PERMISSIONS)
    assert client.get("/admin/permissions", headers=bearer(token)).status_code == 403


def test_new_users_default_to_sales(client):
    owner = owner_token(client)
    r = client.post("/admin/staff", headers=bearer(owner), json={
        "username": "neda", "full_name": "ندا", "password": "Secret1234"})
    assert r.status_code == 201 and r.json()["role"] == "operator"
    r = client.post("/admin/staff", headers=bearer(owner), json={
        "username": "sami", "password": "Secret1234", "role": "admin"})
    assert r.json()["role"] == "super_admin"                 # old code -> «مدیر»


# ---- shipping ----------------------------------------------------------------------------------
def _paid(client, db, reader) -> int:
    order_id = _order(client, reader)
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "r1"}, headers=h("bot"))
    client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))
    return order_id


def test_ship_with_courier(client, db, reader):
    order_id = _paid(client, db, reader)
    sales = staff(db, "operator", "mina")
    r = client.post(f"/admin/orders/{order_id}/ship", headers=sales,
                    json={"courier_name": "  علی   پیک ", "courier_phone": "۰۹۱۲ ۳۴۵ ۶۷۸۹"})
    assert r.status_code == 200, r.text
    assert r.json()["courier_name"] == "علی پیک" and r.json()["courier_phone"] == "09123456789"
    assert r.json()["shipped_at"] and "order_shipped" in events(db)


def test_ship_without_courier_and_bad_phone(client, db, reader):
    order_id = _paid(client, db, reader)
    manager = staff(db)
    assert client.post(f"/admin/orders/{order_id}/ship", headers=manager,
                       json={"courier_phone": "12"}).status_code == 422
    r = client.post(f"/admin/orders/{order_id}/ship", headers=manager)       # no body at all
    assert r.status_code == 200
    assert r.json()["courier_name"] is None and r.json()["courier_phone"] is None


@pytest.mark.parametrize("status_value", ["approved", "written"])
def test_staff_cannot_cancel_a_confirmed_order(client, db, reader, status_value):
    order_id = _order(client, reader)
    db._conn.execute("UPDATE orders SET status=? WHERE id=?", (status_value, order_id))
    db._conn.commit()
    assert client.post(f"/admin/orders/{order_id}/cancel",
                       headers=staff(db)).status_code == 409
