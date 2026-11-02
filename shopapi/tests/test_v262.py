"""v2.6.2: permanent + smart price-list mapping, color then part for phones (saved on the
order line and in the Sazeh line description), and the customer's own order cancel."""
from __future__ import annotations

from app.pricelist import matching
from app.pricelist.repo import PriceListRepo

from .conftest import h, register_and_approve, seed_products
from .test_phase3 import _fake_list, _imp, _row, fake_parse, staff  # noqa: F401
from .test_v260 import events

PHONE = 900


# ---- keys --------------------------------------------------------------------------------------
def test_smart_key_tolerates_case_spacing_order_and_units():
    a = matching.smart_key("SAMSUNG", "A17 128GB Ram4", "ویتنام", "Black/Gray")
    b = matching.smart_key("samsung", " a17  ram4 128 ", "ويتنام", "gray / black")
    c = matching.smart_key("SAMSUNG", "A17 128 R4", "ویتنام", "Gray/Black")
    assert a == b == c
    assert a != matching.smart_key("SAMSUNG", "A17 256GB Ram4", "ویتنام", "Black/Gray")
    assert matching.smart_key("T", "Tab S10 FE+", "", "") != matching.smart_key("T", "Tab S10 FE", "", "")


def test_part_codes_and_model_key():
    assert matching.part_code("17 Promax 512 ZAA") == "ZAA"
    assert matching.part_code("17 256 CHA") == "CHA"
    assert matching.part_code("A17 128GB Ram4") == "" and matching.part_code("Watch SE 44") == ""
    assert matching.model_key("iPHONE", "17 Promax 512 ZAA") == \
        matching.model_key("iphone", "17 promax 512 CHA")
    assert matching.model_key("iPHONE", "17 Promax 512") != matching.model_key("iPHONE", "17 512")


# ---- auto matching on import ------------------------------------------------------------------
def _decide(repo, list_id, desc, color, action="map", code=PHONE, label="", kind="شرکتی"):
    row = next(r for r in repo.rows(list_id) if r["description"] == desc and r["color"] == color
               and r["kind"] == kind)
    return repo.upsert_mapping(row_key=row["row_key"], action=action,
                               kala_code=code if action == "map" else None, color_label=label,
                               section=row["section"], description=row["description"],
                               kind=row["kind"], color=row["color"], actor="t")


def test_new_list_auto_maps_respelled_rows_new_colors_and_parts(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list(extra=[_row("17 Pro 256 ZAA", "Silver", 500000, None),
                                         _row("Watch 11 46", "Silver", 90000, None)])
    repo = PriceListRepo(db)
    first = _imp(db, settings, b"A").list_id
    _decide(repo, first, "17 Pro 256 ZAA", "Silver", label="نقره‌ای")
    _decide(repo, first, "Watch 11 46", "Silver", action="ignore")
    fake_parse[b"B"] = _fake_list("1405/07/20", extra=[
        _row("17 PRO ZAA 256GB", "silver", 501000, None),    # respelled: same row
        _row("17 Pro 256 ZAA", "Orange", 502000, None),      # new color
        _row("17 Pro 256 CHA", "Silver", 480000, None),      # new part
        _row("Watch 11 46", "Gray", 90000, None),            # new color of an ignored model
        _row("18 Pro 256 ZAA", "Silver", 600000, None),      # a truly new model
    ])
    result = _imp(db, settings, b"B")
    assert result.auto_mapped == 4
    rows = {(r["description"], r["color"]): r for r in repo.rows(result.list_id)}
    respelled = rows[("17 PRO ZAA 256GB", "silver")]
    assert respelled["action"] == "map" and respelled["kala_code"] == PHONE
    assert respelled["color_label"] == "نقره‌ای" and respelled["auto"] == 1
    assert respelled["auto_reason"] == "same_row"
    for key in (("17 Pro 256 ZAA", "Orange"), ("17 Pro 256 CHA", "Silver")):
        assert rows[key]["kala_code"] == PHONE and rows[key]["auto_reason"] == "same_model"
    assert rows[("Watch 11 46", "Gray")]["action"] == "ignore"
    assert rows[("18 Pro 256 ZAA", "Silver")]["action"] is None          # stays unmapped
    # decisions are permanent: the same list again asks nothing new
    fake_parse[b"C"] = _fake_list("1405/07/21", extra=[_row("17 Pro 256 ZAA", "Orange", 1, None)])
    third = _imp(db, settings, b"C")
    orange = next(r for r in repo.rows(third.list_id) if r["color"] == "Orange")
    assert orange["action"] == "map"


def test_model_split_over_products_is_not_guessed(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list(extra=[_row("X9 256", "Black", 1, None),
                                         _row("X9 256", "Blue", 1, None),
                                         _row("X9 256", "Gold", 1, None)])
    repo = PriceListRepo(db)
    first = _imp(db, settings, b"A").list_id
    _decide(repo, first, "X9 256", "Black", code=900)
    _decide(repo, first, "X9 256", "Blue", code=901)
    assert matching.auto_match(repo, first) == 0
    gold = next(r for r in repo.rows(first) if r["color"] == "Gold")
    assert gold["action"] is None


def test_review_confirm_undo_and_filter(client, db, reader, settings, fake_parse):
    seed_products(reader)
    reader.products[PHONE] = {"name": "iPhone 17 Pro", "group": 3, "stock": 0.0,
                              "unit_price": 0.0, "image": None}
    fake_parse[b"A"] = _fake_list(extra=[_row("17 Pro 256 ZAA", "Silver", 500000, None),
                                         _row("17 Pro 256 ZAA", "Orange", 500000, None),
                                         _row("17 Pro 256 CHA", "Blue", 480000, None)])
    _imp(db, settings, b"A")
    admin = staff(db)
    rows = client.get("/admin/pricelists/rows", headers=admin).json()["rows"]
    silver = next(r for r in rows if r["color"] == "Silver")
    client.put("/admin/price-mappings", json={"row_key": silver["row_key"], "action": "map",
                                              "kala_code": PHONE}, headers=admin)
    data = client.get("/admin/pricelists/rows", params={"filter": "auto"}, headers=admin).json()
    assert data["counts"]["auto"] == 2 and {r["color"] for r in data["rows"]} == {"Orange", "Blue"}
    orange, blue = sorted(data["rows"], key=lambda r: r["color"] != "Orange")
    # confirm one, undo the other
    ok = client.post(f"/admin/price-mappings/{orange['mapping_id']}/confirm", headers=admin)
    assert ok.status_code == 200 and ok.json()["auto"] == 0
    assert client.delete(f"/admin/price-mappings/{blue['mapping_id']}",
                         headers=admin).status_code == 204
    # an undone row is never matched automatically again
    assert client.post("/admin/price-mappings/auto", headers=admin).json() == {"auto_mapped": 0}
    after = {r["color"]: r for r in
             client.get("/admin/pricelists/rows", headers=admin).json()["rows"]}
    assert after["Blue"]["action"] is None and after["Orange"]["auto"] == 0
    assert client.post("/admin/price-mappings/999/confirm", headers=admin).status_code == 404
    viewer = staff(db, "viewer")
    assert client.post("/admin/price-mappings/auto", headers=viewer).status_code == 403


# ---- color then part ---------------------------------------------------------------------------
def _phone_with_parts(client, db, reader, settings, fake_parse):
    seed_products(reader)
    reader.products[PHONE] = {"name": "iPhone 17 Pro", "group": 3, "stock": 0.0,
                              "unit_price": 0.0, "image": None}
    fake_parse[b"A"] = _fake_list(extra=[_row("17 Pro 256 ZAA", "Silver", 500000, None),
                                         _row("17 Pro 256 CHA", "Silver", 480000, None),
                                         _row("17 Pro 256 ZAA", "Orange", 510000, None)])
    list_id = _imp(db, settings, b"A").list_id
    repo = PriceListRepo(db)
    for desc, color in (("17 Pro 256 ZAA", "Silver"), ("17 Pro 256 CHA", "Silver"),
                        ("17 Pro 256 ZAA", "Orange")):
        _decide(repo, list_id, desc, color)
    register_and_approve(client)
    return client.get(f"/products/{PHONE}", headers=h("bot")).json()


def test_variants_carry_part_and_order_keeps_it(client, db, reader, settings, writer, fake_parse):
    product = _phone_with_parts(client, db, reader, settings, fake_parse)
    variants = {(v["color"], v["part"]): v for v in product["variants"]}
    assert set(variants) == {("Silver", "ZAA"), ("Silver", "CHA"), ("Orange", "ZAA")}
    assert variants[("Silver", "CHA")]["unit_price"] < variants[("Silver", "ZAA")]["unit_price"]
    chosen = variants[("Silver", "CHA")]
    r = client.post("/orders", json={"platform": "bale", "chat_id": "111", "items": [
        {"kala_code": PHONE, "qty": 1, "variant_id": chosen["id"]}]}, headers=h("bot"))
    assert r.status_code == 201, r.text
    line = r.json()["items"][0]
    assert line["color"] == "Silver" and line["part"] == "CHA"
    assert line["variant"] == "Silver — CHA" and line["name"] == "iPhone 17 Pro — Silver — CHA"
    stored = db.get_order_items(r.json()["id"])[0]
    assert (stored["color"], stored["part"]) == ("Silver", "CHA")
    # the line description in «سازه حساب» names the color and the part
    order_id = r.json()["id"]
    client.post(f"/orders/{order_id}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "r1"}, headers=h("bot"))
    client.post(f"/admin/orders/{order_id}/approve-payment", headers=h("admin"))
    assert writer.calls[-1][2] == [(PHONE, 1.0, chosen["unit_price"], "Silver — CHA")]


def test_type_is_a_part_only_when_a_product_has_several(db):
    from app.pricelist.catalog import PhoneCatalog

    one = PhoneCatalog(codes={1}, fresh=True, variants={1: [
        {"id": 1, "color": "Black", "part_code": "", "kind": "ویتنام", "price_rial": 10}]})
    assert one.colors(1)[0]["part"] == ""
    two = PhoneCatalog(codes={1}, fresh=True, variants={1: [
        {"id": 1, "color": "Black", "part_code": "", "kind": "ویتنام", "price_rial": 10},
        {"id": 2, "color": "Black", "part_code": "", "kind": "هند", "price_rial": 9}]})
    assert [v["part"] for v in two.colors(1)] == ["ویتنام", "هند"]


# ---- customer cancel ---------------------------------------------------------------------------
def _accessory_order(client, reader):
    seed_products(reader)
    register_and_approve(client)
    return client.post("/orders", json={"platform": "bale", "chat_id": "111", "items": [
        {"kala_code": 101, "qty": 1}]}, headers=h("bot")).json()


def _cancel(client, order_id, chat_id="111"):
    return client.post(f"/orders/{order_id}/cancel",
                       params={"platform": "bale", "chat_id": chat_id}, headers=h("bot"))


def test_customer_cancels_before_receipt(client, db, reader, writer):
    order = _accessory_order(client, reader)
    r = _cancel(client, order["id"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert db.get_order(order["id"])["cancel_reason"] == "customer"
    assert "order_cancelled_by_customer" in events(db)
    assert "order_cancel_written" not in events(db)
    assert db.pending_reservations().get(101, 0) == 0                  # stock released
    assert _cancel(client, order["id"]).status_code == 409             # once
    assert writer.calls == []                                          # Sazeh untouched


def test_no_cancel_after_receipt_or_by_someone_else(client, db, reader):
    order = _accessory_order(client, reader)
    register_and_approve(client, chat_id="222", person_code=7001, phone="09120000001")
    assert _cancel(client, order["id"], chat_id="222").status_code == 404
    assert _cancel(client, 9999).status_code == 404
    client.post(f"/orders/{order['id']}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "r1"}, headers=h("bot"))
    r = _cancel(client, order["id"])
    assert r.status_code == 409 and r.json()["detail"].startswith("Receipt already sent")
    assert db.get_order(order["id"])["status"] == "receipt_uploaded"
    assert client.post(f"/orders/{order['id']}/cancel", params={"platform": "bale",
                       "chat_id": "111"}, headers=h("site")).status_code == 403


def test_cancel_of_a_written_order_only_alerts_staff(client, db, reader, writer):
    order = _accessory_order(client, reader)
    db._conn.execute("UPDATE orders SET accounting_order_no=77 WHERE id=?", (order["id"],))
    db._conn.commit()
    assert _cancel(client, order["id"]).json()["status"] == "cancelled"
    assert "order_cancel_written" in events(db) and writer.calls == []


# ---- the Sazeh line description ----------------------------------------------------------------
def _sharh_conn(length):
    from .test_writer import FakeConn

    class Conn(FakeConn):
        def fetchone(self):
            if "CHARACTER_MAXIMUM_LENGTH" in self.executed[-1][0]:
                return (length,)
            return super().fetchone()

    return Conn()


def _detail_sharh(conn):
    return [params[5] for sql, params in conn.executed if "KalaOrderDetail" in sql
            and sql.strip().upper().startswith("INSERT")]


def test_writer_puts_color_and_part_in_the_line_description():
    from app.accounting_writer import AccountingWriter
    from app.config import Settings

    for length, expected in ((50, ["Silver — CHA", ""]), (6, ["Silver", ""]), (None, ["", ""])):
        conn = _sharh_conn(length)
        writer = AccountingWriter(Settings(accounting_database="hesab5 t", accounting_allowed_databases=("hesab5 t",), accounting_write_databases=("hesab5 t",),
                                           accounting_status_code=6808),
                                  connection_factory=lambda c=conn: c)
        result = writer.write_order(1, 7001, [(900, 1.0, 10.0, "Silver — CHA"), (101, 2.0, 5.0)])
        assert result.mablp == 20.0 and [it["codekala"] for it in result.items] == [900, 101]
        assert _detail_sharh(conn) == expected, length
