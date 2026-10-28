"""v2.9.1: price-channel text posts (corrections «اصلاحیه», «فروش بسته»), the
per-row price guard, learned «روال − نقد» differences, the newest existing list
post, joined channels and their roles, every proxy-link format."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import sales, tgchannels
from app.pricelist import importer, notes
from app.pricelist.parser import ParsedList, PriceRow
from app.pricelist.repo import PriceListRepo
from app.proxypool import parse_proxy_link

from .test_phase3 import events, staff


def _row(desc, color, naghd, raval, section="SAMSUNG", kind="ویتنام"):
    return PriceRow(block=2, section=section, description=desc, kind=kind, color=color,
                    naghd=naghd, raval=raval)


BASE = [
    _row("A17 128GB Ram6", "Black", 72000, 72500),
    _row("A17 128GB Ram6", "Blue/Gray", 72000, 72500),
    _row("A17 128GB Ram6", "Blue", 71500, 72000, kind="هند"),
    _row("A07 (Full) 128GB Ram4", "Black", 50000, 50500, kind="شرکتی"),
    _row("A07 128GB Ram4", "Black", 49800, 50300, kind="شرکتی"),
    _row("A07 128GB Ram4", "Violet/Green", 49800, 50300, kind="شرکتی"),
    _row("A26 128GB Ram6", "Black", 79000, 79500),
] + [_row(f"Filler {i} 64GB Ram4", "Black", 30000 + i, 30400 + i) for i in range(20)]


def _list(date="1405/07/30", rows=None):
    return ParsedList(list_date=date, rows=list(rows or BASE), sections=["SAMSUNG"])


@pytest.fixture
def fake_parse(monkeypatch):
    holder = {}
    monkeypatch.setattr(importer, "parse_pdf", lambda data: holder[data])
    return holder


@pytest.fixture
def worker(settings):
    settings.worker_api_key = "worker-key"
    return {"X-API-Key": "worker-key"}


def _imp(db, settings, data, **kw):
    return importer.import_pdf(db, settings, data, source=kw.pop("source", "telegram"), **kw)


def _map(db, list_id, description, kala_code=900):
    repo = PriceListRepo(db)
    for row in repo.rows(list_id):
        if row["description"] == description:
            repo.upsert_mapping(row_key=row["row_key"], action="map", kala_code=kala_code,
                                color_label="", section=row["section"],
                                description=row["description"], kind=row["kind"],
                                color=row["color"], actor="t")


def _rows(db, list_id, description):
    return [r for r in PriceListRepo(db).rows(list_id) if r["description"] == description]


# ---- classification / parsing -----------------------------------------------------------
@pytest.mark.parametrize("text", ["فروش بسته", "فروش موقتاً بسته است", "فروش موقتا بسته",
                                  "فروش تا اطلاع ثانوی بسته میباشد", "پایان فروش امروز",
                                  "فروش امروز تعطیل است"])
def test_sales_closed_wordings(text):
    assert notes.classify(text) == notes.KIND_CLOSED


@pytest.mark.parametrize("text", ["فروش باز شد", "بسته کوچک A07", "سلام همکاران عزیز",
                                  "لیست جدید ارسال شد", "فروش ویژهٔ بسته‌های شارژر",
                                  "فروش بسته‌بندی جدید", "فروش بسته ۲ عددی کابل",
                                  "فروش بسته " + "متن طولانی " * 40])
def test_other_posts_are_ignored(text):
    assert notes.classify(text) == notes.KIND_IGNORED


def test_correction_lines_are_parsed():
    lines, bad = notes.parse_correction(
        "اصلاحیه\nA17 128-6 72.000\nA07 128-4 Small pack 48.500\nGalaxy S25 Ultra 256/12 ۳۷۱٬۰۰۰\n"
        "این یک توضیح است\nXYZ ??? 12")
    assert [(l.model, l.storage, l.ram, l.naghd) for l in lines] == [
        ("a17", 128, 6, 72000), ("a07", 128, 4, 48500), ("s25ultra", 256, 12, 371000)]
    assert lines[1].note == "small pack"
    assert bad == ["XYZ ??? 12"]
    assert notes.parse_price("72.5") == 72500 and notes.parse_price("9") is None


def test_row_models():
    full = notes.row_model("A07 (Full) 128GB Ram4")
    assert (full.model, full.storage, full.ram, full.extras) == ("a07", 128, 4, frozenset({"full"}))
    iphone = notes.row_model("17 Promax 256 ZAA")
    assert (iphone.model, iphone.storage, iphone.extras) == ("17promax", 256, frozenset({"zaa"}))
    assert notes.row_model("Redmi Note 15 Pro 5G 256GB Ram12").model == "redminote15pro5g"
    assert notes.row_model("Tab A11 WIFI 128/8").ram == 8


# ---- corrections ----------------------------------------------------------------------------
def test_correction_applies_to_every_color_and_alerts_unmatched(client, db, settings, worker,
                                                                 fake_parse):
    fake_parse[b"A"] = _list()
    list_id = _imp(db, settings, b"A").list_id
    r = client.post("/worker/pricelist-notes", headers=worker, json={
        "text": "اصلاحیه\nA17 128-6 70.000\nA07 128-4 Small pack 48.500\nZ99 128-4 10.000",
        "source_ref": "t.me/AbrishamiiPhoneMashhad/900"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "correction" and body["applied"] == 5 and body["held"] == 0
    assert body["unmatched"] == ["Z99 128-4 10.000"]
    a17 = _rows(db, list_id, "A17 128GB Ram6")
    assert {r["naghd"] for r in a17} == {70000}
    assert all(r["price_flag"] == "correction" for r in a17)
    # the model's learned «روال − نقد» (500) is added; the PDF values are kept
    black = next(r for r in a17 if r["color"] == "Black")
    assert black["raval"] == 70500 and black["price_rial"] == 70500 * 10_000
    assert black["orig_naghd"] == 72000 and not black["raval_estimated"]
    # «Small pack» = the plain A07, not the «(Full)» one
    assert {r["naghd"] for r in _rows(db, list_id, "A07 128GB Ram4")} == {48500}
    assert _rows(db, list_id, "A07 (Full) 128GB Ram4")[0]["naghd"] == 50000
    kinds = events(db)
    assert "pricelist_corrected" in kinds and "price_correction_unmatched" in kinds
    # the next list replaces the correction
    fake_parse[b"B"] = _list("1405/08/01")
    new_id = _imp(db, settings, b"B").list_id
    assert {r["naghd"] for r in _rows(db, new_id, "A17 128GB Ram6")} == {72000, 71500}


def test_correction_without_history_estimates_the_raval(db, settings, fake_parse):
    fake_parse[b"A"] = _list()
    list_id = _imp(db, settings, b"A").list_id
    with db._lock:
        db._conn.execute("DELETE FROM price_raval_diffs")
        db._commit()
    result = notes.apply_correction(db, settings, "اصلاحیه\nA26 128-6 80.000", guard_pct=10,
                                    result=notes.NoteResult(kind="correction"))
    assert len(result.applied) == 1
    row = _rows(db, list_id, "A26 128GB Ram6")[0]
    # same brand, similar price: A17 (500) and A26 (500) -> 500
    assert row["raval"] == 80500 and row["raval_estimated"] == 1


def test_big_correction_of_a_mapped_model_waits_for_approval(client, db, settings, worker,
                                                             fake_parse):
    fake_parse[b"A"] = _list()
    list_id = _imp(db, settings, b"A").list_id
    _map(db, list_id, "A26 128GB Ram6")
    body = client.post("/worker/pricelist-notes", headers=worker, json={
        "text": "اصلاحیه\nA26 128-6 7.900"}).json()        # a typo: -90 %
    assert body["held"] == 1 and body["applied"] == 0
    row = _rows(db, list_id, "A26 128GB Ram6")[0]
    assert row["naghd"] == 79000 and row["pending_naghd"] == 7900
    assert "price_held" in events(db)
    admin = staff(db)
    r = client.post("/admin/pricelists/rows/reject", headers=admin,
                    json={"row_key": row["row_key"]})
    assert r.status_code == 200 and r.json()["pending_price_rial"] is None
    assert r.json()["naghd"] == 79000
    assert client.post("/admin/pricelists/rows/reject", headers=admin,
                       json={"row_key": row["row_key"]}).status_code == 409


def test_held_list_price_is_approved_by_a_manager(client, db, settings, fake_parse):
    fake_parse[b"A"] = _list()
    first = _imp(db, settings, b"A").list_id
    _map(db, first, "A26 128GB Ram6")
    rows = [_row("A26 128GB Ram6", "Black", 95000, 95500)] + BASE[:6] + BASE[7:]
    fake_parse[b"B"] = _list("1405/08/01", rows)
    result = _imp(db, settings, b"B")
    assert result.outcome == "active" and result.held_rows == 1
    row = _rows(db, result.list_id, "A26 128GB Ram6")[0]
    assert row["price_rial"] == 79500 * 10_000 and row["pending_price_rial"] == 95500 * 10_000
    held = client.get("/admin/pricelists/rows", headers=staff(db)).json()["rows"]
    assert any(r["price_flag"] == "held" for r in held)
    r = client.post("/admin/pricelists/rows/approve", headers=staff(db, username="m2"),
                    json={"row_key": row["row_key"]})
    assert r.status_code == 200
    assert r.json()["price_rial"] == 95500 * 10_000 and r.json()["price_flag"] == ""


# ---- «فروش بسته» ----------------------------------------------------------------------------
def test_sales_closed_post_closes_until_the_next_list(client, db, settings, worker, fake_parse):
    settings.sales_windows_enabled = False           # «open» without a time window
    fake_parse[b"A"] = _list()
    _imp(db, settings, b"A")
    assert sales.compute(db, settings).open
    body = client.post("/worker/pricelist-notes", headers=worker,
                       json={"text": "همکاران عزیز فروش موقتاً بسته است"}).json()
    assert body["kind"] == "sales_closed"
    state = sales.compute(db, settings)
    assert not state.open and state.reason == sales.REASON_CHANNEL_CLOSE
    assert "sales_closed_channel" in events(db)
    # the same post again: no second event
    client.post("/worker/pricelist-notes", headers=worker, json={"text": "فروش بسته"})
    assert events(db).count("sales_closed_channel") == 1
    fake_parse[b"B"] = _list("1405/08/01")
    _imp(db, settings, b"B")
    assert sales.compute(db, settings).open


# ---- the newest existing list post -----------------------------------------------------------
def test_deleted_newest_post_brings_back_the_list_before_it(db, settings, fake_parse):
    fake_parse[b"A"] = _list("1405/07/30")
    fake_parse[b"B"] = _list("1405/07/30", BASE[:-1])
    first = _imp(db, settings, b"A", posted_at="2026-10-22T06:00:00+00:00").list_id
    second = _imp(db, settings, b"B", posted_at="2026-10-22T10:00:00+00:00").list_id
    assert PriceListRepo(db).active_list()["id"] == second
    # without «latest» a known file stays a duplicate
    assert _imp(db, settings, b"A").outcome == "duplicate"
    again = _imp(db, settings, b"A", latest=True)
    assert again.outcome == "active" and PriceListRepo(db).active_list()["id"] == first


def test_edited_post_is_newer_by_its_edit_time(db, settings, fake_parse):
    fake_parse[b"A"] = _list()
    fake_parse[b"A2"] = _list(rows=BASE[:-2])
    _imp(db, settings, b"A", posted_at="2026-10-22T06:00:00+00:00")
    edited = _imp(db, settings, b"A2", posted_at="2026-10-22T07:30:00+00:00", latest=True)
    assert edited.outcome == "active"


def test_raval_differences_are_learned_from_every_list(db, settings, fake_parse):
    fake_parse[b"A"] = _list()
    _imp(db, settings, b"A")
    rows = [_row("A17 128GB Ram6", "Black", 72000, 73000)] + BASE[3:]
    fake_parse[b"B"] = _list("1405/08/01", rows)
    _imp(db, settings, b"B")
    with db._lock:
        diffs = {r["model_key"]: r["diff"] for r in db._fetchall("SELECT * FROM price_raval_diffs")}
    assert diffs["samsung|128 a17 ram6"] == 1000


# ---- channels ---------------------------------------------------------------------------------
def test_joined_channels_roles_and_new_channel_alert(client, db, worker):
    found = [{"id": 1, "username": "AbrishamiiPhoneMashhad", "title": "قیمت"},
             {"id": 2, "username": "ProxyMTProto", "title": "proxy"}]
    assert client.post("/worker/telegram/channels", headers=worker,
                       json={"channels": found}).status_code == 200
    roles = client.get("/worker/telegram/roles", headers=worker).json()["channels"]
    assert {r["ref"]: r["role"] for r in roles} == {"AbrishamiiPhoneMashhad": "pricelist",
                                                    "ProxyMTProto": "proxy"}
    assert "telegram_channel_new" not in events(db)        # the first report: no flood
    found.append({"id": 3, "username": "", "title": "Used phones"})
    client.post("/worker/telegram/channels", headers=worker, json={"channels": found})
    assert events(db).count("telegram_channel_new") == 1
    admin = staff(db)
    listed = client.get("/admin/telegram/channels", headers=admin).json()
    assert [c["id"] for c in listed["channels"]][:3] and listed["working_roles"] == [
        "pricelist", "proxy", "price_other"]          # v2.14.0: other price channels
    r = client.put("/admin/telegram/channels/3", headers=admin, json={"role": "pricelist"})
    assert r.status_code == 200
    roles = {r["ref"]: r["role"] for r in
             client.get("/worker/telegram/roles", headers=worker).json()["channels"]}
    assert roles == {"AbrishamiiPhoneMashhad": "", "ProxyMTProto": "proxy", "3": "pricelist"}
    assert client.put("/admin/telegram/channels/3", headers=admin,
                      json={"role": "boss"}).status_code == 422
    assert client.put("/admin/telegram/channels/99", headers=admin,
                      json={"role": "ignore"}).status_code == 404
    # the server's own key («تنظیمات سرور» on the server) may do it too
    from .conftest import h
    assert client.get("/admin/telegram/channels", headers=h("admin")).status_code == 200


def test_worker_state_keeps_the_new_keys(client, worker):
    for key in ("tg_price_version", "tg_price_notes"):
        assert client.put("/worker/state", headers=worker,
                          json={"key": key, "value": "x"}).status_code == 200


# ---- proxy links ------------------------------------------------------------------------------
def test_every_proxy_link_format():
    secret = "2adba7744ab0b1ca88b609561c0334a1"
    web = parse_proxy_link(f"https://t.me/webproxy?server=naap1.cdnflow.store.&secret={secret}")
    assert web is not None and (web.host, web.port) == ("naap1.cdnflow.store", 443)
    assert parse_proxy_link(f"tg://proxy?server=a.b&amp;port=8443&amp;secret={secret}").port == 8443
    b64 = parse_proxy_link("https://t.me/proxy?server=ir-ir.my-pv.info&port=8443"
                           "&secret=EERighJJvXrFGRMCIMjdCQ")
    assert b64 is not None and b64.kind == "plain"


# ---- off-server backup folder -------------------------------------------------------------------
def test_backup_folder_is_tested_by_the_server_account(client, db, tmp_path):
    from .conftest import h

    target = tmp_path / "offsite"
    r = client.post("/admin/server/backup-test", headers=h("admin"),
                    json={"folder": str(target)})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert target.is_dir() and not list(target.iterdir())        # the test file is gone
    assert client.post("/admin/server/backup-test", headers=h("admin"),
                       json={"folder": "relative"}).json()["ok"] is False
    assert client.post("/admin/server/backup-test", headers=h("bot"),
                       json={"folder": str(target)}).status_code in (401, 403)
