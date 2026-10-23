"""Phase 3: price-list parser, phone pricing, import safety, mapping, colors in
the catalogue/orders, inquiries, proxy pool and the worker endpoints."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.pricelist import importer, parser
from app.pricelist.parser import ParsedList, ParseError, PriceRow, parse_pdf, parse_words
from app.pricelist.pricing import change_pct, customer_price_rial
from app.pricelist.repo import PriceListRepo
from app.proxypool import (
    MIN_MAIN_KEEP,
    ProxyLink,
    ProxyPool,
    extract_proxy_links,
    normalize_secret,
    parse_proxy_link,
)
from app.staff import hash_token

from .conftest import h, register_and_approve, seed_products

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "price_list.pdf"
needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="samples/price_list.pdf missing")


def staff(db, role="admin", username=None) -> dict:
    """Bearer headers of a signed-in staff member with ``role``."""
    user = db.create_staff(username or f"u_{role}", "Test", role, "x")
    token = f"tok-{role}-{user['id']}"
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    db.create_session(hash_token(token), user["id"], expires)
    return {"Authorization": f"Bearer {token}"}


def events(db) -> list[str]:
    return [e["kind"] for e in db.list_events(0, 1000)]


# ---- parser ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sample_list() -> ParsedList:
    if not SAMPLE.exists():
        pytest.skip("samples/price_list.pdf missing")
    return parse_pdf(SAMPLE.read_bytes())


def _find(parsed, description, color, kind=None):
    for row in parsed.rows:
        if row.description == description and row.color == color and (
                kind is None or row.kind == kind):
            return row
    raise AssertionError(f"row not found: {description} {color}")


@needs_sample
def test_sample_pdf_parses(sample_list):
    assert sample_list.list_date == "1405/07/19"
    assert len(sample_list.rows) == 195
    assert sample_list.warnings == []
    assert len({r.key for r in sample_list.rows}) == len(sample_list.rows)
    for title in ("iPHONE", "APPLE WATCH", "MACBOOK", "XIAOMI", "IPAD & PEN", "SAMSUNG",
                  "TABLET SAMSUNG"):
        assert title in sample_list.sections


@needs_sample
def test_sample_rows(sample_list):
    row = _find(sample_list, "17 Promax 512 ZAA", "Orange")
    assert (row.section, row.kind, row.naghd, row.raval) == ("iPHONE", "شرکتی", 535000, 538000)
    # "…" / "..." = no price
    row = _find(sample_list, "Watch SE 40 2024", "Midnight")
    assert row.section == "APPLE WATCH" and row.naghd is None and row.raval is None
    # نقد only
    row = _find(sample_list, 'Macbook Pro (M5) 512 R16 14"', "Silver")
    assert (row.naghd, row.raval) == (454000, None)
    # type recognised from scrambled letters, also when split into fragments
    assert _find(sample_list, "S26 Ultra 256GB Ram12", "Black").kind == "ویتنام"
    assert _find(sample_list, "A17 256GB Ram8", "Blue", "هند").raval == 85000
    assert _find(sample_list, "Tivo Lite 128GB Ram6", "Black").kind == "شرکتی"
    assert _find(sample_list, "Tab S11 Ultra 5G 256/12", "Silver").section == "TABLET SAMSUNG"
    assert _find(sample_list, "Redmi Note 15 256GB Ram8", "Blue").naghd is None


def test_scrambled_persian_words():
    assert parser.decode_persian("تیکشر") == "شرکتی"
    assert parser.decode_persian("مانتیو") == "ویتنام"
    assert parser.decode_persian("دنه") == "هند"
    assert parser.letter_signature("دقن") == parser.letter_signature("نقد")


def test_parse_price():
    assert parser.parse_price("535,000") == 535000
    assert parser.parse_price("۵۲,۵۰۰") == 52500
    assert parser.parse_price("7,150") == 7150
    for value in ("…", "...", "Call", "", None, "12,34", "abc"):
        assert parser.parse_price(value) is None


def _words(rows=25, date=True, headers=True, kind=True):
    words = []
    if date:
        words.append({"text": "1405/07/20", "x0": 450, "top": 20})
    if headers:
        words += [{"text": "دقن", "x0": 150, "top": 40}, {"text": "لاور", "x0": 180, "top": 40}]
    for i in range(rows):
        top = 52 + i * 11
        words += [{"text": f"Model{i}", "x0": 17, "top": top},
                  {"text": "Black", "x0": 118, "top": top},
                  {"text": f"{100 + i},000", "x0": 145, "top": top - 1},
                  {"text": f"{101 + i},000", "x0": 174, "top": top - 1}]
        if kind:
            words.append({"text": "تیکشر", "x0": 96, "top": top - 2})
    return words


def test_parse_words_synthetic():
    parsed = parse_words(_words(), 595)
    assert parsed.list_date == "1405/07/20" and len(parsed.rows) == 25
    assert parsed.rows[0].naghd == 100000 and parsed.rows[0].kind == "شرکتی"


@pytest.mark.parametrize("kwargs, message", [
    ({"date": False}, "date"),
    ({"headers": False}, "headers"),
    ({"kind": False}, "type column"),
    ({"rows": 5}, "rows"),
])
def test_layout_changes_raise(kwargs, message):
    with pytest.raises(ParseError, match=message):
        parse_words(_words(**kwargs), 595)


def test_not_a_pdf():
    with pytest.raises(ParseError):
        parse_pdf(b"hello")
    with pytest.raises(ParseError):
        parse_pdf(b"%PDF-1.4 broken")


# ---- pricing ----------------------------------------------------------------------------
def test_customer_price_rules():
    assert customer_price_rial(535000, 538000) == 5_380_000_000          # روال
    assert customer_price_rial(52500, 52600) == 526_000_000
    assert customer_price_rial(52500, None) == 525_000_000 + 5_000_000    # نقد + 500,000 Toman
    assert customer_price_rial(None, None) is None
    assert customer_price_rial(0, 0) is None
    assert change_pct(100, 116) == pytest.approx(16.0)
    assert change_pct(None, 5) is None


# ---- import ------------------------------------------------------------------------------
def _row(desc, color, naghd, raval, section="iPHONE", kind="شرکتی"):
    return PriceRow(block=0, section=section, description=desc, kind=kind, color=color,
                    naghd=naghd, raval=raval)


def _fake_list(date="1405/07/19", price=100000, extra=()):
    rows = [_row(f"Phone {i}", "Black", price + i, price + i + 500) for i in range(30)]
    return ParsedList(list_date=date, rows=rows + list(extra), sections=["iPHONE"])


@pytest.fixture
def fake_parse(monkeypatch):
    holder = {}

    def fake(data: bytes):
        result = holder.get(data)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(importer, "parse_pdf", fake)
    return holder


def _imp(db, settings, data, **kw):
    return importer.import_pdf(db, settings, data, source=kw.pop("source", "manual"), **kw)


def test_first_import_activates_and_duplicate_is_ignored(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    first = _imp(db, settings, b"A")
    assert first.outcome == "active" and first.row_count == 30
    assert _imp(db, settings, b"A").outcome == "duplicate"
    assert events(db) == ["pricelist_imported"]
    rows = PriceListRepo(db).rows(first.list_id)
    assert rows[0]["price_rial"] == (100000 + 500) * 10_000


def test_older_list_is_not_applied(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list("1405/07/19")
    fake_parse[b"B"] = _fake_list("1405/07/18", price=1)
    active = _imp(db, settings, b"A").list_id
    assert _imp(db, settings, b"B").outcome == "older"
    assert PriceListRepo(db).active_list()["id"] == active
    # Same date: a later Telegram post wins, an earlier one does not.
    fake_parse[b"C"] = _fake_list("1405/07/20")
    fake_parse[b"D"] = _fake_list("1405/07/20", price=100001)
    assert _imp(db, settings, b"C", source="telegram",
                posted_at="2026-10-12T10:00:00+00:00").outcome == "active"
    assert _imp(db, settings, b"D", source="telegram",
                posted_at="2026-10-12T09:00:00+00:00").outcome == "older"


def _map_first(db, list_id, kala_code=900, n=1):
    repo = PriceListRepo(db)
    for row in repo.rows(list_id)[:n]:
        repo.upsert_mapping(row_key=row["row_key"], action="map", kala_code=kala_code,
                            color_label="", section=row["section"],
                            description=row["description"], kind=row["kind"],
                            color=row["color"], actor="t")


def test_big_change_of_a_mapped_row_holds_only_that_row(db, settings, fake_parse):
    """v2.9.1 price guard: the list applies; the mapped row moving more than 10 %
    keeps its old price until a manager approves the new one."""
    fake_parse[b"A"] = _fake_list()
    first = _imp(db, settings, b"A").list_id
    _map_first(db, first)
    old_price = PriceListRepo(db).rows(first)[0]["price_rial"]
    # +20% on every row: only the mapped one is held.
    fake_parse[b"B"] = _fake_list("1405/07/20", price=120000)
    result = _imp(db, settings, b"B")
    assert result.outcome == "active" and result.held_rows == 1
    assert PriceListRepo(db).active_list()["id"] == result.list_id
    rows = PriceListRepo(db).rows(result.list_id)
    assert rows[0]["price_rial"] == old_price and rows[0]["price_flag"] == "held"
    assert rows[0]["pending_price_rial"] == (120000 + 500) * 10_000
    assert rows[1]["price_rial"] == (120001 + 500) * 10_000 and rows[1]["price_flag"] == ""
    assert "price_held" in events(db) and "pricelist_held" not in events(db)


def test_big_change_of_unmapped_rows_does_not_hold(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    _imp(db, settings, b"A")
    fake_parse[b"B"] = _fake_list("1405/07/20", price=200000)
    assert _imp(db, settings, b"B").outcome == "active"


def test_small_change_applies(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    _map_first(db, _imp(db, settings, b"A").list_id, n=5)
    fake_parse[b"B"] = _fake_list("1405/07/20", price=110000)   # +10%
    assert _imp(db, settings, b"B").outcome == "active"


def test_missing_mapped_rows_hold(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    _map_first(db, _imp(db, settings, b"A").list_id, n=6)
    renamed = ParsedList("1405/07/20", [_row(f"Fone {i}", "Black", 1, 2) for i in range(30)])
    fake_parse[b"B"] = renamed
    result = _imp(db, settings, b"B")
    assert result.outcome == "held" and "missing" in result.reasons[-1]


def test_parse_failure_keeps_last_good_list(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    good = _imp(db, settings, b"A").list_id
    fake_parse[b"B"] = ParseError("price headers (نقد/روال) not found")
    result = _imp(db, settings, b"B")
    assert result.outcome == "failed"
    assert PriceListRepo(db).active_list()["id"] == good
    assert PriceListRepo(db).get_list(result.list_id)["status"] == "failed"
    assert events(db)[-1] == "pricelist_failed"


@needs_sample
def test_real_pdf_import_and_copy(db, settings, tmp_path):
    settings.pricelists_dir = str(tmp_path)
    result = importer.import_pdf(db, settings, SAMPLE.read_bytes(), source="manual")
    assert result.outcome == "active" and result.row_count == 195
    stored = PriceListRepo(db).get_list(result.list_id)["file_name"]
    assert (tmp_path / stored).read_bytes() == SAMPLE.read_bytes()


# ---- API: lists, approve/reject, mapping ---------------------------------------------
def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_upload_needs_pricelist_permission(client, db):
    body = {"data_b64": _b64(b"%PDF-1.4 x")}
    assert client.post("/admin/pricelists", json=body, headers=staff(db, "operator")).status_code == 403
    assert client.post("/admin/pricelists", json=body, headers=h("admin")).status_code == 403
    assert client.post("/admin/pricelists", json=body, headers=h("bot")).status_code == 403
    assert client.post("/admin/pricelists", json={"data_b64": _b64(b"not a pdf")},
                       headers=staff(db, "admin", "a2")).status_code == 422


def test_upload_failed_pdf_reports_failed(client, db):
    r = client.post("/admin/pricelists", json={"data_b64": _b64(b"%PDF-1.4 broken")},
                    headers=staff(db))
    assert r.status_code == 200 and r.json()["outcome"] == "failed"


@needs_sample
def test_upload_map_ignore_and_filters(client, db, reader):
    seed_products(reader)
    # v2.8.0: a name that matches no row (rows are mapped by name similarity now;
    # see test_v280.py) - this test is about the manual decisions
    reader.products[900] = {"name": "Phone sample X", "group": 3, "stock": 0.0,
                            "unit_price": 0.0, "image": None}
    admin = staff(db)
    r = client.post("/admin/pricelists", json={"data_b64": _b64(SAMPLE.read_bytes())},
                    headers=admin)
    assert r.json()["outcome"] == "active"
    rows = client.get("/admin/pricelists/rows", params={"filter": "unmapped"},
                      headers=admin).json()
    assert rows["counts"] == {"unmapped": 195, "mapped": 0, "ignored": 0, "auto": 0, "held": 0,
                              "corrected": 0, "all": 195}
    iphone = client.get("/admin/pricelists/rows", params={"section": "iPHONE"},
                        headers=admin).json()["rows"]
    assert {r["section"] for r in iphone} == {"iPHONE"} and len(iphone) == 19
    silver = next(r for r in iphone if r["description"] == "17 Promax 256 ZAA"
                  and r["color"] == "Silver")
    # unknown product -> 422; a product of ours -> mapped
    bad = {"row_key": silver["row_key"], "action": "map", "kala_code": 4242}
    assert client.put("/admin/price-mappings", json=bad, headers=admin).status_code == 422
    good = {**bad, "kala_code": 900, "color_label": "نقره‌ای"}
    mapping = client.put("/admin/price-mappings", json=good, headers=admin).json()
    assert mapping["kala_code"] == 900 and mapping["action"] == "map"
    # bulk ignore the Samsung tablets
    tablets = client.get("/admin/pricelists/rows", params={"section": "TABLET SAMSUNG"},
                         headers=admin).json()["rows"]
    r = client.post("/admin/price-mappings/ignore",
                    json={"row_keys": [t["row_key"] for t in tablets]}, headers=admin)
    assert r.json() == {"ignored": 15}
    counts = client.get("/admin/pricelists/rows", headers=admin).json()["counts"]
    # v2.6.2: the other colors of «17 Promax 256 ZAA» followed the staff decision
    assert counts == {"unmapped": 177, "mapped": 3, "ignored": 15, "auto": 2, "held": 0,
                      "corrected": 0, "all": 195}
    ignored = client.get("/admin/pricelists/rows", params={"filter": "ignored"},
                         headers=admin).json()["rows"]
    assert len(ignored) == 15
    # v2.7.0: a sales user (old "viewer") neither sees nor changes the price list
    viewer = staff(db, "viewer")
    assert client.get("/admin/pricelists", headers=viewer).status_code == 403
    assert client.put("/admin/price-mappings", json=good, headers=viewer).status_code == 403


def test_ignored_rows_stay_ignored_on_a_new_list(client, db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    first = _imp(db, settings, b"A").list_id
    key = PriceListRepo(db).rows(first)[3]["row_key"]
    admin = staff(db)
    client.post("/admin/price-mappings/ignore", json={"row_keys": [key]}, headers=admin)
    fake_parse[b"B"] = _fake_list("1405/07/20")
    _imp(db, settings, b"B")
    rows = client.get("/admin/pricelists/rows", params={"filter": "unmapped"},
                      headers=admin).json()["rows"]
    assert key not in {r["row_key"] for r in rows} and len(rows) == 29


def test_approve_and_reject_held_lists(client, db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    first = _imp(db, settings, b"A").list_id
    _map_first(db, first)
    # v2.9.1: a whole list is held only when most mapped rows are missing
    _map_first(db, first, n=6)
    renamed = [_row(f"Fone {i}", "Black", 1, 2) for i in range(30)]
    fake_parse[b"B"] = ParsedList("1405/07/20", renamed)
    fake_parse[b"C"] = ParsedList("1405/07/21", renamed + [_row("Other", "Red", 3, 4)])
    held_b = _imp(db, settings, b"B").list_id
    held_c = _imp(db, settings, b"C").list_id
    admin = staff(db)
    assert client.post(f"/admin/pricelists/{first}/approve", headers=admin).status_code == 409
    r = client.post(f"/admin/pricelists/{held_c}/approve", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert PriceListRepo(db).get_list(first)["status"] == "superseded"
    # B is older than the active C now
    assert client.post(f"/admin/pricelists/{held_b}/approve", headers=admin).status_code == 409
    r = client.post(f"/admin/pricelists/{held_b}/reject", json={"reason": "old"}, headers=admin)
    assert r.json()["status"] == "rejected"


# ---- catalogue / colors / orders -------------------------------------------------------
@pytest.fixture
def phone_shop(client, db, reader, settings, fake_parse):
    """Product 900 mapped to two colors (Black available, Blue without price),
    product 901 has an unmapped row, 902 only ignored rows."""
    seed_products(reader)
    for code in (900, 901, 902):
        reader.products[code] = {"name": f"Phone {code}", "group": 3, "stock": 0.0,
                                 "unit_price": 0.0, "image": None}
    rows = [
        _row("X1 256", "Black", 50000, 52500),
        _row("X1 256", "Blue", None, None),
        _row("X1 256", "Gold", 60000, None),
        _row("X2 128", "Red", 40000, 41000),
    ]
    fake_parse[b"A"] = _fake_list(extra=rows)
    list_id = _imp(db, settings, b"A").list_id
    repo = PriceListRepo(db)
    by = {(r["description"], r["color"]): r for r in repo.rows(list_id)}

    def put(desc, color, action, code=None, label=""):
        r = by[(desc, color)]
        return repo.upsert_mapping(row_key=r["row_key"], action=action, kala_code=code,
                                   color_label=label, section=r["section"],
                                   description=r["description"], kind=r["kind"],
                                   color=r["color"], actor="t")

    ids = {
        "black": put("X1 256", "Black", "map", 900, "مشکی")["id"],
        "blue": put("X1 256", "Blue", "map", 900)["id"],
        "gold": put("X1 256", "Gold", "map", 900, "طلایی")["id"],
    }
    put("X2 128", "Red", "ignore")
    register_and_approve(client)
    return ids


def test_product_shows_only_mapped_colors(client, phone_shop):
    p = client.get("/products/900", headers=h("bot")).json()
    assert p["priced_by"] == "pricelist"
    colors = {v["color"]: v for v in p["variants"]}
    assert set(colors) == {"مشکی", "Blue", "طلایی"}
    assert colors["مشکی"]["unit_price"] == 525_000_000 and colors["مشکی"]["available"]
    assert colors["طلایی"]["unit_price"] == 600_000_000 + 5_000_000
    assert colors["Blue"]["unit_price"] is None and not colors["Blue"]["available"]
    assert p["unit_price"] == 525_000_000          # lowest available color
    # 901: priced from accounting (0) and nothing mapped -> not for sale
    assert client.get("/products/901", headers=h("bot")).status_code == 404
    # accessories unchanged
    acc = client.get("/products/101", headers=h("bot")).json()
    assert acc["priced_by"] == "accounting" and acc["variants"] is None


def test_product_list_includes_phones(client, phone_shop):
    page = client.get("/products", params={"in_stock": "true"}, headers=h("bot")).json()
    codes = [it["code"] for it in page["items"]]
    assert 900 in codes and 901 not in codes and 902 not in codes
    assert 102 not in codes      # accessory without stock still filtered
    phone = next(it for it in page["items"] if it["code"] == 900)
    assert phone["available_qty"] == 1.0 and len(phone["variants"]) == 3


def _order(client, items):
    return client.post("/orders", json={"platform": "bale", "chat_id": "111", "items": items},
                       headers=h("bot"))


def test_order_phone_by_color(client, db, phone_shop):
    r = _order(client, [{"kala_code": 900, "qty": 1, "variant_id": phone_shop["black"]},
                        {"kala_code": 900, "qty": 2, "variant_id": phone_shop["gold"]},
                        {"kala_code": 101, "qty": 1}])
    assert r.status_code == 201, r.text
    items = {it["variant"]: it for it in r.json()["items"]}
    assert items["مشکی"]["unit_price"] == 525_000_000
    assert items["طلایی"]["qty"] == 2 and items["طلایی"]["name"].endswith("طلایی")
    assert r.json()["total"] == 525_000_000 + 2 * 605_000_000 + 100
    stored = db.get_order_items(r.json()["id"])
    assert {it["variant_id"] for it in stored} == {phone_shop["black"], phone_shop["gold"], None}


def test_order_phone_rules(client, phone_shop):
    assert _order(client, [{"kala_code": 900, "qty": 1}]).status_code == 422          # no color
    assert _order(client, [{"kala_code": 900, "qty": 1, "variant_id": phone_shop["blue"]}]
                  ).status_code == 409                                                   # no price
    assert _order(client, [{"kala_code": 900, "qty": 1, "variant_id": 99999}]).status_code == 422
    assert _order(client, [{"kala_code": 101, "qty": 1, "variant_id": phone_shop["black"]}]
                  ).status_code == 422                                                   # no colors


def test_stale_list_is_not_sold(client, db, settings, phone_shop):
    settings.pricelist_max_age_hours = 1
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    db._conn.execute("UPDATE price_lists SET activated_at=? WHERE status='active'", (old,))
    # v2.6.0: a phone outside the current valid list is hidden and not sold
    assert client.get("/products/900", headers=h("bot")).status_code == 404
    assert _order(client, [{"kala_code": 900, "qty": 1, "variant_id": phone_shop["black"]}]
                  ).status_code == 422


def test_approve_payment_skips_stock_for_phones(client, db, writer, phone_shop):
    order = _order(client, [{"kala_code": 900, "qty": 1, "variant_id": phone_shop["black"]}]).json()
    client.post(f"/orders/{order['id']}/receipt", params={"platform": "bale", "chat_id": "111"},
                json={"receipt_ref": "r1"}, headers=h("bot"))
    r = client.post(f"/admin/orders/{order['id']}/approve-payment", headers=h("admin"))
    assert r.status_code == 200, r.text
    # v2.6.2: the chosen color goes into the line description (KalaOrderDetail.sharh)
    assert writer.calls[-1][2] == [(900, 1.0, 525_000_000, "مشکی")]


def test_inquiry_for_unavailable_color(client, db, phone_shop):
    r = client.post("/inquiries", json={"platform": "bale", "chat_id": "111", "kala_code": 900,
                                        "variant_id": phone_shop["blue"]}, headers=h("bot"))
    assert r.status_code == 201 and r.json()["color"] == "Blue"
    assert events(db)[-1] == "price_inquiry"
    got = client.get(f"/admin/inquiries/{r.json()['id']}", headers=h("admin")).json()
    assert got["product_name"] == "Phone 900" and got["customer_name"] == "Ali"
    assert client.post("/inquiries", json={"platform": "bale", "chat_id": "nobody",
                                           "kala_code": 900}, headers=h("bot")).status_code == 404


# ---- proxy pool -----------------------------------------------------------------------------
SECRET = "0123456789abcdef0123456789abcdef"


def test_proxy_link_parsing():
    link = parse_proxy_link(f"tg://proxy?server=1.2.3.4&port=443&secret={SECRET}")
    assert link == ProxyLink("1.2.3.4", 443, SECRET) and link.kind == "plain"
    assert parse_proxy_link(f"https://t.me/proxy?server=Ex.com&port=8443&secret=dd{SECRET}"
                            ).kind == "dd"
    assert parse_proxy_link(f"t.me/proxy?server=ex.com&port=1&secret=ee{SECRET}676f6f"
                            ).kind == "ee"
    b64 = base64.urlsafe_b64encode(bytes.fromhex("ee" + SECRET + "676f6f")).decode().rstrip("=")
    assert parse_proxy_link(f"tg://proxy?server=a.b&port=2&secret={b64}").secret == \
        "ee" + SECRET + "676f6f"
    for bad in (
        "tg://socks?server=1.2.3.4&port=1080",
        f"tg://proxy?server=1.2.3.4&port=70000&secret={SECRET}",
        "tg://proxy?server=1.2.3.4&port=443&secret=abc",
        f"https://evil.com/proxy?server=1.2.3.4&port=443&secret={SECRET}",
        f"tg://proxy?server=bad host&port=443&secret={SECRET}",
    ):
        assert parse_proxy_link(bad) is None, bad
    assert normalize_secret("zz") is None


def test_extract_links_from_a_post():
    text = (f"پروکسی جدید 👇\ntg://proxy?server=1.1.1.1&port=443&secret={SECRET}\n"
            f"https://t.me/proxy?server=2.2.2.2&port=443&secret=dd{SECRET}.\n"
            f"dup tg://proxy?server=1.1.1.1&port=443&secret={SECRET}")
    links = extract_proxy_links(text)
    assert [l.host for l in links] == ["1.1.1.1", "2.2.2.2"]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def days(self, n):
        self.now += timedelta(days=n)


def _pool(db):
    clock = Clock()
    return ProxyPool(db, clock), clock


def _add(pool, n, state="probation"):
    return [pool.add(ProxyLink(f"10.0.0.{i}", 443, SECRET), "test", state=state)[0]["id"]
            for i in range(n)]


def test_probation_is_promoted_after_good_days(db):
    pool, clock = _pool(db)
    [pid] = _add(pool, 1)
    for _ in range(2):
        pool.record(pid, True)
        clock.days(1)
    assert pool.evaluate() == [] and pool.get(pid)["state"] == "probation"
    pool.record(pid, True)
    assert pool.evaluate() == [(pid, "main")]


def test_probation_dropped_after_bad_days_main_kept_longer(db):
    pool, clock = _pool(db)
    mains = _add(pool, MIN_MAIN_KEEP + 1, "main")
    [newbie] = [pool.add(ProxyLink("9.9.9.9", 443, SECRET), "test")[0]["id"]]
    witness = mains[0]          # keeps working: the network is up
    for day in range(5):
        pool.record(witness, True)
        for pid in mains[1:] + [newbie]:
            pool.record(pid, False)
        changes = dict(pool.evaluate())
        if day == 2:
            assert changes == {newbie: "retired"}       # probation: 3 bad days
        elif day < 4:
            assert changes == {}
        clock.days(1)
    # main proxies after 5 bad days, but never below MIN_MAIN_KEEP
    states = [pool.get(pid)["state"] for pid in mains]
    assert states.count("main") == MIN_MAIN_KEEP and states.count("retired") == 1


def test_outage_days_do_not_count(db):
    pool, clock = _pool(db)
    mains = _add(pool, MIN_MAIN_KEEP + 2, "main")
    for _ in range(10):                 # everything failing: our own outage
        for pid in mains:
            pool.record(pid, False)
        assert pool.evaluate() == []
        clock.days(1)
    assert all(pool.get(pid)["state"] == "main" for pid in mains)


def test_ranking_prefers_proven_stability(db):
    pool, clock = _pool(db)
    veteran, fresh, flaky = _add(pool, 3, "main")
    for day in range(30):
        pool.record(veteran, day != 7)          # 29 of 30 good days
        if day >= 27:
            pool.record(fresh, True)            # 3 of 3
        pool.record(flaky, day % 2 == 0)
        clock.days(1)
    pool.record(veteran, True)
    pool.record(fresh, True)
    pool.record(flaky, True)
    order = [p["id"] for p in pool.ranked()]
    assert order == [veteran, fresh, flaky]
    # a failing proxy drops behind the others of its tier at once
    clock.now += timedelta(minutes=1)
    pool.record(veteran, False)
    assert [p["id"] for p in pool.ranked()][-1] == veteran


def test_all_dead_alert_once(db):
    pool, clock = _pool(db)
    ids = _add(pool, 2, "main")
    for pid in ids:
        pool.record(pid, True)
    clock.now += timedelta(minutes=1)
    for pid in ids:
        pool.record(pid, False)
    assert not pool.should_alert_all_dead()        # worked a minute ago
    clock.now += timedelta(minutes=15)
    for pid in ids:
        pool.record(pid, False)
    assert pool.should_alert_all_dead()
    assert not pool.should_alert_all_dead()        # once per 6 h
    pool.record(ids[0], True)
    assert not pool.should_alert_all_dead()


# ---- worker / proxy endpoints ------------------------------------------------------------
@pytest.fixture
def worker(settings):
    settings.worker_api_key = "worker-key"
    return {"X-API-Key": "worker-key"}


def test_worker_key_is_worker_only(client, worker, phone_shop):
    assert client.get("/products/900", headers=worker).status_code == 403
    assert client.get("/admin/pricelists", headers=worker).status_code == 403
    assert client.post("/orders", json={"platform": "bale", "chat_id": "111",
                                        "items": [{"kala_code": 101, "qty": 1}]},
                       headers=worker).status_code == 403
    assert client.get("/worker/proxies", headers=h("bot")).status_code == 403
    assert client.get("/worker/proxies", headers=h("admin")).status_code == 403
    assert client.get("/worker/proxies", headers=worker).status_code == 200


def test_worker_key_is_loopback_only(client, worker, settings):
    settings.service_keys_local_only = True
    assert client.get("/worker/proxies", headers=worker).status_code == 401


@needs_sample
def test_worker_uploads_pdf(client, db, worker):
    r = client.post("/worker/pricelists", headers=worker, json={
        "data_b64": _b64(SAMPLE.read_bytes()), "source_ref": "AbrishamiiPhoneMashhad/812",
        "posted_at": "2026-10-11T09:00:00+00:00"})
    assert r.json()["outcome"] == "active"
    plist = PriceListRepo(db).active_list()
    assert plist["source"] == "telegram" and plist["source_ref"] == "AbrishamiiPhoneMashhad/812"


def test_worker_state_whitelist(client, worker):
    assert client.put("/worker/state", json={"key": "tg_price_last_id", "value": "812"},
                      headers=worker).status_code == 200
    assert client.get("/worker/state", headers=worker).json()["tg_price_last_id"] == "812"
    assert client.put("/worker/state", json={"key": "shop_closed", "value": "1"},
                      headers=worker).status_code == 422


def test_worker_proxy_flow(client, db, worker):
    super_admin = staff(db, "super_admin")
    links = [f"tg://proxy?server=1.1.1.{i}&port=443&secret={SECRET}" for i in range(3)]
    r = client.post("/worker/proxies/candidates", headers=worker,
                    json={"links": links + ["junk"], "source": "channel:proxyA"})
    assert r.json() == {"added": 3, "invalid": 1, "skipped": 0}
    ranked = client.get("/worker/proxies", headers=worker).json()
    assert len(ranked) == 3 and ranked[0]["secret"] == SECRET
    report = {"results": [{"id": p["id"], "ok": False} for p in ranked]}
    assert client.post("/worker/proxies/report", json=report, headers=worker).json()["recorded"] == 3
    # staff see masked secrets only; operators/admins cannot see the pool
    listed = client.get("/admin/proxies", headers=super_admin).json()
    assert "secret" not in listed[0] and listed[0]["secret_masked"].endswith("cdef")
    assert client.get("/admin/proxies", headers=staff(db, "operator")).status_code == 403
    # manual entry straight into the main list
    r = client.post("/admin/proxies", headers=super_admin, json={
        "link": f"https://t.me/proxy?server=5.5.5.5&port=443&secret=dd{SECRET}", "main": True})
    assert r.status_code == 201 and r.json()["state"] == "main"
    assert client.post("/admin/proxies", headers=super_admin,
                       json={"link": "tg://proxy?server=x"}).status_code == 422
    pid = r.json()["id"]
    assert client.post(f"/admin/proxies/{pid}/state", json={"state": "disabled"},
                       headers=super_admin).json()["state"] == "disabled"
    assert client.delete(f"/admin/proxies/{pid}", headers=super_admin).status_code == 204


def test_worker_alerts_are_rate_limited(client, db, worker):
    body = {"kind": "telegram_login_required"}
    assert client.post("/worker/alerts", json=body, headers=worker).json() == {"sent": True}
    assert client.post("/worker/alerts", json=body, headers=worker).json() == {"sent": False}
    assert client.post("/worker/alerts", json={"kind": "x"}, headers=worker).status_code == 422
    assert events(db).count("telegram_login_required") == 1


def test_schema_has_no_secret_in_events(db, settings, fake_parse):
    fake_parse[b"A"] = _fake_list()
    _imp(db, settings, b"A")
    assert all(set(e) == {"id", "ts", "kind", "ref_id", "actor"} for e in db.list_events(0))
