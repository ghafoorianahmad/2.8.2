"""v2.6.1: group tree with inherited flags, «قیمت با استعلام», stale carts refused at the
final submit with a precise reason, inquiry requests, staff replies to item requests,
and the phone-group warning flag of the shop state."""
from __future__ import annotations

from app import groups as group_config

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff
from .test_v260 import PHONE, _map_phone, _order, events

BRAND = 31          # a brand subgroup of the phones group 3
INQ = 600           # an item of the «price on inquiry» group 5 (no accounting price)


def _tree(reader, db):
    """1, 2 accessories; 3 = گوشی with brand subgroup 31; 5 = price on inquiry with
    subgroup 51; only the parents carry flags (the children inherit)."""
    seed_products(reader)
    reader.products[PHONE] = {"name": "Samsung A26", "group": BRAND, "stock": 4.0,
                              "open": 0.0, "unit_price": 210_000_000.0, "image": None}
    reader.products[INQ] = {"name": "Gold watch", "group": 51, "stock": 0.0, "open": 0.0,
                            "unit_price": 0.0, "image": None}
    reader.groups = [{"code": 1, "name": "G1", "parent": 0}, {"code": 2, "name": "G2", "parent": 0},
                     {"code": 3, "name": "گوشی", "parent": 0},
                     {"code": BRAND, "name": "سامسونگ", "parent": 3},
                     {"code": 5, "name": "ساعت", "parent": 0},
                     {"code": 51, "name": "طلا", "parent": 5}]
    db.set_group_settings([(1, True, False, False), (2, True, False, False),
                           (3, True, True, False), (BRAND, False, False, False),
                           (5, True, False, True), (51, False, False, False)], "test")


# ---- inheritance -------------------------------------------------------------------------------
def test_group_config_inherits_and_survives_cycles():
    cfg = group_config.GroupConfig(shown={3}, phone={3}, inquiry={5},
                                   parents={31: 3, 311: 31, 51: 5, 7: 8, 8: 7})
    assert cfg.visible(311) and cfg.is_phone(311) and not cfg.on_inquiry(311)
    assert cfg.on_inquiry(51) and not cfg.visible(51)
    assert not cfg.visible(7)                       # a cycle ends, never loops
    assert cfg.inquiry_groups() == {5, 51}
    assert group_config.parent_map([{"code": 0, "parent": None}, {"code": 1, "parent": 0},
                                    {"code": 4, "parent": 1}]) == {4: 1}


def test_subgroups_inherit_show_and_phone(client, reader, db):
    _tree(reader, db)
    register_and_approve(client)
    groups = client.get("/groups", headers=h("bot")).json()
    assert {g["code"] for g in groups} == {1, 2, 3, BRAND, 5, 51}
    assert next(g for g in groups if g["code"] == BRAND)["parent"] == 3
    # a brand item is a phone: no list -> hidden and refused (never at the accounting price)
    items = client.get("/products", headers=h("bot")).json()["items"]
    assert PHONE not in [p["code"] for p in items]
    r = _order(client, [{"kala_code": PHONE, "qty": 1}])
    assert r.status_code == 422 and "is not in the current price list" in r.json()["detail"]
    # with the list it is sold, priced from the list; listing the parent shows the child's item
    color = _map_phone(db)
    by_parent = client.get("/products", params={"group": 3}, headers=h("bot")).json()["items"]
    assert [p["code"] for p in by_parent] == [PHONE] and by_parent[0]["priced_by"] == "pricelist"
    assert _order(client, [{"kala_code": PHONE, "qty": 1, "variant_id": color}]).status_code == 201
    # closed sales close the inherited phone too
    client.post("/admin/sales/action", json={"action": "close"}, headers=h("admin"))
    r = _order(client, [{"kala_code": PHONE, "qty": 1, "variant_id": color}])
    assert r.status_code == 409 and r.json()["detail"].startswith("Sales are closed")


def test_hidden_parent_hides_nothing_inherited_without_a_tick(client, reader, db):
    _tree(reader, db)
    db.set_group_settings([(3, False, True, False)], "test")
    groups = {g["code"] for g in client.get("/groups", headers=h("bot")).json()}
    assert 3 not in groups and BRAND not in groups


def test_admin_groups_show_parent_and_effective_flags(client, reader, db):
    _tree(reader, db)
    rows = {g["code"]: g for g in client.get("/admin/product-groups", headers=h("admin")).json()}
    brand = rows[BRAND]
    assert brand["parent"] == 3 and not brand["is_phone"] and brand["effective_is_phone"]
    assert brand["effective_show_in_bot"] and not brand["effective_price_on_inquiry"]
    assert rows[51]["effective_price_on_inquiry"] and rows[5]["price_on_inquiry"]
    assert rows[3]["parent"] is None
    saved = client.put("/admin/product-groups", json={"groups": [
        {"code": 2, "show_in_bot": True, "is_phone": False, "price_on_inquiry": True}]},
        headers=staff(db)).json()
    assert next(g for g in saved if g["code"] == 2)["price_on_inquiry"] is True


# ---- price on inquiry ----------------------------------------------------------------------------
def test_inquiry_items_have_no_price_and_cannot_be_ordered(client, reader, db):
    _tree(reader, db)
    register_and_approve(client)
    items = client.get("/products", headers=h("bot")).json()["items"]
    inq = next(p for p in items if p["code"] == INQ)        # shown with no price and no stock
    assert inq["price_on_inquiry"] and inq["priced_by"] == "inquiry" and inq["unit_price"] == 0
    one = client.get(f"/products/{INQ}", headers=h("bot")).json()
    assert one["price_on_inquiry"] is True and one["unit_price"] == 0
    # an item with an accounting price in an inquiry group never shows the price
    reader.products[104]["group"] = 51
    assert client.get("/products/104", headers=h("bot")).json()["unit_price"] == 0
    r = _order(client, [{"kala_code": 104, "qty": 1}])
    assert r.status_code == 422 and r.json()["detail"] == "Product 104 is price on inquiry"
    assert db.list_orders_for_user(1) == []


def test_inquiry_request_goes_to_the_item_requests(client, reader, db, writer):
    _tree(reader, db)
    register_and_approve(client)
    body = {"platform": "bale", "chat_id": "111", "kala_code": INQ, "kind": "inquiry"}
    r = client.post("/item-requests", json=body, headers=h("bot"))
    assert r.status_code == 201 and r.json()["kind"] == "inquiry"
    assert r.json()["product_name"] == "Gold watch"
    # only for an inquiry item, and a product is required
    assert client.post("/item-requests", json={**body, "kala_code": 101},
                       headers=h("bot")).status_code == 422
    assert client.post("/item-requests", json={**body, "kala_code": None, "text": "abc"},
                       headers=h("bot")).status_code == 422
    rows = client.get("/admin/item-requests", params={"kind": "inquiry"},
                      headers=h("admin")).json()
    assert [x["kind"] for x in rows] == ["inquiry"]
    assert rows[0]["customer_phone"] == "09120000000"
    assert client.get("/admin/item-requests", params={"kind": "unavailable"},
                      headers=h("admin")).json() == []
    assert "item_request" in events(db)
    assert writer.calls == []                                   # nothing to Sazeh


# ---- stale carts ----------------------------------------------------------------------------------
def test_stale_cart_items_are_refused_with_the_reason(client, reader, db):
    _tree(reader, db)
    register_and_approve(client)
    db.set_group_settings([(2, False, False, False)], "test")          # group 2 now hidden
    r = _order(client, [{"kala_code": 101, "qty": 1}, {"kala_code": 104, "qty": 1}])
    assert r.status_code == 422 and r.json()["detail"] == "Product 104 is not available for sale"
    assert _order(client, [{"kala_code": 101, "qty": 1}]).status_code == 201


def test_shop_state_reports_missing_phone_groups(client, reader, db):
    _tree(reader, db)
    assert client.get("/shop/state", headers=h("bot")).json()["phone_groups_ready"] is True
    db.set_group_settings([(3, True, False, False)], "test")
    assert client.get("/shop/state", headers=h("bot")).json()["phone_groups_ready"] is False


# ---- staff replies --------------------------------------------------------------------------------
def _request(client, db, reader):
    _tree(reader, db)
    register_and_approve(client)
    return client.post("/item-requests", json={"platform": "bale", "chat_id": "111",
                                               "text": "نوکیا ۳۳۱۰"}, headers=h("bot")).json()


def test_reply_is_queued_for_the_bot_and_reported(client, reader, db):
    req = _request(client, db, reader)
    who = staff(db, "operator")
    r = client.post(f"/admin/item-requests/{req['id']}/messages", json={"text": " موجود شد "},
                    headers=who)
    assert r.status_code == 201
    msg = r.json()
    assert msg["status"] == "pending" and msg["text"] == "موجود شد" and msg["created_by"]
    assert "item_request_message" in events(db)
    # the bot (service key) reads where to deliver it; staff may not
    assert client.get(f"/admin/item-request-messages/{msg['id']}", headers=who).status_code == 403
    d = client.get(f"/admin/item-request-messages/{msg['id']}", headers=h("admin")).json()
    assert d["platform"] == "bale" and d["chat_id"] == "111" and d["request_text"] == "نوکیا ۳۳۱۰"
    # staff cannot fake a delivery; the bot reports a failure once
    assert client.post(f"/admin/item-request-messages/{msg['id']}/result",
                       json={"ok": True}, headers=who).status_code == 403
    done = client.post(f"/admin/item-request-messages/{msg['id']}/result",
                       json={"ok": False, "error": "blocked"}, headers=h("admin")).json()
    assert done["status"] == "failed" and done["error"] == "blocked"
    again = client.post(f"/admin/item-request-messages/{msg['id']}/result",
                        json={"ok": True}, headers=h("admin")).json()
    assert again["status"] == "failed"                    # a late report changes nothing
    history = client.get(f"/admin/item-requests/{req['id']}/messages", headers=who).json()
    assert [m["status"] for m in history] == ["failed"]
    assert client.get(f"/admin/item-requests/{req['id']}", headers=who).json()["messages_count"] == 1


def test_reply_validation(client, reader, db):
    req = _request(client, db, reader)
    who = staff(db)
    url = f"/admin/item-requests/{req['id']}/messages"
    assert client.post(url, json={"text": "   "}, headers=who).status_code == 422
    assert client.post(url, json={"text": "x" * 1001}, headers=who).status_code == 422
    assert client.post("/admin/item-requests/999/messages", json={"text": "x"},
                       headers=who).status_code == 404
    assert client.post(url, json={"text": "x"}, headers=h("bot")).status_code in (401, 403)


def test_staff_note(client, reader, db):
    req = _request(client, db, reader)
    who = staff(db)
    r = client.put(f"/admin/item-requests/{req['id']}/note", json={"note": " تماس گرفته شد "},
                   headers=who).json()
    assert r["admin_note"] == "تماس گرفته شد" and r["note_by"]
