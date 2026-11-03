"""v2.4.0: version sync, forgot-password flow, reset to 12345, console login, test-DB mode."""
from __future__ import annotations

import re
from pathlib import Path

from app import control
from app.config import Settings
from app.staff import DEFAULT_RESET_PASSWORD, verify_password

from .conftest import h
from .test_staff_auth import PW, add_staff, bearer, login, owner_token

ROOT = Path(__file__).resolve().parents[2]


# ---- version -----------------------------------------------------------------
def test_server_and_installer_versions_match():
    iss = (ROOT / "shopadmin" / "installer" / "ShopAdmin.iss").read_text(encoding="utf-8")
    match = re.search(r'^#define\s+MyAppVersion\s+"([^"]+)"', iss, re.MULTILINE)
    assert match, "MyAppVersion not found in ShopAdmin.iss"
    assert control.VERSION == match.group(1)
    assert control.VERSION == "2.18.0"


# ---- forgot password ---------------------------------------------------------
def forgot(client, username):
    r = client.post("/auth/forgot", json={"username": username})
    assert r.status_code == 200, r.text
    return r.json()


def status_of(client, req):
    return client.post("/auth/forgot/status", json={
        "request_id": req["request_id"], "token": req["token"]}).json()["status"]


def complete(client, req, password):
    return client.post("/auth/forgot/complete", json={
        "request_id": req["request_id"], "token": req["token"], "new_password": password})


def test_forgot_flow_approve_then_choose_new_password(client):
    owner = owner_token(client)
    add_staff(client, owner, "sara", "operator")
    old = login(client, "sara").json()["token"]
    req = forgot(client, "sara")
    assert status_of(client, req) == "pending"
    assert complete(client, req, "Brandnew99").status_code == 403  # not approved yet

    pending = client.get("/admin/password-requests", headers=bearer(owner)).json()
    assert [p["username"] for p in pending] == ["sara"]
    assert client.post(f"/admin/password-requests/{pending[0]['id']}/approve",
                       headers=bearer(owner)).status_code == 200
    assert status_of(client, req) == "approved"

    assert complete(client, req, "short").status_code == 422        # policy still applies
    assert complete(client, req, PW).status_code == 422             # not the old one
    assert complete(client, req, "Brandnew99").status_code == 200
    assert status_of(client, req) == "used"
    assert complete(client, req, "Another123").status_code == 403   # single use

    assert login(client, "sara", PW).status_code == 401             # old password dead
    assert login(client, "sara", "Brandnew99").status_code == 200
    assert client.get("/auth/me", headers=bearer(old)).status_code == 401  # old sessions gone
    assert client.get("/admin/password-requests", headers=bearer(owner)).json() == []


def test_forgot_reject_and_wrong_token(client):
    owner = owner_token(client)
    add_staff(client, owner, "sara", "operator")
    req = forgot(client, "sara")
    rid = client.get("/admin/password-requests", headers=bearer(owner)).json()[0]["id"]
    assert client.post(f"/admin/password-requests/{rid}/reject",
                       headers=bearer(owner)).status_code == 200
    assert status_of(client, req) == "rejected"
    assert complete(client, req, "Brandnew99").status_code == 403
    # a wrong secret reveals nothing
    bad = {"request_id": req["request_id"], "token": "nope"}
    assert status_of(client, bad) == "pending"
    assert complete(client, bad, "Brandnew99").status_code == 403


def test_forgot_unknown_user_looks_identical(client):
    owner = owner_token(client)
    fake = forgot(client, "nobody")
    assert set(fake) == {"request_id", "token"}
    assert status_of(client, fake) == "pending"
    assert client.get("/admin/password-requests", headers=bearer(owner)).json() == []


def test_forgot_permissions(client):
    owner = owner_token(client)
    add_staff(client, owner, "adm", "admin")
    add_staff(client, owner, "opr", "operator")
    adm = login(client, "adm").json()["token"]
    op = login(client, "opr").json()["token"]
    forgot(client, "opr")
    forgot(client, "owner")
    assert client.get("/admin/password-requests", headers=bearer(op)).status_code == 403
    # an admin sees (and may decide) staff requests, never a super admin's
    seen = client.get("/admin/password-requests", headers=bearer(adm)).json()
    # v2.7.0: "admin" is a «مدیر» now and sees every request
    assert sorted(p["username"] for p in seen) == ["opr", "owner"]
    all_ids = {p["username"]: p["id"] for p in
               client.get("/admin/password-requests", headers=bearer(owner)).json()}
    assert client.post(f"/admin/password-requests/{all_ids['opr']}/approve",
                       headers=bearer(op)).status_code == 403          # a sales user never
    assert client.post(f"/admin/password-requests/{all_ids['opr']}/approve",
                       headers=bearer(adm)).status_code == 200


def test_forgot_new_request_replaces_old_and_event(client, db):
    owner = owner_token(client)
    add_staff(client, owner, "sara", "operator")
    first = forgot(client, "sara")
    second = forgot(client, "sara")
    assert status_of(client, first) == "expired"
    assert status_of(client, second) == "pending"
    assert any(e["kind"] == "password_request" for e in db.list_events(0))


def test_forgot_tokens_stored_hashed(client, db):
    owner = owner_token(client)
    add_staff(client, owner, "sara", "operator")
    req = forgot(client, "sara")
    row = db.get_password_request(req["request_id"])
    assert req["token"] not in row.values() and row["token_hash"] != req["token"]


# ---- super admin sets / resets passwords -----------------------------------------
def test_reset_to_default_forces_change(client):
    owner = owner_token(client)
    user = add_staff(client, owner, "sara", "operator")
    sara = login(client, "sara").json()["token"]
    r = client.post(f"/admin/staff/{user['id']}/reset-default", headers=bearer(owner))
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert client.get("/auth/me", headers=bearer(sara)).status_code == 401
    out = login(client, "sara", DEFAULT_RESET_PASSWORD)
    assert out.status_code == 200 and out.json()["user"]["must_change_password"] is True
    tok = out.json()["token"]
    # nothing but the password change works until it is done
    assert client.get("/admin/orders", headers=bearer(tok)).status_code == 403
    assert client.post("/auth/change-password", headers=bearer(tok), json={
        "current_password": DEFAULT_RESET_PASSWORD, "new_password": "12345"}).status_code == 422
    assert client.post("/auth/change-password", headers=bearer(tok), json={
        "current_password": DEFAULT_RESET_PASSWORD, "new_password": "Fresh12345"}).status_code == 200
    assert login(client, "sara", DEFAULT_RESET_PASSWORD).status_code == 401
    assert login(client, "sara", "Fresh12345").json()["user"]["must_change_password"] is False


def test_reset_default_super_admin_only_and_hashed(client, db):
    owner = owner_token(client)
    user = add_staff(client, owner, "sara", "operator")
    adm = add_staff(client, owner, "adm", "operator")
    admin_tok = login(client, "adm").json()["token"]
    assert client.post(f"/admin/staff/{user['id']}/reset-default",
                       headers=bearer(admin_tok)).status_code == 403
    client.post(f"/admin/staff/{user['id']}/reset-default", headers=bearer(owner))
    stored = db.get_staff(user["id"])["password_hash"]
    assert stored.startswith("scrypt$") and DEFAULT_RESET_PASSWORD not in stored
    assert verify_password(DEFAULT_RESET_PASSWORD, stored)
    assert adm["id"]


def test_super_admin_sets_chosen_password(client):
    owner = owner_token(client)
    user = add_staff(client, owner, "sara", "operator")
    r = client.post(f"/admin/staff/{user['id']}/password", headers=bearer(owner),
                    json={"password": "Chosen12345", "must_change_password": False})
    assert r.status_code == 200
    assert login(client, "sara", "Chosen12345").status_code == 200


# ---- server edition console login --------------------------------------------------
def test_console_login(client, monkeypatch):
    owner_token(client)
    assert client.post("/auth/console-login", headers=h("admin")).status_code == 403  # not loopback
    monkeypatch.setattr("app.routers.auth.is_local_request", lambda _r: True)
    assert client.post("/auth/console-login", headers=h("bot")).status_code == 403
    assert client.post("/auth/console-login").status_code == 401
    r = client.post("/auth/console-login", headers=h("admin"))
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "super_admin"
    assert client.get("/auth/me", headers=bearer(body["token"])).status_code == 200


def test_console_login_needs_a_super_admin(client, monkeypatch):
    monkeypatch.setattr("app.routers.auth.is_local_request", lambda _r: True)
    assert client.post("/auth/console-login", headers=h("admin")).status_code == 409


# ---- test-database mode ------------------------------------------------------------
def test_test_db_enables_writes_without_a_switch():
    # v2.8.1: no built-in test database; a LISTED test copy still needs no switch
    listed = dict(accounting_test_databases=("hesab5 t",))
    test = Settings(accounting_database="hesab5 t", accounting_write_enabled=False,
                    accounting_server="some-other-host", **listed)
    assert test.is_test_db() and test.write_allowed()
    assert Settings(accounting_database="HESAB5 T ", **listed).write_allowed()
    assert not Settings(accounting_database="hesab5 t").write_allowed()
    prod = Settings(accounting_database="hesab5", accounting_write_enabled=False)
    assert not prod.is_test_db() and not prod.write_allowed()
    # production still needs the switch AND an allowed host
    on = Settings(accounting_database="hesab5", accounting_write_enabled=True,
                  accounting_server="some-other-host")
    assert not on.write_allowed()


def test_system_info_reports_test_mode(client, settings):
    owner = owner_token(client)
    settings.accounting_database = "hesab5 t"
    settings.accounting_test_databases = ("hesab5 t",)
    info = client.get("/admin/system-info", headers=bearer(owner)).json()
    assert info["test_mode"] is True and info["accounting_write_enabled"] is True
    assert info["write_allowed_on_host"] is True
