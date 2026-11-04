"""v2.18.1 items 14 and 15: the owner's ready replies, filled by the server without ever saying a
customer's address or national code; the ticks of what 2.18 added."""
from __future__ import annotations

import pytest

from app import reply_templates as rt
from app import staff as st
from app.db_own import OwnDB

from .conftest import h
from .test_phase3 import staff

CODE = "0499370899"
ADDRESS = "تهران، ولیعصر، پلاک ۱"
VALUES = {"customer_name": "علی رضایی", "product": "Galaxy S25", "color": "مشکی",
          "price": "۹۰۰٬۰۰۰٬۰۰۰ ریال", "order_no": "۱۲", "hours": "۹ تا ۲۱",
          "shop_address": "مشهد، خیابان نمونه", "shop_phone": "09155000432",
          "customer_phone": "09120000000"}


def test_the_56_templates_are_all_there():
    templates = rt.load_data()["templates"]
    assert len(templates) == 56 and len({t["id"] for t in templates}) == 56
    for template in templates:
        assert set(template) == {"id", "category", "title", "text", "placeholders"}
        assert sorted(template["placeholders"]) == sorted(set(rt.gaps(template["text"])))


def test_all_placeholders_are_filled():
    built = rt.build(VALUES, has_national_code=False, has_address=True)
    assert built["templates"] and not [t for t in built["templates"] if t["missing"]]
    assert not [t for t in built["templates"] if "{" in t["text"]]


def test_what_is_not_known_stays_a_gap():
    built = rt.build({"customer_name": "علی"})
    greet = next(t for t in built["templates"] if t["id"] == "greet")
    assert "علی" in greet["text"] and greet["missing"] == []
    price = next(t for t in built["templates"] if "price" in rt.gaps(t["text"]))
    assert "price" in price["missing"]


def _text(template_id: str, **flags) -> str:
    built = rt.build(VALUES, **{"has_national_code": False, "has_address": True, **flags})
    return next(t["text"] for t in built["templates"] if t["id"] == template_id)


@pytest.mark.parametrize("template_id", sorted(rt.CUSTOMER_ADDRESS))
def test_the_customers_address_is_never_written(template_id):
    text = _text(template_id)
    assert rt.ADDRESS_ON_FILE in text and "خیابان نمونه" not in text


def test_the_shops_address_is_written_where_it_is_the_shops():
    assert "خیابان نمونه" in _text("pickup_ready_store")
    assert "09155000432" in _text("pickup_coord_phone")


def test_the_customers_phone_is_their_own():
    assert "09120000000" in _text("stock_out_notify")


def test_what_is_on_file_is_never_asked_for():
    ids = {t["id"] for t in rt.build(VALUES, has_national_code=True, has_address=True)["templates"]}
    assert not {"ask_national_code_invoice", "ask_address_full"} & ids
    assert "ask_address_confirm" in ids
    ids = {t["id"] for t in rt.build(VALUES, has_national_code=False, has_address=False)["templates"]}
    assert {"ask_national_code_invoice", "ask_address_full"} <= ids
    assert "ask_address_confirm" not in ids


def test_a_private_value_in_a_message_is_noticed():
    assert rt.mentions_private("کد ملی شما ۰۴۹۹۳۷۰۸۹۹ است", CODE, "")
    assert rt.mentions_private("ارسال به تهران، ولیعصر،  پلاک ۱ شد", "", ADDRESS)
    assert not rt.mentions_private("سفارش شما ارسال شد", CODE, ADDRESS)
    assert not rt.mentions_private("کوتاه", "", "کوتاه")


# ---- the endpoint ------------------------------------------------------------------------------
def _request(client) -> int:
    client.post("/users/register", headers=h("bot"), json={
        "platform": "bale", "chat_id": "5", "name": "علی رضایی", "phone": "09120000005"})
    return client.post("/item-requests", headers=h("bot"), json={
        "platform": "bale", "chat_id": "5", "text": "Galaxy S25 می‌خواهم"}).json()["id"]


def test_the_list_is_filled_for_this_customer(client, db):
    request_id = _request(client)
    client.post("/users/bale/5/details", headers=h("bot"),
                json={"national_code": CODE, "address": ADDRESS})
    boss = staff(db, "super_admin", "boss")
    r = client.get(f"/admin/item-requests/{request_id}/reply-templates", headers=boss)
    assert r.status_code == 200
    body = r.json()
    assert CODE not in r.text and "ولیعصر" not in r.text
    assert "علی رضایی" in next(t["text"] for t in body["templates"] if t["id"] == "greet")
    assert "ask_national_code_invoice" not in {t["id"] for t in body["templates"]}


def test_missing_details_can_be_asked_for(client, db):
    request_id = _request(client)
    boss = staff(db, "super_admin", "boss")
    body = client.get(f"/admin/item-requests/{request_id}/reply-templates", headers=boss).json()
    assert "ask_national_code_invoice" in {t["id"] for t in body["templates"]}


def test_a_new_sales_user_has_the_tick_and_it_can_be_taken_away(client, db):
    request_id = _request(client)
    assert "reply_templates.view" in st.PERMISSIONS["operator"]
    mina = staff(db, "operator", "mina")
    url = f"/admin/item-requests/{request_id}/reply-templates"
    # a request nobody has taken yet is visible to a sales user
    assert client.get(url, headers=mina).status_code == 200
    db._conn.execute("UPDATE staff_users SET perm_revoke='reply_templates.view' WHERE username='mina'")
    db._conn.commit()
    assert client.get(url, headers=mina).status_code == 403


def test_a_reply_with_a_gap_is_refused(client, db):
    request_id = _request(client)
    boss = staff(db, "super_admin", "boss")
    r = client.post(f"/admin/item-requests/{request_id}/messages", headers=boss,
                    json={"text": "مدل {product} موجود شد"})
    assert r.status_code == 422 and "جای‌خالی" in r.json()["detail"]


def test_a_reply_with_the_customers_private_details_is_refused(client, db):
    request_id = _request(client)
    client.post("/users/bale/5/details", headers=h("bot"),
                json={"national_code": CODE, "address": ADDRESS})
    boss = staff(db, "super_admin", "boss")
    url = f"/admin/item-requests/{request_id}/messages"
    for text in (f"کد ملی شما {CODE} ثبت شد", f"به {ADDRESS} ارسال شد"):
        r = client.post(url, headers=boss, json={"text": text})
        assert r.status_code == 422 and "کد ملی" in r.json()["detail"]
    assert client.post(url, headers=boss, json={"text": "سفارش شما ارسال شد"}).status_code == 201


# ---- item 15: every new part of 2.18 has a tick -----------------------------------------------------
NEW_IN_218 = ("archive_manual.edit", "auto_quote.view", "auto_quote.edit", "product_alias.edit",
              "faq.view", "faq.edit", "staff_chat.view", "staff_chat.edit",
              "customer_private.view", "customer_private.edit", "installment.view",
              "installment.edit", "installment_rules.view", "installment_rules.edit",
              "reply_templates.view", "price_notes.view", "price_notes.edit")


@pytest.mark.parametrize("name", NEW_IN_218)
def test_each_has_a_tick(name):
    assert name in st.ALL_PERMISSIONS
    assert st.PERMISSION_LABELS[name]


def test_a_new_user_starts_with_only_the_daily_one():
    sales = st.effective_permissions("operator")
    assert {p for p in NEW_IN_218 if p in sales} == {"reply_templates.view"}


def test_the_price_list_tick_is_not_the_channels_tick(client, db):
    mina = staff(db, "operator", "mina")
    db._conn.execute("UPDATE staff_users SET perm_grant='pricelist.view' WHERE username='mina'")
    db._conn.commit()
    assert client.get("/admin/pricelists/notes", headers=mina).status_code == 403
    db._conn.execute("UPDATE staff_users SET perm_grant='price_notes.view' WHERE username='mina'")
    db._conn.commit()
    assert client.get("/admin/pricelists/notes", headers=mina).status_code == 200
    r = client.post("/admin/pricelists/notes/1/apply", headers=mina,
                    json={"picks": [{"row_key": "x", "naghd": 1}]})
    assert r.status_code == 403


def test_who_had_the_channel_with_the_price_list_keeps_it():
    assert st.upgrade_ticks_2181("operator", "pricelist.view") == "price_notes.view,pricelist.view"
    assert "price_notes.edit" in st.upgrade_ticks_2181("operator", "pricelist.edit")
    assert st.upgrade_ticks_2181("operator", "orders.view") == "orders.view"
    assert st.upgrade_ticks_2181("super_admin", "x") == "x"


def test_the_upgrade_runs_once(tmp_path):
    path = tmp_path / "x.db"
    first = OwnDB(path)
    user = first.create_staff("mina", "Mina", "operator", "x")
    first._conn.execute("UPDATE staff_users SET perm_grant='pricelist.edit' WHERE id=?", (user["id"],))
    first._conn.execute("DELETE FROM shop_state WHERE key='permissions_2181'")
    first._conn.commit()
    first._conn.close()
    again = OwnDB(path)
    row = again._conn.execute("SELECT perm_grant FROM staff_users WHERE id=?", (user["id"],)).fetchone()
    assert "price_notes.edit" in row["perm_grant"]
    again._conn.execute("UPDATE staff_users SET perm_grant='orders.view' WHERE id=?", (user["id"],))
    again._conn.commit()
    again._conn.close()
    third = OwnDB(path)
    row = third._conn.execute("SELECT perm_grant FROM staff_users WHERE id=?", (user["id"],)).fetchone()
    assert row["perm_grant"] == "orders.view"
    third._conn.close()
