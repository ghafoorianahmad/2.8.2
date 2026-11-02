"""v2.17.0 #15: every page, section and action has its own tick. Only signing in and
out and changing one's own password need none; «مدیر» always has everything."""
from __future__ import annotations

import re

import pytest

from app import staff as st
from app.db_own import OwnDB
from app.main import app
from tests.conftest import register_and_approve, seed_products
from tests.test_v280 import staff

#: Asked for by the owner by name: each has a tick of its own.
NAMED = ("site.view", "site.edit", "staff_alerts.view", "staff_alerts.edit",
         "status_codes.view", "status_codes.edit", "work_hours.view", "work_hours.edit",
         "auto_invoice.view", "auto_invoice.edit", "acctwrite.edit", "claim.edit",
         "health.view", "app_settings.view", "app_settings.edit", "proxies.edit",
         "reports_export.edit", "receipts.edit", "payinfo.edit", "ship.edit", "cancel.edit")

#: Administration and settings: a new user never starts with these.
ADMIN_SECTIONS = ("staff", "server", "health", "status_codes", "work_hours", "auto_invoice",
                  "app_settings", "passwords", "activity", "site", "models", "groups",
                  "pricelist", "proxies", "sales")

#: Signed-in plumbing that holds no page of its own: the feed filters itself per user,
#: system-info feeds the yellow banner.
NEEDS_NO_TICK = {("GET", "/admin/events"), ("GET", "/admin/system-info")}


def test_each_named_part_has_its_own_tick():
    assert set(NAMED) <= st.ALL_PERMISSIONS


def test_a_new_user_has_no_admin_or_settings_section():
    sales = st.effective_permissions("operator")
    for section in ADMIN_SECTIONS:
        assert not {p for p in sales if p.split(".", 1)[0] == section}, section
    assert "acctwrite.edit" not in sales


def test_the_manager_always_has_everything():
    every = st.effective_permissions("super_admin", "", ",".join(st.ALL_PERMISSIONS))
    assert st.ALL_PERMISSIONS <= every


def test_every_daily_tick_can_be_taken_away():
    for name in st.PERMISSIONS["operator"]:
        assert name not in st.effective_permissions("operator", "", name), name


def test_taking_a_page_takes_its_actions():
    eff = st.effective_permissions("operator", "", "orders.view")
    assert not {"orders.view", "receipts.edit", "payinfo.edit", "ship.edit", "cancel.edit"} & eff
    assert "requests.view" in eff


def test_an_action_brings_its_page():
    eff = st.effective_permissions("operator", "acctwrite.edit", "")
    assert "orders.view" in eff
    assert "pricelist.view" in st.effective_permissions("operator", "proxies.edit", "")


@pytest.fixture()
def no_ticks(client, db):
    headers = staff(db, "operator", "nobody")
    row = db.get_staff_by_username("nobody")
    db.update_staff(row["id"], perm_revoke=",".join(sorted(st.PERMISSIONS["operator"])))
    return headers


def _routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/admin"):
            continue
        for method in sorted(getattr(route, "methods", ()) - {"HEAD", "OPTIONS"}):
            yield method, path


def test_a_user_without_ticks_is_refused_everywhere(client, no_ticks):
    """Walks every /admin route, so a new endpoint without a check fails here."""
    open_routes = []
    for method, path in _routes():
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url, headers=no_ticks,
                                  json={} if method != "GET" else None)
        if response.status_code not in (403, 404) and (method, path) not in NEEDS_NO_TICK:
            # 422 means the body was read before any check: also a hole
            open_routes.append((method, path, response.status_code))
    assert open_routes == []


def test_refused_404_is_only_for_a_row_not_a_section(client, no_ticks, reader):
    seed_products(reader)
    assert client.get("/admin/orders", headers=no_ticks).status_code == 403
    assert client.get("/admin/users", headers=no_ticks).status_code == 403
    assert client.get("/admin/item-requests", headers=no_ticks).status_code == 403


def test_own_password_needs_no_tick(client, no_ticks):
    assert client.get("/auth/me", headers=no_ticks).status_code == 200


def test_the_feed_is_filtered_by_ticks(client, db, no_ticks, reader):
    seed_products(reader)
    register_and_approve(client)
    db.add_event("item_request", 1, "x")
    last = client.get("/admin/events?after=0", headers=no_ticks).json()
    assert [e for e in last["items"] if e["kind"] in ("item_request", "customer_registered")] == []


def test_existing_users_keep_what_they_had_once(tmp_path):
    path = tmp_path / "old.db"
    db = OwnDB(path)
    mina = db.create_staff("mina", "", "operator", "x")
    boss = db.create_staff("boss", "", "super_admin", "x")
    db.update_staff(mina["id"], perm_grant="server.edit,models.edit,pricelist.edit")
    db._conn.execute("DELETE FROM shop_state WHERE key='permissions_2170'")
    db._conn.commit()
    db._conn.close()
    again = OwnDB(path)
    row = again.get_staff(mina["id"])
    eff = st.effective_permissions(row["role"], row["perm_grant"], row["perm_revoke"])
    assert {"app_settings.view", "app_settings.edit", "proxies.edit", "site.edit",
            "status_codes.edit", "work_hours.edit", "health.view"} <= eff
    assert again.get_staff(boss["id"])["perm_grant"] == ""
    # once only: a tick the manager takes away later does not come back
    again.update_staff(mina["id"], perm_grant="server.edit")
    again._conn.close()
    assert OwnDB(path).get_staff(mina["id"])["perm_grant"] == "server.edit"


def test_a_user_created_after_the_upgrade_gets_no_settings(tmp_path):
    db = OwnDB(tmp_path / "new.db")
    row = db.create_staff("new", "", "operator", "x")
    eff = st.effective_permissions(row["role"], row.get("perm_grant"), row.get("perm_revoke"))
    assert "app_settings.view" not in eff and "server.view" not in eff
