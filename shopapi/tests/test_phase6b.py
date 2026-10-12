"""Phase 6b: site catalog models (REQUIREMENTS §9a) - fuzzy matching, mapping
routes, the nightly check (drift vs. hide + Bale alert) and bot resolution."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app import catalog_models as cm
from app import fuzzy

from .conftest import h
from .test_phase3 import events, staff

SITE = [
    {"slug": "iphone-17-pro", "name": "iPhone 17 Pro", "brand": "Apple"},
    {"slug": "iphone-17-pro-max", "name": "iPhone 17 Pro Max", "brand": "Apple"},
    {"slug": "galaxy-s25-ultra", "name": "Galaxy S25 Ultra", "brand": "Samsung"},
]


def _p(name, price=1000.0, stock=3.0):
    return {"name": name, "group": 1, "stock": stock, "open": 0.0,
            "unit_price": price, "image": None}


@pytest.fixture
def products(reader):
    reader.products = {
        289: _p("آیفون 17 پرو 256 گیگ"),
        290: _p("آيفون ۱۷ پرو ۵۱۲ گيگ"),           # Arabic yeh, Persian digits
        291: _p("آیفون 17 پرو مکس 256 گیگ"),
        292: _p("قاب آیفون 17 پرو"),
        300: _p("گلکسی S25 اولترا 512"),
    }
    return reader.products


@pytest.fixture
def adm(db):
    return staff(db, "admin")


def _import(client, adm):
    r = client.post("/admin/catalog-models/import", json={"models": SITE}, headers=adm)
    assert r.status_code == 200, r.text
    return {m["slug"]: m for m in client.get("/admin/catalog-models", headers=adm).json()["models"]}


def _map(client, adm, model_id, code, label=""):
    r = client.post(f"/admin/catalog-models/{model_id}/items",
                    json={"kala_code": code, "label": label}, headers=adm)
    assert r.status_code == 201, r.text
    return r.json()


def _resolve(client, text):
    r = client.get("/catalog/resolve", params={"text": text}, headers=h("bot"))
    assert r.status_code == 200, r.text
    return r.json()


# ---- fuzzy --------------------------------------------------------------------------
def test_tokens_normalize_scripts_digits_spacing():
    assert fuzzy.tokens("آیفون۱۷ پرو ۲۵۶ گیگ") == fuzzy.tokens("Iphone 17pro 256G")
    assert fuzzy.tokens("آيفون ۱۷") == fuzzy.tokens("ایفون 17")
    assert fuzzy.tokens("نقره‌ای") == fuzzy.tokens("نقرهای")
    assert fuzzy.tokens("Galaxy S24+") == ["galaxy", "s", "24", "plus"]


def test_rank_prefers_the_model_over_other_models_and_accessories(products):
    names = {c: p["name"] for c, p in products.items()}
    ranked = fuzzy.rank("iPhone 17 Pro", names)
    assert {r["code"] for r in ranked[:2]} == {289, 290}
    order = [r["code"] for r in ranked]
    assert order.index(291) > 1 and (292 not in order or order.index(292) > order.index(291))
    assert 300 not in order


@pytest.mark.parametrize("old,new,expected", [
    ("آیفون 17 پرو 256 گیگ", "آیفون 17 پرو 256 گیگ", "ok"),
    ("آیفون 17 پرو 256 گیگ", "آيفون 17 پرو 256 گيگ", "ok"),          # ی/ي only
    ("آیفون 17 پرو 256 گیگ", "آیفون17پرو 256 گیگ", "drifted"),         # spacing
    ("آیفون 17 پرو 256 گیگ", "آیفون 17 پرو 256 گیگ آبی", "drifted"),   # color added
    ("آیفون 17 پرو 256 گیگ", "آیفون 17 پرو 512 گیگ", "missing"),       # other storage
    ("آیفون 17 پرو 256 گیگ", "آیفون 17 پرو مکس 256 گیگ", "missing"),  # other model
    ("آیفون 17 پرو 256 گیگ", "قاب آیفون 17 پرو 256", "missing"),       # accessory
    ("آیفون 17 پرو 256 گیگ", None, "missing"),                         # gone
])
def test_classify_drift_threshold(old, new, expected):
    assert cm.classify(old, new, 0.7)[0] == expected


# ---- mapping routes -------------------------------------------------------------------
def test_import_is_idempotent_and_validates_slugs(client, adm):
    models = _import(client, adm)
    assert set(models) == {m["slug"] for m in SITE}
    assert all(m["status"] == "unmapped" for m in models.values())
    again = client.post("/admin/catalog-models/import", json={"models": SITE}, headers=adm).json()
    assert again == {"added": 0, "updated": 0, "unchanged": 3}
    renamed = [{**SITE[0], "name": "iPhone 17 Pro (2025)"}]
    assert client.post("/admin/catalog-models/import", json={"models": renamed},
                       headers=adm).json()["updated"] == 1
    for bad in ("17-pro", "iPhone-17", "a_b", "x" * 63):
        r = client.post("/admin/catalog-models/import",
                        json={"models": [{"slug": bad, "name": "x"}]}, headers=adm)
        assert r.status_code == 422, bad
    dup = client.post("/admin/catalog-models/import", json={"models": [SITE[0], SITE[0]]},
                      headers=adm)
    assert dup.status_code == 422


def test_permissions(client, db, products):
    viewer, operator = staff(db, "viewer"), staff(db, "operator")
    assert client.get("/admin/catalog-models", headers=viewer).status_code == 200
    for who in (viewer, operator):
        r = client.post("/admin/catalog-models/import", json={"models": SITE}, headers=who)
        assert r.status_code == 403
    assert client.post("/admin/catalog-models/import", json={"models": SITE},
                       headers=h("bot")).status_code in (401, 403)
    assert client.post("/admin/catalog-models/import", json={"models": SITE},
                       headers=staff(db, "super_admin")).status_code == 200


def test_suggestions_and_mapping(client, adm, products):
    models = _import(client, adm)
    pro = models["iphone-17-pro"]
    sug = client.get(f"/admin/catalog-models/{pro['id']}/suggestions", headers=adm).json()
    assert {s["code"] for s in sug[:2]} == {289, 290}
    detail = _map(client, adm, pro["id"], 289, "256GB")
    assert detail["model"]["status"] == "ok"
    assert detail["items"][0]["confirmed_name"] == "آیفون 17 پرو 256 گیگ"
    # own products are not suggested again; mapped elsewhere = "taken_by"
    sug = client.get(f"/admin/catalog-models/{pro['id']}/suggestions", headers=adm).json()
    assert 289 not in {s["code"] for s in sug}
    pm = models["iphone-17-pro-max"]
    sug = client.get(f"/admin/catalog-models/{pm['id']}/suggestions",
                     params={"q": "آیفون 17 پرو"}, headers=adm).json()
    assert {s["code"]: s["taken_by"] for s in sug}.get(289) == "iphone-17-pro"
    # one product -> one model
    r = client.post(f"/admin/catalog-models/{pm['id']}/items", json={"kala_code": 289},
                    headers=adm)
    assert r.status_code == 409
    # unknown / inactive product
    r = client.post(f"/admin/catalog-models/{pm['id']}/items", json={"kala_code": 999},
                    headers=adm)
    assert r.status_code == 422
    # relabel, delete
    item_id = detail["items"][0]["id"]
    r = client.patch(f"/admin/catalog-models/items/{item_id}", json={"label": "۲۵۶ گیگ"},
                     headers=adm)
    assert r.json()["items"][0]["label"] == "۲۵۶ گیگ"
    r = client.delete(f"/admin/catalog-models/items/{item_id}", headers=adm)
    assert r.json()["model"]["status"] == "unmapped"


# ---- nightly check --------------------------------------------------------------------------
class Sender:
    def __init__(self):
        self.texts: list[str] = []

    def __call__(self, text):
        self.texts.append(text)
        return 1


def _check(db, reader, settings, sender):
    return cm.run_check(db, reader, settings, sender=sender)


def test_check_unchanged_and_minor_drift_stay_visible_without_alert(
        client, adm, db, reader, settings, products):
    models = _import(client, adm)
    pro = models["iphone-17-pro"]
    _map(client, adm, pro["id"], 289, "256")
    _map(client, adm, pro["id"], 290, "512")
    sender = Sender()
    summary = _check(db, reader, settings, sender)
    assert summary["drifted"] == summary["missing"] == 0 and not sender.texts
    products[289]["name"] = "آیفون 17 پرو 256 گیگ آبی"      # a color added
    summary = _check(db, reader, settings, sender)
    assert summary["drifted"] == 1 and summary["missing"] == 0
    assert not sender.texts and "model_review" not in events(db)
    detail = client.get(f"/admin/catalog-models/{pro['id']}", headers=adm).json()
    assert detail["model"]["status"] == "ok" and detail["model"]["drifted_count"] == 1
    item = next(i for i in detail["items"] if i["kala_code"] == 289)
    assert item["state"] == "drifted" and item["current_name"].endswith("آبی")
    assert _resolve(client, "m_iphone-17-pro")["status"] == "found"
    # the owner accepts the new name
    detail = client.post(f"/admin/catalog-models/items/{item['id']}/accept", headers=adm).json()
    item = next(i for i in detail["items"] if i["kala_code"] == 289)
    assert item["state"] == "ok" and item["confirmed_name"].endswith("آبی")


@pytest.mark.parametrize("change", ["gone", "inactive", "renamed"])
def test_check_hides_and_alerts_once_when_product_lost(
        client, adm, db, reader, settings, products, change):
    models = _import(client, adm)
    pro = models["iphone-17-pro"]
    _map(client, adm, pro["id"], 289, "256")
    _map(client, adm, pro["id"], 290, "512")
    if change == "gone":
        products[301] = products.pop(289)               # new code after stocktaking
    elif change == "inactive":
        products[289]["active"] = False
        products[301] = _p("آیفون 17 پرو 256 گیگ")
    else:
        products[289]["name"] = "شارژر سامسونگ 25 وات"  # the code was reused
        products[301] = _p("آیفون 17 پرو 256 گیگ")
    sender = Sender()
    summary = _check(db, reader, settings, sender)
    assert summary["missing"] == 1 and summary["newly_hidden"] == ["iphone-17-pro"]
    assert len(sender.texts) == 1 and "iphone-17-pro" in sender.texts[0]
    assert "model_review" in events(db)
    detail = client.get(f"/admin/catalog-models/{pro['id']}", headers=adm).json()
    assert detail["model"]["status"] == "review" and detail["model"]["hidden"]
    lost = next(i for i in detail["items"] if i["kala_code"] == 289)
    assert lost["state"] == "missing"
    assert lost["candidates"][0]["code"] == 301        # same name, new code
    # hidden from customers: never a product of a hidden model
    res = _resolve(client, "m_iphone-17-pro")
    assert res["status"] == "unavailable" and "items" not in res
    # a second night: still hidden, no second alert
    _check(db, reader, settings, sender)
    assert len(sender.texts) == 1
    # confirm is refused while a product is missing ...
    r = client.post(f"/admin/catalog-models/{pro['id']}/confirm", headers=adm)
    assert r.status_code == 409
    if change == "renamed":
        # accepting the renamed item itself is an explicit, per-item decision
        lost_now = client.get(f"/admin/catalog-models/{pro['id']}", headers=adm).json()
        assert next(i for i in lost_now["items"] if i["id"] == lost["id"])["state"] == "missing"
    # the owner picks the candidate, then confirms -> visible again
    client.patch(f"/admin/catalog-models/items/{lost['id']}", json={"kala_code": 301},
                 headers=adm)
    detail = client.post(f"/admin/catalog-models/{pro['id']}/confirm", headers=adm).json()
    assert detail["model"]["status"] == "ok"
    assert {i["kala_code"] for i in detail["items"]} == {301, 290}
    assert _resolve(client, "m_iphone-17-pro")["status"] == "found"


def test_check_changes_nothing_when_accounting_fails(client, adm, db, reader, settings, products):
    models = _import(client, adm)
    _map(client, adm, models["iphone-17-pro"]["id"], 289)
    reader.down = True
    with pytest.raises(RuntimeError):
        _check(db, reader, settings, Sender())
    reader.down = False
    products.clear()                       # an empty read must not hide everything
    with pytest.raises(RuntimeError):
        _check(db, reader, settings, Sender())
    assert client.get("/admin/catalog-models", headers=adm).json()["counts"]["review"] == 0
    reader.down = True
    assert client.post("/admin/catalog-models/check", headers=adm).status_code == 503


def test_check_now_route(client, adm, products):
    models = _import(client, adm)
    _map(client, adm, models["iphone-17-pro"]["id"], 289)
    r = client.post("/admin/catalog-models/check", headers=adm)
    assert r.status_code == 200 and r.json()["checked"] == 1
    last = client.get("/admin/catalog-models", headers=adm).json()["last_check"]
    assert last["checked"] == 1


def test_due_once_a_day_after_the_hour(db, settings):
    settings.model_check_hour = 2
    assert not cm.due(db, settings, datetime(2026, 10, 12, 1, 59))
    assert cm.due(db, settings, datetime(2026, 10, 12, 2, 0))
    db.set_state(cm.LAST_RUN_KEY, "2026-10-12")
    assert not cm.due(db, settings, datetime(2026, 10, 12, 23, 0))
    assert cm.due(db, settings, datetime(2026, 10, 13, 3, 0))
    settings.model_check_hour = -1
    assert not cm.due(db, settings, datetime(2026, 10, 13, 3, 0))


def test_nightly_loop_runs_and_records_the_day(db, reader, settings, monkeypatch):
    settings.model_check_hour = 2
    calls = []
    monkeypatch.setattr(cm, "run_check", lambda *a, **k: calls.append(1) or {})

    async def go():
        task = asyncio.create_task(cm.nightly_loop(
            settings, lambda: db, lambda: reader, poll_seconds=0,
            clock=lambda: datetime(2026, 10, 12, 3, 0)))
        for _ in range(20):
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(go())
    assert calls == [1] and db.get_state(cm.LAST_RUN_KEY) == "2026-10-12"


# ---- bot resolution -----------------------------------------------------------------------------
@pytest.fixture
def mapped(client, adm, products):
    models = _import(client, adm)
    _map(client, adm, models["iphone-17-pro"]["id"], 289, "256 گیگ")
    _map(client, adm, models["iphone-17-pro"]["id"], 290, "512 گیگ")
    _map(client, adm, models["iphone-17-pro-max"]["id"], 291, "256 گیگ")
    return models


@pytest.mark.parametrize("text", [
    "m_iphone-17-pro",
    "/start m_iphone-17-pro",
    "iPhone 17 Pro\nکد مدل: iphone-17-pro",
    "كد مدل: iphone-17-pro",                    # Arabic kaf
    "iphone-17-pro",
    "iPhone 17 Pro\nکد مدل: iphone-17-pr0",     # edited slug -> name line
    "ایفون ۱۷ پرو",
])
def test_resolve_found(client, mapped, text):
    res = _resolve(client, text)
    assert res["status"] == "found", (text, res)
    assert res["model"]["slug"] == "iphone-17-pro"
    assert [i["kala_code"] for i in res["items"]] == [289, 290]
    assert res["items"][0]["label"] == "256 گیگ"


def test_resolve_other_outcomes(client, mapped):
    assert _resolve(client, "17 pro max")["model"]["slug"] == "iphone-17-pro-max"
    res = _resolve(client, "galaxy-s25-ultra")          # imported but not mapped
    assert res["status"] == "unavailable" and "items" not in res
    res = _resolve(client, "m_nokia-3310")
    assert res == {"status": "unknown", "explicit": True}
    assert _resolve(client, "سلام")["status"] == "unknown"
    assert _resolve(client, "سلام")["explicit"] is False
    assert _resolve(client, "iphone")["status"] in ("unknown", "ambiguous")


def test_resolve_ambiguous_with_aliases(client, adm, mapped):
    pro, pm = mapped["iphone-17-pro"], mapped["iphone-17-pro-max"]
    client.patch(f"/admin/catalog-models/{pro['id']}", json={"aliases": "هفده پرو"}, headers=adm)
    client.patch(f"/admin/catalog-models/{pm['id']}", json={"aliases": "هفده پرو"}, headers=adm)
    res = _resolve(client, "هفده پرو")
    assert res["status"] == "ambiguous"
    assert {o["slug"] for o in res["options"]} == {"iphone-17-pro", "iphone-17-pro-max"}


def test_resolve_requires_a_key(client, mapped):
    assert client.get("/catalog/resolve", params={"text": "x"}).status_code == 401


def test_site_aliases_are_imported_merged_and_used(client, adm, products):
    products[400] = _p("ردمی 14C 128 گیگ")
    site = [{"slug": "redmi-14c", "name": "Redmi 14C", "brand": "Xiaomi",
             "aliases": ["ردمی ۱۴ سی", "redmi14c"]}]
    client.post("/admin/catalog-models/import", json={"models": site}, headers=adm)
    model = client.get("/admin/catalog-models", headers=adm).json()["models"][0]
    client.patch(f"/admin/catalog-models/{model['id']}", json={"aliases": model["aliases"] + "، شیائومی ۱۴ سی"},
                 headers=adm)
    site[0]["aliases"].append("ردمی ۱۴ سي")          # same alias, Arabic yeh: not added twice
    client.post("/admin/catalog-models/import", json={"models": site}, headers=adm)
    model = client.get(f"/admin/catalog-models/{model['id']}", headers=adm).json()["model"]
    assert model["aliases"].splitlines() == ["ردمی ۱۴ سی", "redmi14c", "شیائومی ۱۴ سی"]
    sug = client.get(f"/admin/catalog-models/{model['id']}/suggestions", headers=adm).json()
    assert sug[0]["code"] == 400
    _map(client, adm, model["id"], 400)
    assert _resolve(client, "ردمی ۱۴ سی")["model"]["slug"] == "redmi-14c"


@pytest.mark.parametrize("text,slug", [
    ("آیفون ۱۷ پرو ۲۵۶ گیگ", "iphone-17-pro"),
    ("iphone 17 pro max 1TB silver", "iphone-17-pro-max"),
    ("آیفون 17 پرو نقره ای", "iphone-17-pro"),
])
def test_resolve_ignores_storage_and_color_in_customer_text(client, mapped, text, slug):
    res = _resolve(client, text)
    assert res["status"] == "found" and res["model"]["slug"] == slug, res


def test_model_letters_are_identity():
    assert fuzzy.similarity("iPhone 17", "iPhone 17e") < 0.5
    assert fuzzy.similarity("آیفون ۱۷ ای", "iPhone 17e") == 1.0
    assert fuzzy.tokens("نقره ای")[-1] == "ای"            # a color word, not «e»
    assert fuzzy.similarity("Redmi 14C", "ردمی ۱۴ سی") == 1.0
