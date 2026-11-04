"""v2.18.1 item 16: the national code and the address never go towards a customer or a bot, a
customer cannot change one that is on file, and among staff only the tick shows them."""
from __future__ import annotations

from app import customer_details as cd
from app import staff as st

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff

CODE = "0499370899"
ADDRESS = "تهران، ولیعصر، پلاک ۱"
NOTHING = {"first_name": "علی", "last_name": "رضایی", "national_code": "", "address": ""}


def _register(client, chat="222", phone="09124445555"):
    return client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": chat, "name": "علی رضایی", "phone": phone}).json()


def _save(client, chat="222", **fields):
    return client.post(f"/users/bale/{chat}/details", json=fields, headers=h("bot"))


def _order(client, chat="222", **extra):
    return client.post("/orders", headers=h("bot"), json={
        "platform": "bale", "chat_id": chat, "items": [{"kala_code": 101, "qty": 1}], **extra})


def _sales(db, ticks: str, revoke: str = "") -> dict:
    """Headers of a «کاربر فروش» with these ticks (and without those)."""
    headers = staff(db, "operator", "mina")
    db._conn.execute("UPDATE staff_users SET perm_grant=?, perm_revoke=? WHERE username='mina'",
                     (ticks, revoke))
    db._conn.commit()
    return headers


# ---- masking -------------------------------------------------------------------------------------
def test_the_mask_leaves_only_the_last_two():
    assert cd.mask_national_code(CODE) == "••••••••99"
    assert cd.mask_national_code("") == ""
    assert CODE not in cd.mask_national_code(CODE)


# ---- towards the bots ----------------------------------------------------------------------------
def test_no_answer_to_a_bot_carries_them(client, reader):
    seed_products(reader)
    _register(client)
    answers = [_save(client, national_code=CODE, address=ADDRESS).text,
               client.get("/users/bale/222/details", headers=h("bot")).text,
               client.get("/users/bale/222", headers=h("bot")).text]
    order = _order(client, use_saved_address=True)
    assert order.status_code == 201
    answers += [order.text, client.get("/users/bale/222/orders", headers=h("bot")).text]
    for answer in answers:
        assert CODE not in answer and "ولیعصر" not in answer


def test_the_service_key_gets_no_values_either(client, reader):
    seed_products(reader)
    user = _register(client)
    _save(client, national_code=CODE, address=ADDRESS)
    order_id = _order(client, use_saved_address=True).json()["id"]
    for url in (f"/admin/users/{user['id']}", f"/admin/orders/{order_id}"):
        answer = client.get(url, headers=h("admin")).text
        assert CODE not in answer and "ولیعصر" not in answer


def test_never_in_the_audit_log_or_events(client, db, reader):
    seed_products(reader)
    _register(client)
    _save(client, national_code=CODE, address=ADDRESS)
    _order(client, use_saved_address=True)
    logged = str(db.list_audit(200)) + str(db.list_events(0, 200))
    assert CODE not in logged and "ولیعصر" not in logged


# ---- a customer cannot change what is on file -----------------------------------------------------
def test_on_file_in_our_database_stays(client, db):
    _register(client)
    _save(client, national_code=CODE, address=ADDRESS)
    r = _save(client, national_code="1234567891", address="مشهد، احمدآباد، پلاک ۲")
    assert r.status_code == 200
    row = db.get_user_by_platform("bale", "222")
    assert row["national_code"] == CODE and row["address"] == ADDRESS


def test_on_file_in_sazeh_is_not_copied_or_changed(client, db, reader, writer):
    seed_products(reader)
    register_and_approve(client)
    reader.person_details = lambda code: {**NOTHING, "national_code": CODE, "address": ADDRESS}
    _save(client, "111", national_code="1234567891", address="مشهد، احمدآباد، پلاک ۲")
    row = db.get_user_by_platform("bale", "111")
    assert row["national_code"] == "" and row["address"] == ""
    assert not [c for c in writer.calls if c[0] == "fill_person_empty"]


def test_sazeh_unreadable_takes_nothing(client, db, reader):
    seed_products(reader)
    register_and_approve(client)

    def down(_code):
        raise OSError("down")

    reader.person_details = down
    _save(client, "111", national_code=CODE)
    assert db.get_user_by_platform("bale", "111")["national_code"] == ""


def test_only_the_missing_one_is_taken(client, db, reader):
    seed_products(reader)
    register_and_approve(client)
    reader.person_details = lambda code: {**NOTHING, "national_code": CODE}
    _save(client, "111", national_code="1234567891", address=ADDRESS)
    row = db.get_user_by_platform("bale", "111")
    assert row["national_code"] == "" and row["address"] == ADDRESS


def test_the_server_validates_what_the_form_sent(client, db):
    _register(client)
    r = _save(client, national_code="1111111111")
    assert r.status_code == 422 and db.get_user_by_platform("bale", "222")["national_code"] == ""


def test_a_changed_name_is_still_allowed(client, db):
    _register(client)
    _save(client, first_name="علی", last_name="رضایی")
    assert _save(client, first_name="حسن").status_code == 200
    assert db.get_user_by_platform("bale", "222")["first_name"] == "حسن"


# ---- ordering waits for them -----------------------------------------------------------------------
def test_no_order_without_national_code(client, reader, db):
    seed_products(reader)
    _register(client)
    r = _order(client, ship_address=ADDRESS)
    assert r.status_code == 409 and r.json()["detail"] == cd.DETAILS_REQUIRED
    assert db.list_orders("awaiting_payment") == []


def test_no_order_without_any_address(client, reader):
    seed_products(reader)
    _register(client)
    _save(client, national_code=CODE)
    assert _order(client).status_code == 409
    assert _order(client, use_saved_address=True).status_code == 409


def test_an_address_typed_for_the_order_counts(client, reader, db):
    seed_products(reader)
    _register(client)
    _save(client, national_code=CODE)
    assert _order(client, ship_address=ADDRESS).status_code == 201
    assert db.get_user_by_platform("bale", "222")["address"] == ADDRESS


def test_use_saved_address_is_filled_by_the_server(client, reader, db):
    seed_products(reader)
    _register(client)
    _save(client, national_code=CODE, address=ADDRESS)
    r = _order(client, use_saved_address=True)
    assert r.status_code == 201 and r.json()["has_ship_address"] is True
    assert db.get_order(r.json()["id"])["ship_address"] == ADDRESS


def test_the_check_of_a_color_is_not_an_order(client, reader):
    seed_products(reader)
    _register(client)
    r = client.post("/orders?check=true", headers=h("bot"), json={
        "platform": "bale", "chat_id": "222", "items": [{"kala_code": 101, "qty": 1}]})
    assert r.status_code == 200


# ---- among staff -----------------------------------------------------------------------------------
def test_the_tick_is_not_a_default(db):
    assert "customer_private.view" not in st.PERMISSIONS["operator"]
    assert {"customer_private.view", "customer_private.edit"} <= st.ALL_PERMISSIONS


def test_staff_without_the_tick_see_a_mask(client, db, reader):
    user = _register(client)
    _save(client, national_code=CODE, address=ADDRESS)
    mina = _sales(db, "customers.view")
    row = client.get(f"/admin/users/{user['id']}", headers=mina)
    assert row.status_code == 200, row.text
    data = row.json()
    assert data["national_code"] == "••••••••99" and data["address"] == ""
    assert data["national_code_on_file"] and data["address_on_file"] and data["private_hidden"]
    every = client.get("/admin/users", headers=mina).text
    assert CODE not in every and "ولیعصر" not in every


def test_staff_with_the_tick_see_them(client, db):
    user = _register(client)
    _save(client, national_code=CODE, address=ADDRESS)
    mina = _sales(db, "customers.view,customer_private.view")
    data = client.get(f"/admin/users/{user['id']}", headers=mina).json()
    assert data["national_code"] == CODE and data["address"] == ADDRESS
    assert data["private_hidden"] is False


def test_the_manager_sees_them(client, db):
    user = _register(client)
    _save(client, national_code=CODE)
    boss = staff(db, "super_admin", "boss")
    assert client.get(f"/admin/users/{user['id']}",
                      headers=boss).json()["national_code"] == CODE


def test_editing_needs_its_own_tick(client, db):
    user = _register(client)
    mina = _sales(db, "customers.edit,customer_private.view")
    url = f"/admin/users/{user['id']}/details"
    assert client.put(url, json={"national_code": CODE}, headers=mina).status_code == 403
    # the name is not private
    assert client.put(url, json={"first_name": "علی"}, headers=mina).status_code == 200
    db._conn.execute("UPDATE staff_users SET perm_grant=? WHERE username='mina'",
                     ("customers.edit,customer_private.edit",))
    db._conn.commit()
    r = client.put(url, json={"national_code": CODE}, headers=mina)
    assert r.status_code == 200 and db.get_user_by_id(user["id"])["national_code"] == CODE


def test_approving_without_the_tick_uses_what_is_stored(client, db, writer):
    user = _register(client)
    _save(client, first_name="علی", last_name="رضایی", national_code=CODE, address=ADDRESS)
    mina = _sales(db, "customers.edit")
    url = f"/admin/users/{user['id']}/approve"
    r = client.post(url, json={"create_person": True, "national_code": "1234567891"},
                    headers=mina)
    assert r.status_code == 403
    r = client.post(url, json={"create_person": True}, headers=mina)
    assert r.status_code == 200, r.text
    assert CODE not in r.text and "ولیعصر" not in r.text


def test_the_order_address_with_the_ship_tick_or_the_private_one(client, db, reader):
    seed_products(reader)
    _register(client)
    _save(client, national_code=CODE, address=ADDRESS)
    order_id = _order(client, use_saved_address=True).json()["id"]
    # without either tick: «there is one», not which (the manager sees all orders)
    mina = _sales(db, "orders.view", "ship.edit")
    db._conn.execute("UPDATE orders SET owner_id=(SELECT id FROM staff_users WHERE username='mina')"
                     " WHERE id=?", (order_id,))
    db._conn.commit()
    seen = client.get(f"/admin/orders/{order_id}", headers=mina)
    assert seen.status_code == 200, seen.text
    assert seen.json()["ship_address"] == "" and seen.json()["has_ship_address"] is True
    db._conn.execute("UPDATE staff_users SET perm_revoke='' WHERE username='mina'")
    db._conn.commit()
    assert client.get(f"/admin/orders/{order_id}", headers=mina).json()["ship_address"] == ADDRESS
    boss = staff(db, "super_admin", "boss")
    assert client.get(f"/admin/orders/{order_id}",
                      headers=boss).json()["ship_address"] == ADDRESS
