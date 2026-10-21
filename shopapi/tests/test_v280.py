"""v2.8.0: smart phone search, mapping by name similarity, «درخواست خرید», ownership
and handover (enforced by the API), the activity log, the weekly archive and
read-only finished orders."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import archive, ownership, phone_search
from app.pricelist.matching import confident, name_candidates, name_match
from app.pricelist.repo import PriceListRepo

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import staff
from .test_v260 import events

PRO = 600      # «آیفون ۱۷ پرو ۲۵۶ گیگ» in a phone group, in stock
A55 = 601      # «سامسونگ گلکسی A55 256 گیگ» in a phone group, no stock

ROWS = [
    ("i17p-zaa-silver", "iPHONE", "17 Pro 256 ZAA", "شرکتی", "Silver", 1_200_000_000),
    ("i17p-cha-silver", "iPHONE", "17 Pro 256 CHA", "شرکتی", "Silver", 1_150_000_000),
    ("i17pm-zaa-blue", "iPHONE", "17 Promax 256 ZAA", "شرکتی", "Blue", 1_500_000_000),
    ("a55-navy", "SAMSUNG", "A55 256GB Ram8", "ویتنام", "Navy", 110_000_000),
    ("s26u-black", "SAMSUNG", "S26 Ultra 256GB Ram12", "ویتنام", "Black", 465_000_000),
]


def _shop(reader):
    seed_products(reader)
    reader.products[PRO] = {"name": "آیفون ۱۷ پرو ۲۵۶ گیگ", "group": 3, "stock": 2.0,
                            "open": 0.0, "unit_price": 1.0, "image": None}
    reader.products[A55] = {"name": "سامسونگ گلکسی A55 256 گیگ", "group": 3, "stock": 0.0,
                            "open": 0.0, "unit_price": 1.0, "image": None}
    reader.groups = [{"code": 1, "name": "Group 1"}, {"code": 2, "name": "Group 2"},
                     {"code": 3, "name": "Phones"}]


def _list(db) -> int:
    repo = PriceListRepo(db)
    rows = [{"row_key": k, "block": 0, "section": sec, "description": desc, "kind": kind,
             "color": color, "naghd": price // 10_000, "raval": None, "price_rial": price}
            for k, sec, desc, kind, color, price in ROWS]
    list_id = repo.insert_list(list_date="1405/07/26", sha256="v280", source="manual",
                               source_ref="", posted_at=None, status="held", reason="", rows=rows)
    repo.activate(list_id)
    return list_id


def _map(db, row_key, code) -> int:
    row = next(r for r in ROWS if r[0] == row_key)
    return PriceListRepo(db).upsert_mapping(
        row_key=row_key, action="map", kala_code=code, color_label="", section=row[1],
        description=row[2], kind=row[3], color=row[4], actor="test")["id"]


@pytest.fixture
def shop(client, db, reader, settings):
    _shop(reader)
    _list(db)
    settings.phone_stock_required = True
    register_and_approve(client)
    return client


# ---- 2: search and normalization -----------------------------------------------------------------
@pytest.mark.parametrize("text, model", [
    ("آیفون ۱۷ پرو", "17 Pro 256"),
    ("17pro", "17 Pro 256"),
    ("iphone 17 pro 256", "17 Pro 256"),
    ("IPHONE17PRO ۲۵۶ گیگ", "17 Pro 256"),
    ("پرو ۱۷ آیفون", "17 Pro 256"),               # word order
    ("17 پرو مکس", "17 Promax 256"),
    ("سامسونگ a55 ۲۵۶", "A55 256GB Ram8"),
    ("گلکسی اس ۲۶ الترا", "S26 Ultra 256GB Ram12"),
])
def test_search_normalizes_any_spelling(text, model):
    rows = [{"row_key": k, "section": s, "description": d, "kind": kd, "color": c,
             "price_rial": p} for k, s, d, kd, c, p in ROWS]
    found = phone_search.search(rows, text)
    assert found and found[0]["model"] == model


def test_search_tokens_digits_case_gb():
    assert phone_search.search_tokens("IPhone۱۷Pro ۲۵۶GB") == ["iphone", "17", "pro", "256", "gb"]
    assert phone_search.search_tokens("17 Promax") == ["17", "pro", "max"]
    rows = [{"row_key": "x", "section": "iPHONE", "description": "17 Pro 256", "kind": "",
             "color": "Silver", "price_rial": 1}]
    assert phone_search.search(rows, "16 pro") == []           # another number: no
    assert phone_search.search(rows, "سلام") == []


def test_search_endpoint_marks_order_or_purchase(shop, db):
    _map(db, "i17p-zaa-silver", PRO)          # mapped, stock 2 -> order
    _map(db, "a55-navy", A55)                 # mapped, stock 0 -> purchase
    r = shop.get("/phones/search", params={"q": "آیفون ۱۷ پرو"}, headers=h("bot")).json()
    assert r["list_ready"] and r["items"][0]["model"] == "17 Pro 256"
    by_key = {i["row_key"]: i for i in r["items"]}
    assert by_key["i17p-zaa-silver"]["action"] == "order"
    assert by_key["i17p-zaa-silver"]["variant_id"] and by_key["i17p-zaa-silver"]["kala_code"] == PRO
    assert by_key["i17p-cha-silver"]["action"] == "purchase"         # not mapped
    assert by_key["i17p-cha-silver"]["part"] == "CHA"
    assert by_key["i17p-cha-silver"]["price"] == 1_150_000_000
    a55 = shop.get("/phones/search", params={"q": "a55"}, headers=h("bot")).json()["items"]
    assert [i["action"] for i in a55] == ["purchase"]                # no stock


def test_phone_without_stock_is_not_ordered(shop, db):
    variant = _map(db, "a55-navy", A55)
    r = shop.post("/orders", json={"platform": "bale", "chat_id": "111", "items": [
        {"kala_code": A55, "qty": 1, "variant_id": variant}]}, headers=h("bot"))
    assert r.status_code == 422 and "purchase request" in r.json()["detail"]


# ---- 3: mapping by name similarity -------------------------------------------------------------
def test_name_match_maps_confident_rows_only(db, reader):
    _shop(reader)
    list_id = _list(db)
    names = {PRO: "آیفون ۱۷ پرو ۲۵۶ گیگ", A55: "سامسونگ گلکسی A55 256 گیگ",
             700: "آیفون ۱۷ پرو مکس ۲۵۶", 701: "آیفون 17 Pro Max 256 گیگ"}
    repo = PriceListRepo(db)
    assert name_match(repo, list_id, names) == 3
    rows = {r["row_key"]: r for r in repo.rows(list_id)}
    assert rows["i17p-zaa-silver"]["kala_code"] == PRO and rows["i17p-zaa-silver"]["auto"]
    assert rows["i17p-zaa-silver"]["auto_reason"] == "name"
    assert rows["a55-navy"]["kala_code"] == A55
    # two products are equally close to «17 Promax 256»: ambiguous -> never mapped
    assert rows["i17pm-zaa-blue"]["action"] is None
    assert rows["s26u-black"]["action"] is None                        # no product


def test_undone_name_match_is_not_repeated(db, reader):
    list_id = _list(db)
    repo = PriceListRepo(db)
    repo.reject_auto("a55-navy", "boss")
    assert name_match(repo, list_id, {A55: "سامسونگ گلکسی A55 256 گیگ"}) == 0


def test_candidates_and_confidence():
    row = {"section": "iPHONE", "description": "17 Pro 256 ZAA", "color": "Silver"}
    names = {1: "آیفون ۱۷ پرو ۲۵۶ گیگ", 2: "قاب آیفون ۱۷ پرو", 3: "آیفون ۱۷ پرو ۵۱۲"}
    found = name_candidates(row, names)
    assert found[0]["code"] == 1 and confident(found)["code"] == 1
    assert all(c["code"] != 3 for c in found)                         # 512 is not 256


def test_suggestions_endpoint_top_three(shop, db):
    boss = staff(db, "super_admin", "boss")
    r = shop.get("/admin/price-mappings/suggestions", params={"row_key": "i17p-zaa-silver"},
                 headers=boss).json()
    assert r["items"][0]["code"] == PRO and r["confident"] == PRO and len(r["items"]) <= 3
    auto = shop.post("/admin/price-mappings/auto", headers=boss).json()
    assert auto["auto_mapped"] >= 2
    rows = shop.get("/admin/pricelists/rows", params={"filter": "auto"}, headers=boss).json()
    assert {r["row_key"] for r in rows["rows"]} >= {"i17p-zaa-silver", "a55-navy"}


# ---- 4: «درخواست خرید» -----------------------------------------------------------------------
def _request(shop, **payload) -> dict:
    r = shop.post("/purchase-requests", json={"platform": "bale", "chat_id": "111", **payload},
                  headers=h("bot"))
    assert r.status_code == 201, r.text
    return r.json()


def test_purchase_request_then_stock_confirmed_creates_an_order(shop, db):
    req = _request(shop, row_key="i17p-cha-silver")
    assert req["kind"] == "purchase" and req["color"] == "Silver" and req["part"] == "CHA"
    assert req["price_rial"] == 1_150_000_000 and req["kala_code"] is None
    assert "item_request" in events(db)
    mina = staff(db, "operator", "mina")
    listed = shop.get("/admin/item-requests", params={"kind": "purchase"}, headers=mina).json()
    assert [r["id"] for r in listed] == [req["id"]]
    # not mapped yet: the product is required
    url = f"/admin/item-requests/{req['id']}/confirm-stock"
    assert shop.post(url, json={}, headers=mina).status_code == 422
    order = shop.post(url, json={"kala_code": PRO, "price_rial": 1_100_000_000},
                      headers=mina).json()
    assert order["status"] == "awaiting_payment" and order["total"] == 1_100_000_000
    assert order["items"][0]["variant"] == "Silver — CHA" and order["request_id"] == req["id"]
    # v2.8.2: the deadline starts with «ارسال اطلاعات پرداخت»
    assert order["reserve_until"] is None and order["owned_by_me"]
    assert "purchase_order_created" in events(db)
    # the row is mapped now (also for later lists) and the request is finished
    assert PriceListRepo(db).mapping_for_key("i17p-cha-silver")["kala_code"] == PRO
    done = shop.get(f"/admin/item-requests/{req['id']}", headers=mina).json()
    assert done["status"] == "done" and done["outcome"] == "confirmed"
    assert done["order_id"] == order["id"] and done["finished"]
    assert shop.post(url, json={"kala_code": PRO}, headers=mina).status_code == 409
    # v2.8.2: staff send the payment details; then the bot can show them
    sent = shop.post(f"/admin/orders/{order['id']}/payment-info", headers=mina,
                     json={"card_number": "6037-0000-1111-2222", "holder": "فروشگاه"})
    assert sent.status_code == 200 and sent.json()["reserve_until"]
    got = shop.get(f"/orders/{order['id']}", params={"platform": "bale", "chat_id": "111"},
                   headers=h("bot")).json()
    assert got["payment_info"] == {"card_number": "6037-0000-1111-2222", "holder": "فروشگاه"}


def test_purchase_request_by_variant_and_unavailable(shop, db):
    variant = _map(db, "a55-navy", A55)
    req = _request(shop, kala_code=A55, variant_id=variant)
    assert req["kala_code"] == A55 and req["mapping_id"] == variant
    mina = staff(db, "operator", "mina")
    row = shop.post(f"/admin/item-requests/{req['id']}/unavailable", headers=mina).json()
    assert row["outcome"] == "unavailable" and row["status"] == "done"
    messages = shop.get(f"/admin/item-requests/{req['id']}/messages", headers=mina).json()
    assert len(messages) == 1 and "موجود نیست" in messages[0]["text"]
    assert "item_request_message" in events(db)


def test_stock_confirm_follows_the_sales_window(shop, db, settings):
    req = _request(shop, row_key="i17p-cha-silver")
    boss = staff(db, "super_admin", "boss")
    shop.post("/admin/sales/action", json={"action": "close"}, headers=boss)
    r = shop.post(f"/admin/item-requests/{req['id']}/confirm-stock",
                  json={"kala_code": PRO}, headers=boss)
    assert r.status_code == 409 and "Sales are closed" in r.json()["detail"]


def test_purchase_request_unknown_row(shop):
    r = shop.post("/purchase-requests", json={"platform": "bale", "chat_id": "111",
                                              "row_key": "nope"}, headers=h("bot"))
    assert r.status_code == 404


# ---- 6: ownership and handover --------------------------------------------------------------------
def _receipt_order(client, reader) -> int:
    seed_products(reader)
    register_and_approve(client)
    order = client.post("/orders", json={"platform": "bale", "chat_id": "111", "items": [
        {"kala_code": 101, "qty": 1}]}, headers=h("bot")).json()
    client.post(f"/orders/{order['id']}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "R-1"}, headers=h("bot"))
    return order["id"]


def _take(db, target_id: int, username: str, target: str = "order") -> None:
    """v2.8.2 (no «برمی‌دارم»): the first action of ``username`` takes the row."""
    from app.security import Identity

    row = db.get_staff_by_username(username)
    who = Identity(kind="staff", role=row["role"], username=username, user_id=row["id"],
                   permissions=frozenset({"orders.view", "orders.edit"}))
    ownership.take(db, who, target, db.get_order(target_id) if target == "order"
                   else db.get_item_request(target_id))


def test_first_action_takes_the_order_and_hides_it_from_others(client, db, reader):
    order_id = _receipt_order(client, reader)
    mina, sara = staff(db, "operator", "mina"), staff(db, "operator", "sara")
    boss = staff(db, "super_admin", "boss")
    for who in (mina, sara):     # a new order: every sales user sees it
        assert [o["id"] for o in client.get("/admin/orders", headers=who).json()] == [order_id]
    _take(db, order_id, "mina")
    r = client.get(f"/admin/orders/{order_id}", headers=mina).json()
    assert r["owned_by_me"] and r["owner_name"] is None          # no names for sales users
    assert client.get("/admin/orders", headers=sara).json() == []
    assert client.get(f"/admin/orders/{order_id}", headers=sara).status_code == 404
    assert client.get(f"/admin/orders/{order_id}/receipt", headers=sara).status_code == 404
    assert client.post(f"/admin/orders/{order_id}/reject-payment", headers=sara).status_code == 404
    # the manager sees everything, with the name
    seen = client.get("/admin/orders", headers=boss).json()
    assert seen[0]["owner_name"] == "Test" and not seen[0]["owned_by_me"]
    # «کارهای من»
    assert [o["id"] for o in client.get("/admin/orders", params={"mine": True},
                                        headers=mina).json()] == [order_id]
    assert client.get("/admin/orders", params={"mine": True}, headers=boss).json() == []


def test_action_by_a_second_user_on_a_taken_row_is_refused(client, db, reader):
    order_id = _receipt_order(client, reader)
    mina = staff(db, "operator", "mina")
    sara = db.create_staff("sara", "Sara", "operator", "x")
    _take(db, order_id, "mina")
    row = db.get_order(order_id)
    from app.security import Identity

    who = Identity(kind="staff", role="operator", username="sara", user_id=sara["id"],
                   permissions=frozenset({"orders.view"}))
    with pytest.raises(Exception) as err:
        ownership.take(db, who, "order", row)
    assert getattr(err.value, "status_code", None) == 403


def test_handover_by_owner_and_assign_permission(client, db, reader):
    order_id = _receipt_order(client, reader)
    mina = staff(db, "operator", "mina")
    sara_headers = staff(db, "operator", "sara")
    sara = db.get_staff_by_username("sara")
    reza_headers = staff(db, "operator", "reza")
    reza = db.get_staff_by_username("reza")
    _take(db, order_id, "mina")
    # a third user neither sees nor reassigns it
    assert client.post(f"/admin/orders/{order_id}/assign", json={"staff_id": reza["id"]},
                       headers=reza_headers).status_code == 404
    # the owner hands it over
    r = client.post(f"/admin/orders/{order_id}/assign", json={"staff_id": sara["id"]},
                    headers=mina)
    assert r.status_code == 200 and not r.json()["owned_by_me"]
    assert client.get("/admin/orders", headers=mina).json() == []
    mine = client.get("/admin/orders", headers=sara_headers).json()
    assert mine[0]["owned_by_me"]
    # the new owner sees what was done, without names
    steps = client.get(f"/admin/orders/{order_id}/timeline", headers=sara_headers).json()
    assert [s["action"] for s in steps] == ["claim", "handover"]
    assert all(s["actor_name"] is None for s in steps) and steps[1]["to_me"]
    # «ارجاع سفارش» tick: reassign an order that is not yours
    db.update_staff(reza["id"], perm_grant="assign.edit")
    assert client.post(f"/admin/orders/{order_id}/assign", json={"staff_id": reza["id"]},
                       headers=reza_headers).status_code == 404     # still hidden from reza
    boss = staff(db, "super_admin", "boss")
    r = client.post(f"/admin/orders/{order_id}/assign", json={"staff_id": reza["id"]},
                    headers=boss)
    assert r.status_code == 200
    steps = client.get(f"/admin/orders/{order_id}/timeline", headers=boss).json()
    assert steps[-1]["action"] == "assign" and steps[-1]["to_name"] == "Test"
    assert steps[0]["actor_name"] == "Test"
    assert events(db).count("order_assigned") == 2


def test_assign_tick_reassigns_a_free_order(client, db, reader):
    order_id = _receipt_order(client, reader)
    lead = staff(db, "operator", "lead")
    db.update_staff(db.get_staff_by_username("lead")["id"], perm_grant="assign.edit")
    staff(db, "operator", "sara")
    sara = db.get_staff_by_username("sara")
    r = client.post(f"/admin/orders/{order_id}/assign", json={"staff_id": sara["id"]},
                    headers=lead)
    assert r.status_code == 200
    plain = staff(db, "operator", "plain")
    staff(db, "operator", "other")
    other = db.get_staff_by_username("other")
    # sara's order now: hidden from a user without the tick
    assert client.post(f"/admin/orders/{order_id}/assign", json={"staff_id": other["id"]},
                       headers=plain).status_code == 404


def test_item_requests_follow_the_same_ownership(shop, db):
    req = _request(shop, row_key="i17p-cha-silver")
    mina, sara = staff(db, "operator", "mina"), staff(db, "operator", "sara")
    shop.put(f"/admin/item-requests/{req['id']}/note", json={"note": "call"}, headers=mina)
    assert shop.get("/admin/item-requests", headers=sara).json() == []
    assert shop.get(f"/admin/item-requests/{req['id']}", headers=sara).status_code == 404
    own = shop.get(f"/admin/item-requests/{req['id']}", headers=mina).json()
    assert own["note_by"] == "" and own["owned_by_me"]          # never a name
    boss = staff(db, "super_admin", "boss")
    assert shop.get(f"/admin/item-requests/{req['id']}", headers=boss).json()["note_by"] == "mina"
    steps = shop.get(f"/admin/item-requests/{req['id']}/timeline", headers=boss).json()
    assert [s["action"] for s in steps] == ["claim", "note"]


def test_assignees_are_names_only(client, db):
    mina = staff(db, "operator", "mina")
    staff(db, "operator", "sara")
    rows = client.get("/admin/assignees", headers=mina).json()
    assert rows == [{"id": db.get_staff_by_username("sara")["id"], "name": "Test"}]


# ---- 5: activity log --------------------------------------------------------------------------------
def test_activity_log_is_for_the_manager_with_filters(client, db, reader):
    order_id = _receipt_order(client, reader)
    mina = staff(db, "operator", "mina")
    client.post(f"/admin/orders/{order_id}/reject-payment", json={"reason": "x"}, headers=mina)
    assert client.get("/admin/activity", headers=mina).status_code == 403
    boss = staff(db, "super_admin", "boss")
    rows = client.get("/admin/activity", headers=boss).json()
    assert [r["action"] for r in rows][:2] == ["receipt_reject", "claim"]
    mina_id = db.get_staff_by_username("mina")["id"]
    assert client.get("/admin/activity", params={"staff_id": mina_id + 99},
                      headers=boss).json() == []
    user_id = db.get_order(order_id)["user_id"]
    by_customer = client.get("/admin/activity", params={"customer_id": user_id},
                             headers=boss).json()
    assert {r["action"] for r in by_customer} >= {"receipt_reject", "claim"}
    assert client.get("/admin/activity", params={"date_from": "2999-01-01"},
                      headers=boss).json() == []


def test_customer_decisions_are_logged(client, db):
    boss = staff(db, "super_admin", "boss")
    client.post("/users/register", json={"platform": "bale", "chat_id": "9", "name": "N",
                                         "phone": "09120000009"}, headers=h("bot"))
    user = client.get("/users/bale/9", headers=h("bot")).json()
    client.post(f"/admin/users/{user['id']}/reject", headers=boss)
    rows = client.get("/admin/activity", headers=boss).json()
    assert rows[0]["action"] == "customer_reject" and rows[0]["customer_id"] == user["id"]


# ---- 7: archive + read-only finished orders --------------------------------------------------------
def test_last_due_is_thursday_2330_tehran():
    # Friday 2026-10-23 10:00 UTC -> Thursday 2026-10-22 23:30 Tehran (20:00 UTC)
    due = archive.last_due(datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc))
    assert due.astimezone(timezone.utc) == datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)
    # Thursday 23:00 Tehran -> the week before
    due = archive.last_due(datetime(2026, 10, 22, 19, 30, tzinfo=timezone.utc))
    assert due.astimezone(timezone.utc) == datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)


def test_weekly_archive_moves_closed_rows_once(client, db, reader, settings):
    order_id = _receipt_order(client, reader)
    mina = staff(db, "operator", "mina")
    client.post(f"/admin/orders/{order_id}/reject-payment", headers=mina)
    db._conn.execute("UPDATE orders SET updated_at='2026-10-20T10:00:00+00:00'")
    later = datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc)
    assert archive.run_due(db, later) == {"orders": 1, "requests": 0}
    assert archive.run_due(db, later) is None                       # once per week
    assert client.get("/admin/orders", params={"status": "rejected"}, headers=mina).json() == []
    arch = client.get("/admin/archive/orders", headers=mina).json()
    assert [o["id"] for o in arch] == [order_id] and arch[0]["archived"] and arch[0]["finished"]
    # a sales user: own + the current fiscal year only
    db._conn.execute("UPDATE orders SET accounting_db='hesab4'")
    assert client.get("/admin/archive/orders", headers=mina).json() == []
    sara = staff(db, "operator", "sara")
    assert client.get("/admin/archive/orders", headers=sara).json() == []
    boss = staff(db, "super_admin", "boss")
    assert [o["id"] for o in client.get("/admin/archive/orders", headers=boss).json()] == [order_id]
    assert client.get("/admin/archive/orders", params={"q": "Ali"}, headers=boss).json()
    assert client.get("/admin/archive/orders", params={"q": "nobody"}, headers=boss).json() == []
    # read-only for everyone
    for path, body in ((f"/admin/orders/{order_id}/assign", {"staff_id": 1}),
                       (f"/admin/orders/{order_id}/cancel", None)):
        r = client.post(path, json=body, headers=boss)
        assert r.status_code == 409, path
    assert db.get_order(order_id)["status"] == "rejected"          # nothing deleted


def test_shipped_order_is_finished_and_read_only(client, db, reader, writer):
    order_id = _receipt_order(client, reader)
    boss = staff(db, "super_admin", "boss")
    client.post(f"/admin/orders/{order_id}/approve-payment", headers=boss)
    assert client.post(f"/admin/orders/{order_id}/ship", headers=boss).status_code == 200
    got = client.get(f"/admin/orders/{order_id}", headers=boss).json()
    assert got["finished"] and not got["archived"]
    staff(db, "operator", "x")
    r = client.post(f"/admin/orders/{order_id}/assign",
                    json={"staff_id": db.get_staff_by_username("x")["id"]}, headers=boss)
    assert r.status_code == 409


def test_finished_request_is_read_only(shop, db):
    req = _request(shop, row_key="i17p-cha-silver")
    boss = staff(db, "super_admin", "boss")
    shop.post(f"/admin/item-requests/{req['id']}/unavailable", headers=boss)
    for method, path, body in (
            ("PUT", f"/admin/item-requests/{req['id']}/note", {"note": "x"}),
            ("POST", f"/admin/item-requests/{req['id']}/status", {"status": "new"}),
            ("POST", f"/admin/item-requests/{req['id']}/messages", {"text": "hi"})):
        assert shop.request(method, path, json=body, headers=boss).status_code == 409, path
    db._conn.execute("UPDATE item_requests SET handled_at='2026-10-20T10:00:00+00:00'")
    assert archive.archive_now(db, "boss", cutoff="2026-10-21T00:00:00+00:00")["requests"] == 1
    assert shop.get("/admin/item-requests", headers=boss).json() == []
    assert len(shop.get("/admin/archive/item-requests", headers=boss).json()) == 1


def test_purchase_status_done_needs_an_answer(shop, db):
    req = _request(shop, row_key="i17p-cha-silver")
    boss = staff(db, "super_admin", "boss")
    r = shop.post(f"/admin/item-requests/{req['id']}/status", json={"status": "done"},
                  headers=boss)
    assert r.status_code == 409


def test_new_permission_has_a_label():
    from app import staff as st

    assert st.PERMISSION_LABELS[st.P_ORDERS_ASSIGN] == "ارجاع کار به همکار — تغییر"
    assert st.P_ORDERS_ASSIGN in st.PERMISSIONS["operator"]        # v2.8.3: always on
    assert st.P_ORDERS_ASSIGN in st.PERMISSIONS["super_admin"]
