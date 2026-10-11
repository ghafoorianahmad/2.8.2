"""Staff accounts, sessions, server-side roles, key locality and the event feed."""
from __future__ import annotations

import pytest

from app.staff import hash_password, hash_token, verify_password, validate_password

from .conftest import h, register_and_approve, seed_products

PW = "Secret123"


def bootstrap(client, username="owner", password=PW):
    return client.post("/auth/bootstrap", headers=h("admin"),
                       json={"username": username, "full_name": "Owner", "password": password})


def login(client, username="owner", password=PW, remember=False):
    return client.post("/auth/login", json={"username": username, "password": password,
                                            "remember": remember, "client": "pytest"})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def owner_token(client):
    assert bootstrap(client).status_code == 201
    return login(client).json()["token"]


def add_staff(client, token, username, role, must_change=False, password=PW):
    r = client.post("/admin/staff", headers=bearer(token), json={
        "username": username, "full_name": username, "role": role,
        "password": password, "must_change_password": must_change})
    assert r.status_code == 201, r.text
    return r.json()


# ---- hashing / validation --------------------------------------------------
def test_password_hash_roundtrip_and_salt():
    a, b = hash_password(PW), hash_password(PW)
    assert a != b and a.startswith("scrypt$")
    assert verify_password(PW, a) and not verify_password("wrong", a)
    assert not verify_password(PW, "garbage")


def test_password_policy():
    assert validate_password("short1")
    assert validate_password("onlyletters")
    assert validate_password("12345678")
    assert validate_password(PW) is None


# ---- bootstrap ---------------------------------------------------------------
def test_bootstrap_status_and_once_only(client):
    assert client.get("/auth/status").json() == {"bootstrap_required": True}
    assert bootstrap(client).status_code == 201
    assert client.get("/auth/status").json() == {"bootstrap_required": False}
    assert bootstrap(client, "second").status_code == 409


def test_bootstrap_requires_service_key(client):
    assert client.post("/auth/bootstrap", headers=h("bot"),
                       json={"username": "x1x", "password": PW}).status_code == 403
    assert client.post("/auth/bootstrap",
                       json={"username": "x1x", "password": PW}).status_code == 401


def test_bootstrap_validates(client):
    assert bootstrap(client, username="a b").status_code == 422
    assert bootstrap(client, password="weak").status_code == 422


# ---- login -------------------------------------------------------------------
def test_login_success_and_token_stored_hashed(client, db):
    bootstrap(client)
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "super_admin" and "staff.manage" in body["permissions"]
    token = body["token"]
    assert db.get_session(hash_token(token)) is not None
    rows = db._fetchall("SELECT token_hash FROM staff_sessions")
    assert all(token not in row["token_hash"] for row in rows)
    me = client.get("/auth/me", headers=bearer(token)).json()
    assert me["user"]["username"] == "owner"


def test_login_is_case_insensitive_on_username(client):
    bootstrap(client)
    assert login(client, username="OWNER").status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client):
    bootstrap(client)
    a = login(client, password="Wrong1234")
    b = login(client, username="nobody")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_lockout_after_max_attempts(client, settings):
    bootstrap(client)
    for _ in range(settings.login_max_attempts):
        assert login(client, password="Wrong1234").status_code == 401
    # Even the right password is refused while locked.
    assert login(client).status_code == 423


def test_unlock_by_super_admin(client, settings):
    token = owner_token(client)
    staff = add_staff(client, token, "clerk", "operator")
    for _ in range(settings.login_max_attempts):
        login(client, "clerk", "Wrong1234")
    assert login(client, "clerk").status_code == 423
    assert client.post(f"/admin/staff/{staff['id']}/unlock", headers=bearer(token)).status_code == 200
    assert login(client, "clerk").status_code == 200


def test_rate_limit_per_address(client):
    from app.routers.auth import login_limiter

    login_limiter.max_attempts = 3
    try:
        for _ in range(3):
            login(client, username="nobody")
        assert login(client, username="nobody").status_code == 429
    finally:
        login_limiter.max_attempts = 20
        login_limiter.reset()


def test_disabled_account_cannot_sign_in(client):
    token = owner_token(client)
    staff = add_staff(client, token, "clerk", "operator")
    client.patch(f"/admin/staff/{staff['id']}", headers=bearer(token), json={"active": False})
    assert login(client, "clerk").status_code == 403


def test_logout_invalidates_token(client):
    token = owner_token(client)
    assert client.post("/auth/logout", headers=bearer(token)).status_code == 200
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_expired_session_is_rejected(client, db):
    token = owner_token(client)
    db._conn.execute("UPDATE staff_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    db._conn.commit()
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_garbage_bearer_rejected(client):
    assert client.get("/admin/users", headers=bearer("not-a-token")).status_code == 401


# ---- server-side roles -------------------------------------------------------
@pytest.mark.parametrize("role, can_view, can_decide", [
    ("viewer", True, False),
    ("operator", True, False),
    ("admin", True, True),
    ("super_admin", True, True),
])
def test_role_matrix(client, reader, role, can_view, can_decide):
    seed_products(reader)
    owner = owner_token(client)
    add_staff(client, owner, "member", role)
    token = login(client, "member").json()["token"]
    client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": "5", "name": "C", "phone": "09120000005"})
    user_id = client.get("/users/bale/5", headers=h("bot")).json()["id"]

    assert (client.get("/admin/users", headers=bearer(token)).status_code == 200) == can_view
    r = client.post(f"/admin/users/{user_id}/approve", headers=bearer(token),
                    json={"person_code": 7001})
    assert (r.status_code == 200) == can_decide
    if not can_decide:
        assert r.status_code == 403
    staff_list = client.get("/admin/staff", headers=bearer(token)).status_code
    assert (staff_list == 200) == (role == "super_admin")


def test_staff_actions_are_audited_with_username(client, db, reader):
    seed_products(reader)
    token = owner_token(client)
    client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": "9", "name": "C", "phone": "09120000005"})
    uid = client.get("/users/bale/9", headers=h("bot")).json()["id"]
    client.post(f"/admin/users/{uid}/approve", headers=bearer(token), json={"person_code": 7001})
    actors = {(r["actor"], r["action"]) for r in db.list_audit()}
    assert ("owner", "user_approve") in actors


def test_must_change_password_blocks_until_changed(client, reader):
    owner = owner_token(client)
    add_staff(client, owner, "newbie", "admin", must_change=True)
    token = login(client, "newbie").json()["token"]
    assert client.get("/admin/users", headers=bearer(token)).status_code == 403
    r = client.post("/auth/change-password", headers=bearer(token),
                    json={"current_password": PW, "new_password": "Better456"})
    assert r.status_code == 200
    assert client.get("/admin/users", headers=bearer(token)).status_code == 200


def test_change_password_signs_out_other_devices(client):
    token_a = owner_token(client)
    token_b = login(client).json()["token"]
    client.post("/auth/change-password", headers=bearer(token_a),
                json={"current_password": PW, "new_password": "Better456"})
    assert client.get("/auth/me", headers=bearer(token_a)).status_code == 200
    assert client.get("/auth/me", headers=bearer(token_b)).status_code == 401


def test_change_password_needs_current(client):
    token = owner_token(client)
    r = client.post("/auth/change-password", headers=bearer(token),
                    json={"current_password": "Nope12345", "new_password": "Better456"})
    assert r.status_code == 403


def test_role_change_drops_sessions(client):
    owner = owner_token(client)
    staff = add_staff(client, owner, "clerk", "admin")
    token = login(client, "clerk").json()["token"]
    client.patch(f"/admin/staff/{staff['id']}", headers=bearer(owner), json={"role": "viewer"})
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_last_super_admin_is_protected(client):
    owner = owner_token(client)
    me = client.get("/auth/me", headers=bearer(owner)).json()["user"]
    assert client.patch(f"/admin/staff/{me['id']}", headers=bearer(owner),
                        json={"role": "admin"}).status_code == 409
    assert client.patch(f"/admin/staff/{me['id']}", headers=bearer(owner),
                        json={"active": False}).status_code == 409
    assert client.delete(f"/admin/staff/{me['id']}", headers=bearer(owner)).status_code == 409


def test_duplicate_username_rejected(client):
    owner = owner_token(client)
    add_staff(client, owner, "clerk", "viewer")
    r = client.post("/admin/staff", headers=bearer(owner), json={
        "username": "CLERK", "role": "viewer", "password": PW})
    assert r.status_code == 409


def test_reset_password_forces_change_and_signs_out(client):
    owner = owner_token(client)
    staff = add_staff(client, owner, "clerk", "admin")
    token = login(client, "clerk").json()["token"]
    r = client.post(f"/admin/staff/{staff['id']}/password", headers=bearer(owner),
                    json={"password": "Fresh7890"})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401
    assert login(client, "clerk", "Fresh7890").status_code == 200


def test_audit_log_is_super_admin_only(client):
    owner = owner_token(client)
    add_staff(client, owner, "boss", "admin")
    token = login(client, "boss").json()["token"]
    assert client.get("/admin/audit", headers=bearer(owner)).status_code == 200
    assert client.get("/admin/audit", headers=bearer(token)).status_code == 403


# ---- channels ----------------------------------------------------------------
def test_staff_can_browse_catalogue_but_not_place_orders(client, reader):
    seed_products(reader)
    token = owner_token(client)
    assert client.get("/products", headers=bearer(token)).status_code == 200
    assert client.get("/groups", headers=bearer(token)).status_code == 200
    r = client.post("/orders", headers=bearer(token), json={
        "platform": "bale", "chat_id": "1", "items": [{"kala_code": 101, "qty": 1}]})
    assert r.status_code == 401


def test_service_and_bot_keys_are_local_only(client, settings):
    settings.service_keys_local_only = True  # TestClient is not a loopback host
    assert client.get("/admin/users", headers=h("admin")).status_code == 401
    assert client.get("/groups", headers=h("bot")).status_code == 401
    # The site key is meant for a relay outside the server.
    assert client.get("/groups", headers=h("site")).status_code == 200


def test_channel_keys_cannot_use_admin_endpoints(client):
    assert client.get("/admin/users", headers=h("bot")).status_code == 403
    assert client.get("/admin/users", headers=h("site")).status_code == 403


def test_service_key_cannot_manage_staff(client):
    owner_token(client)
    assert client.get("/admin/staff", headers=h("admin")).status_code == 403


# ---- events --------------------------------------------------------------------
def test_event_feed(client, reader):
    seed_products(reader)
    token = owner_token(client)
    start = client.get("/admin/events", headers=bearer(token)).json()
    assert start["items"] == []
    register_and_approve(client, chat_id="77")
    order = client.post("/orders", headers=h("bot"), json={
        "platform": "bale", "chat_id": "77", "items": [{"kala_code": 101, "qty": 1}]}).json()
    client.post(f"/orders/{order['id']}/receipt?platform=bale&chat_id=77",
                headers=h("bot"), json={"receipt_ref": "photo"})
    feed = client.get(f"/admin/events?after={start['last_id']}", headers=bearer(token)).json()
    kinds = [e["kind"] for e in feed["items"]]
    assert kinds == ["customer_registered", "customer_approved", "order_created",
                     "receipt_uploaded"]
    # Re-registering an existing customer is not a new event.
    client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": "77", "name": "Ali", "phone": "09120000005"})
    again = client.get(f"/admin/events?after={feed['last_id']}", headers=bearer(token)).json()
    assert again["items"] == [] and again["last_id"] == feed["last_id"]


def test_event_feed_resyncs_after_reset(client):
    token = owner_token(client)
    r = client.get("/admin/events?after=999", headers=bearer(token)).json()
    assert r == {"last_id": 0, "items": []}
