"""v2.6.0: product groups (show in bot / phone group), phones only from the current
valid list, the sales gate for phones without any list, payment card required,
unavailable item requests, the statement PDF data, person names, Status setting."""
from __future__ import annotations

from app import control
from app.pricelist.repo import PriceListRepo

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff


def events(db) -> list[str]:
    return [e["kind"] for e in db.list_events(0, 1000)]

PHONE = 500        # an item of the phone group (3) with an accounting price and stock


def _shop(reader):
    seed_products(reader)
    reader.products[PHONE] = {"name": "Samsung A26", "group": 3, "stock": 4.0, "open": 0.0,
                              "unit_price": 210_000_000.0, "image": None}
    reader.groups = [{"code": 1, "name": "Group 1"}, {"code": 2, "name": "Group 2"},
                     {"code": 3, "name": "Phones"}, {"code": 4, "name": "Internal"}]


def _order(client, items, key=None):
    headers = {**h("bot"), **({"Idempotency-Key": key} if key else {})}
    return client.post("/orders", json={"platform": "bale", "chat_id": "111", "items": items},
                       headers=headers)


def _map_phone(db, kala_code=PHONE) -> int:
    repo = PriceListRepo(db)
    row = {"row_key": "a26|128|blk", "block": 0, "section": "SAMSUNG", "description": "A26",
           "kind": "شرکتی", "color": "BLACK", "naghd": 20000, "raval": 21000,
           "price_rial": 205_000_000}
    list_id = repo.insert_list(list_date="1405/07/22", sha256="a26", source="manual",
                               source_ref="", posted_at=None, status="held", reason="",
                               rows=[row])
    repo.activate(list_id)
    return repo.upsert_mapping(row_key=row["row_key"], action="map", kala_code=kala_code,
                               color_label="مشکی", section="SAMSUNG", description="A26",
                               kind="شرکتی", color="BLACK", actor="test")["id"]


# ---- 7 (critical): closed sales + no price list -> no phone order -------------------------
def test_phone_without_any_list_is_hidden_and_refused_while_sales_closed(client, reader, db):
    _shop(reader)
    register_and_approve(client)
    client.post("/admin/sales/action", json={"action": "close"}, headers=h("admin"))
    assert client.get("/shop/state", headers=h("bot")).json()["closed"] is True
    # the phone has an accounting price and stock but no list: never shown ...
    names = [p["code"] for p in client.get("/products", headers=h("bot")).json()["items"]]
    assert PHONE not in names and 101 in names
    assert client.get(f"/products/{PHONE}", headers=h("bot")).status_code == 404
    # ... and never sold at the accounting price (the old bug), also from a stale cart
    r = _order(client, [{"kala_code": PHONE, "qty": 1}])
    assert r.status_code == 409 and r.json()["detail"].startswith("Sales are closed")
    mixed = _order(client, [{"kala_code": 101, "qty": 1}, {"kala_code": PHONE, "qty": 1}])
    assert mixed.status_code == 409
    assert _order(client, [{"kala_code": 101, "qty": 1}]).status_code == 201   # accessories


def test_phone_without_list_is_refused_while_sales_open(client, reader, db):
    _shop(reader)
    register_and_approve(client)
    # open sales but no list: a phone has no price -> not for sale
    assert _order(client, [{"kala_code": PHONE, "qty": 1}]).status_code == 422


def test_phone_is_priced_only_from_the_list(client, reader, db):
    _shop(reader)
    register_and_approve(client)
    color = _map_phone(db)
    p = client.get(f"/products/{PHONE}", headers=h("bot")).json()
    assert p["priced_by"] == "pricelist" and p["unit_price"] == 205_000_000
    r = _order(client, [{"kala_code": PHONE, "qty": 1, "variant_id": color}])
    assert r.status_code == 201 and r.json()["items"][0]["unit_price"] == 205_000_000
    # no color = no accounting-price fallback
    assert _order(client, [{"kala_code": PHONE, "qty": 1}]).status_code == 422


def test_mapping_outside_a_phone_group_does_not_make_a_phone(client, reader, db):
    _shop(reader)
    register_and_approve(client)
    _map_phone(db, kala_code=104)                       # 104 = group 2 (accessories)
    p = client.get("/products/104", headers=h("bot")).json()
    assert p["priced_by"] == "accounting" and p["unit_price"] == 30.0
    client.post("/admin/sales/action", json={"action": "close"}, headers=h("admin"))
    assert _order(client, [{"kala_code": 104, "qty": 1}]).status_code == 201


# ---- 10: groups shown in the bot -----------------------------------------------------------
def test_only_selected_groups_reach_customers(client, reader, db):
    _shop(reader)
    reader.products[700] = {"name": "Internal part", "group": 4, "stock": 9.0, "open": 0.0,
                            "unit_price": 10.0, "image": None}
    register_and_approve(client)
    groups = [g["code"] for g in client.get("/groups", headers=h("bot")).json()]
    assert groups == [1, 2, 3]
    assert client.get("/products", params={"group": 4}, headers=h("bot")).json()["items"] == []
    found = client.get("/products", params={"q": "Internal"}, headers=h("bot")).json()
    assert found["items"] == []
    assert client.get("/products/700", headers=h("bot")).status_code == 404
    assert _order(client, [{"kala_code": 700, "qty": 1}]).status_code == 422


def test_nothing_is_shown_before_groups_are_chosen(client, reader, db):
    _shop(reader)
    db._conn.execute("DELETE FROM product_groups")
    assert client.get("/groups", headers=h("bot")).json() == []
    assert client.get("/products", headers=h("bot")).json()["items"] == []
    assert client.get("/shop/state", headers=h("bot")).json()["catalog_ready"] is False


def test_lists_have_only_in_stock_items(client, reader):
    _shop(reader)
    codes = [p["code"] for p in client.get("/products", headers=h("bot")).json()["items"]]
    assert 102 not in codes                          # stock 0
    assert 103 not in codes                          # price 0


def test_admin_product_groups(client, reader, db):
    _shop(reader)
    admin = staff(db)
    assert client.get("/admin/product-groups",
                      headers=staff(db, "viewer")).status_code == 403   # v2.7.0: admin only
    rows = client.get("/admin/product-groups", headers=admin).json()
    by = {r["code"]: r for r in rows}
    assert by[3]["is_phone"] and by[3]["show_in_bot"] and not by[4]["show_in_bot"]
    r = client.put("/admin/product-groups", json={"groups": [
        {"code": 4, "show_in_bot": True, "is_phone": False},
        {"code": 2, "show_in_bot": False, "is_phone": False}]}, headers=admin)
    assert r.status_code == 200
    by = {r["code"]: r for r in r.json()}
    assert by[4]["show_in_bot"] and not by[2]["show_in_bot"] and by[1]["show_in_bot"]
    assert [g["code"] for g in client.get("/groups", headers=h("bot")).json()] == [1, 3, 4]
    assert "product_groups_changed" in events(db)
    dup = {"groups": [{"code": 1, "show_in_bot": True, "is_phone": False}] * 2}
    assert client.put("/admin/product-groups", json=dup, headers=admin).status_code == 422
    for other in (h("bot"), h("admin"), staff(db, "operator")):
        assert client.put("/admin/product-groups", json={"groups": []},
                          headers=other).status_code in (401, 403)


# ---- 8: v2.8.2 - no fixed card: staff send the payment details per order ----------------------
def test_no_card_is_needed_to_order(client, reader, settings):
    _shop(reader)
    register_and_approve(client)
    settings.payment_card_number = ""
    assert client.get("/shop/state", headers=h("bot")).json()["payment_ready"] is True
    assert _order(client, [{"kala_code": 101, "qty": 1}]).status_code == 201


def test_a_retry_still_gets_its_order_after_the_card_is_removed(client, reader, settings):
    _shop(reader)
    register_and_approve(client)
    first = _order(client, [{"kala_code": 101, "qty": 1}], key="r" * 16)
    settings.payment_card_number = ""
    again = _order(client, [{"kala_code": 101, "qty": 1}], key="r" * 16)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]


# ---- 12: unavailable item requests ---------------------------------------------------------
def test_item_requests(client, reader, db):
    _shop(reader)
    register_and_approve(client)
    found = client.get("/item-requests/search", params={"q": "Widget"}, headers=h("bot")).json()
    assert {f["code"] for f in found} >= {101, 102}           # also out of stock, no prices
    assert all(set(f) == {"code", "name"} for f in found)
    r = client.post("/item-requests", json={"platform": "bale", "chat_id": "111",
                                             "kala_code": 102}, headers=h("bot"))
    assert r.status_code == 201 and r.json()["product_name"] == "Widget B"
    r2 = client.post("/item-requests", json={"platform": "bale", "chat_id": "111",
                                              "text": "  گوشی   نوکیا ۳۳۱۰ "}, headers=h("bot"))
    assert r2.status_code == 201 and r2.json()["text"] == "گوشی نوکیا ۳۳۱۰"
    assert client.post("/item-requests", json={"platform": "bale", "chat_id": "111", "text": "x"},
                       headers=h("bot")).status_code == 422
    reader.products[700] = {"name": "Hidden", "group": 4, "stock": 0.0, "unit_price": 1.0}
    assert client.post("/item-requests", json={"platform": "bale", "chat_id": "111",
                                                "kala_code": 700}, headers=h("bot")).status_code == 404
    assert client.post("/item-requests", json={"platform": "bale", "chat_id": "999", "text": "abc"},
                       headers=h("bot")).status_code == 404
    # nothing written anywhere but our own table; staff see it
    rows = client.get("/admin/item-requests", headers=h("admin")).json()
    assert [r["id"] for r in rows] == [r2.json()["id"], r.json()["id"]]
    assert rows[0]["customer_name"] == "Ali" and rows[0]["person_code"] == 7001
    assert events(db).count("item_request") == 2
    done = client.post(f"/admin/item-requests/{r.json()['id']}/status", json={"status": "done"},
                       headers=h("admin"))
    assert done.status_code == 200 and done.json()["status"] == "done"
    assert len(client.get("/admin/item-requests", params={"status": "new"},
                          headers=h("admin")).json()) == 1
    assert client.post("/admin/item-requests/999/status", json={"status": "done"},
                       headers=h("admin")).status_code == 404


def test_item_requests_are_limited_per_day(client, reader):
    _shop(reader)
    register_and_approve(client)
    body = {"platform": "bale", "chat_id": "111", "text": "something"}
    codes = [client.post("/item-requests", json=body, headers=h("bot")).status_code
             for _ in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429


# ---- 13: statement PDF data ------------------------------------------------------------------
def test_full_statement_for_the_pdf(client, reader):
    _shop(reader)
    register_and_approve(client)
    reader.person_name_map = {7001: "علی آزمایشی"}
    reader.ledger[7001] = [
        {"id": 1, "date": "1405/07/01", "kind": "f", "doc_no": "10", "debit": 500.0,
         "credit": 0.0, "description": "فاکتور"},
        {"id": 2, "date": "1405/07/05", "kind": "x", "doc_no": "11", "debit": 0.0,
         "credit": 200.0, "description": "واریز"},
    ]
    body = client.get("/users/bale/111/statement/full", headers=h("bot")).json()
    assert body["person_code"] == 7001 and body["customer_name"] == "علی آزمایشی"
    assert body["from_date"] == "1405/07/01" and body["to_date"] == "1405/07/05"
    assert [r["balance"] for r in body["rows"]] == [500.0, 300.0]
    assert [r["side"] for r in body["rows"]] == ["debtor", "debtor"]
    assert body["total_debit"] == 500 and body["total_credit"] == 200
    assert body["balance"] == 300 and body["side"] == "debtor"
    assert body["opening_balance"] == 0 and body["opening_side"] == "zero"
    # without the name grant: the registration name
    reader.person_name_map = {}
    assert client.get("/users/bale/111/statement/full",
                      headers=h("bot")).json()["customer_name"] == "Ali"
    assert client.get("/users/bale/111/statement/full",
                      headers=h("site")).status_code == 403


def test_full_statement_only_for_approved(client, reader):
    _shop(reader)
    client.post("/users/register", json={"platform": "bale", "chat_id": "222", "name": "B",
                                         "phone": "09121234567"}, headers=h("bot"))
    assert client.get("/users/bale/222/statement/full", headers=h("bot")).status_code == 403


# ---- 3: person name in the staff order list ------------------------------------------------
def test_admin_orders_carry_the_person_name_and_code(client, reader):
    _shop(reader)
    register_and_approve(client)
    reader.person_name_map = {7001: "علی آزمایشی"}
    order = _order(client, [{"kala_code": 101, "qty": 1}]).json()
    rows = client.get("/admin/orders", params={"status": "awaiting_payment"},
                      headers=h("admin")).json()
    assert rows[0]["person_name"] == "علی آزمایشی" and rows[0]["user_person_code"] == 7001
    assert rows[0]["user_name"] == "Ali"
    one = client.get(f"/orders/{order['id']}", headers=h("admin")).json()
    assert one["person_name"] == "علی آزمایشی"
    # the bot never gets the accounting name
    mine = client.get(f"/orders/{order['id']}", params={"platform": "bale", "chat_id": "111"},
                      headers=h("bot")).json()
    assert mine["person_name"] is None


# ---- 9: ACCOUNTING_STATUS_CODE from ShopAdmin -------------------------------------------------
def test_status_code_is_editable_with_the_same_validation():
    assert "ACCOUNTING_STATUS_CODE" in control.EDITABLE
    assert control.validate_settings({"ACCOUNTING_STATUS_CODE": "0"}) == {}
    assert control.validate_settings({"ACCOUNTING_STATUS_CODE": "12"}) == {}
    for bad in ("6808", "", "-1", "abc", "1.5"):
        assert "ACCOUNTING_STATUS_CODE" in control.validate_settings(
            {"ACCOUNTING_STATUS_CODE": bad}), bad


def test_version():
    assert control.VERSION == "2.16.0"


def test_staff_see_every_group(client, reader, db):
    _shop(reader)
    reader.products[700] = {"name": "Internal part", "group": 4, "stock": 9.0, "open": 0.0,
                            "unit_price": 10.0, "image": None}
    viewer = staff(db)                      # v2.7.0: a sales user may not list products
    assert client.get("/products", headers=staff(db, "operator", "s1")).status_code == 403
    assert [g["code"] for g in client.get("/groups", headers=viewer).json()] == [1, 2, 3, 4]
    codes = [p["code"] for p in client.get("/products", headers=viewer).json()["items"]]
    assert 700 in codes and PHONE in codes
