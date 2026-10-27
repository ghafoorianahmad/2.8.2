"""v2.11.0: the site's cart -> «درخواست خرید - استعلام قیمت» per line
(``POST /cart-requests``, bot key). The site files are faked - no network."""
from __future__ import annotations

import json

import pytest

from app import site_cart
from app.catalog_models import CatalogModelRepo

from .conftest import h, register_and_approve

CATALOG = {"format": "asr-catalog", "version": 1, "items": [
    {"code": "galaxy-s26-ultra", "name": "Galaxy S26 Ultra", "category": "phone",
     "colors": [{"name": "بنفش کبالت"}, {"name": "سفید"}, {"name": "مشکی"}]},
    {"code": "anker-737", "name": "پاوربانک Anker 737", "category": "accessory", "colors": []},
]}
PRODUCTS_JS = """const CATALOG = { samsung: { name: "Samsung", mark: "s", items: [
  { id: "galaxy-a56", name: "Galaxy A56", tier: "x", colors: ["خاکستری روشن آوسام", "گرافیتی آوسام"],
    spec: { "a": "b" } } ] } };"""
B64 = site_cart.B64URL


def line(code: str, color: int | None, qty: int) -> str:
    return site_cart.model_hash(code) + B64[63 if color is None else color] + B64[qty]


@pytest.fixture
def fake_site(monkeypatch):
    calls = []

    def fetch(url: str) -> str:
        calls.append(url)
        if url.endswith("catalog.json"):
            return json.dumps(CATALOG, ensure_ascii=False)
        return PRODUCTS_JS

    monkeypatch.setattr(site_cart, "fetch_text", fetch)
    return calls


def test_hash_and_decode_match_the_site():
    # the same values site.js cartHash() gives (checked with node)
    assert site_cart.model_hash("iphone-17") == "zn96_"
    assert site_cart.model_hash("galaxy-s26-ultra") == "xYpSm"
    assert site_cart.decode("c_xYpSmCCE6XvoAC") == [
        {"hash": "xYpSm", "color": 2, "qty": 2}, {"hash": "E6Xvo", "color": 0, "qty": 2}]
    for bad in ("c_", "c_short", "x_xYpSmCC", "c_xYpSmCA", "c_" + "xYpSmCC" * 9):
        with pytest.raises(ValueError):
            site_cart.decode(bad)
    assert site_cart.looks_like_cart("c_xYpSmCC") and not site_cart.looks_like_cart("m_iphone-17")


def test_parse_site_reads_catalog_json_and_products_js():
    assert site_cart.parse_site(json.dumps(CATALOG))["galaxy-s26-ultra"]["colors"][2] == "مشکی"
    assert site_cart.parse_site(PRODUCTS_JS)["galaxy-a56"]["colors"] == [
        "خاکستری روشن آوسام", "گرافیتی آوسام"]
    assert site_cart.parse_site("{not json") == {}


def test_cart_becomes_purchase_requests(client, db, fake_site):
    register_and_approve(client)
    code = "c_" + line("galaxy-s26-ultra", 2, 2) + line("anker-737", None, 1) + line("nope-1", 0, 1)
    r = client.post("/cart-requests", json={"platform": "bale", "chat_id": "111", "code": code},
                    headers=h("bot"))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["unknown"] == 1 and not out["repeated"]
    assert [(c["name"], c["color"], c["qty"]) for c in out["created"]] == [
        ("Galaxy S26 Ultra", "مشکی", 2), ("پاوربانک Anker 737", "", 1)]
    requests = client.get("/admin/item-requests", headers=h("admin")).json()
    rows = requests["items"] if isinstance(requests, dict) else requests
    s26 = next(r for r in rows if r["id"] == out["created"][0]["id"])
    assert s26["kind"] == "purchase" and "سبد خرید سایت" in s26["product_name"]
    assert s26["color"] == "مشکی" and s26["qty"] == 2 and s26.get("row_key") in (None, "")
    # the same cart again (a double tap): nothing new
    again = client.post("/cart-requests", json={"platform": "bale", "chat_id": "111",
                                                "code": code}, headers=h("bot")).json()
    assert again["repeated"] and again["created"] == out["created"]


def test_products_js_when_the_site_has_no_catalog_json(client, monkeypatch):
    register_and_approve(client)

    def fetch(url: str) -> str:
        if url.endswith("catalog.json"):
            raise RuntimeError("site answered HTTP 404")
        return PRODUCTS_JS

    monkeypatch.setattr(site_cart, "fetch_text", fetch)
    code = "c_" + line("galaxy-a56", 1, 1)
    out = client.post("/cart-requests", json={"platform": "bale", "chat_id": "111", "code": code},
                      headers=h("bot")).json()
    assert out["created"][0]["color"] == "گرافیتی آوسام"


def test_site_unreachable_uses_known_models_and_maps_one_product(client, db, monkeypatch):
    register_and_approve(client)

    def fetch(url: str) -> str:
        raise RuntimeError("site unreachable")

    monkeypatch.setattr(site_cart, "fetch_text", fetch)
    repo = CatalogModelRepo(db)
    repo.import_models([{"slug": "iphone-17", "name": "iPhone 17", "brand": "Apple"}], "t")
    model = repo.get_by_slug("iphone-17")
    repo.add_item(model["id"], 5012, "iPhone 17 256", "", "t")
    out = client.post("/cart-requests", json={"platform": "bale", "chat_id": "111",
                                              "code": "c_" + line("iphone-17", 1, 1)},
                      headers=h("bot")).json()
    created = out["created"][0]
    assert created["name"] == "iPhone 17" and created["color"] == ""
    request = db.get_item_request(created["id"]) if hasattr(db, "get_item_request") else None
    if request is not None:
        assert request["kala_code"] == 5012


def test_cart_requests_need_the_bot_key_and_a_known_customer(client, fake_site):
    body = {"platform": "bale", "chat_id": "999", "code": "c_" + line("anker-737", None, 1)}
    assert client.post("/cart-requests", json=body, headers=h("site")).status_code == 403
    assert client.post("/cart-requests", json=body, headers=h("bot")).status_code == 404
    body["code"] = "c_bad!"
    assert client.post("/cart-requests", json=body, headers=h("bot")).status_code == 422
