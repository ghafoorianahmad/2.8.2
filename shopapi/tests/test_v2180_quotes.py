"""v2.18.0: search by the customer's words, automatic mapping only at 95%, automatic quotes."""
from __future__ import annotations

import pytest

from app import auto_quote, phone_search, product_aliases
from app.pricelist.matching import confident, name_candidates, specs_differ

from .conftest import h
from .test_v2170 import staff


def _row(key, section, description, color, price=1000, **fields):
    return {"row_key": key, "section": section, "description": description, "color": color,
            "kind": "", "price_rial": price, "action": None, "kala_code": None, **fields}


ROWS = [
    _row("a", "iPHONE", "17 Promax 256 ZAA", "Black"),
    _row("b", "iPHONE", "17 Promax 256 ZAA", "White"),
    _row("c", "iPHONE", "17 Promax 512 ZAA", "Black"),
    _row("d", "iPHONE", "17 Pro 256 ZAA", "Black"),
    _row("e", "SAMSUNG", "A55 256GB Ram8", "Navy"),
    _row("f", "SAMSUNG", "A55 256GB Ram12", "Navy"),
]


def _keys(text):
    return [r["row_key"] for r in phone_search.search(ROWS, text)]


@pytest.mark.parametrize("text", ["ایفون17پرومکس256 مشکی", "آیفون ۱۷ پرو مکس ۲۵۶ مشکی",
                                  "ايفون١٧پرومكس٢٥٦ مشكي", "iphone 17 pro max 256 black"])
def test_a_certain_match_is_one_row(text):
    assert _keys(text) == ["a"]


def test_a_missing_color_asks():
    assert _keys("آیفون 17 پرومکس 256") == ["a", "b"]


def test_pro_is_never_pro_max():
    assert _keys("آیفون 17 پرو 256") == ["d"]


def test_ram_decides_between_two_rows():
    assert _keys("سامسونگ a55 256 رم 12") == ["f"]
    assert set(_keys("سامسونگ a55 256")) == {"e", "f"}


def test_a_storage_the_list_does_not_have_shows_the_model_and_asks():
    assert set(_keys("آیفون 17 پرو مکس 1 ترابایت")) == {"a", "b", "c"}


def test_what_staff_taught_is_understood(db):
    product_aliases.learn(db, "طلایی محسن", "iPhone 17 Pro Max", "boss")
    learned = product_aliases.load_learned(db)
    assert {r["row_key"] for r in phone_search.search(ROWS, "طلایی محسن", learned)} == {"a", "b", "c"}


# ---- automatic mapping ---------------------------------------------------------------------
def _map_row(**fields):
    return {"section": "SAMSUNG", "description": "A55 256GB Ram8", "kind": "", "color": "Black",
            **fields}


@pytest.mark.parametrize("name,differs", [
    ("Samsung A55 256GB Ram8 Black", False),
    ("Samsung A56 256GB Ram8 Black", True),        # model number
    ("Samsung A55 128GB Ram8 Black", True),        # storage
    ("Samsung A55 256GB Ram12 Black", True),       # RAM
    ("Samsung A55 256GB Ram8 Blue", True),         # color
    ("Samsung A55 256GB", False),                  # a spec only the row states is no difference
])
def test_specs(name, differs):
    assert specs_differ(_map_row(), name) is differs


def test_below_95_percent_is_only_a_suggestion():
    assert confident([{"code": 1, "name": "x", "score": 0.94}]) is None
    assert confident([{"code": 1, "name": "x", "score": 0.95}])["code"] == 1


def test_never_on_a_different_storage_however_close(db):
    from app.pricelist.matching import name_match
    from app.pricelist.repo import PriceListRepo

    class Repo(PriceListRepo):
        def rows(self, _list_id):
            return [{**_map_row(), "row_key": "k", "action": None}]

    repo = Repo(db)
    assert name_match(repo, 1, {7: "Samsung A55 128GB Ram8 Black"}) == 0
    assert repo.list_mappings() == []
    assert name_match(repo, 1, {7: "Samsung A55 256GB Ram8 Black"}) == 1


def test_candidates_are_still_offered_to_staff():
    found = name_candidates(_map_row(), {7: "Samsung A55 256GB Ram8 Black"})
    assert found and found[0]["code"] == 7


# ---- the switch, the report ----------------------------------------------------------------
def test_the_switch_and_the_report(client, db):
    boss = staff(db, "super_admin", "boss")
    rules = client.get("/admin/shop-rules", headers=boss).json()
    assert rules["auto_quote"] == {"enabled": True, "report": []}
    r = client.put("/admin/shop-rules/auto-quote", json={"enabled": False}, headers=boss)
    assert r.json()["enabled"] is False and not auto_quote.enabled(db)
    auto_quote.record(db, "bale", "1", "ایفون", {"row_key": "a", "description": "17 Promax 256",
                                                 "color": "Black", "price_rial": 5}, 1)
    report = client.get("/admin/shop-rules", headers=boss).json()["auto_quote"]["report"]
    assert report[0]["query"] == "ایفون" and report[0]["price_rial"] == 5
    assert "chat_id" not in report[0]


def test_ticks(client, db):
    mina = staff(db, "operator", "mina")
    assert client.put("/admin/shop-rules/auto-quote", json={"enabled": False},
                      headers=mina).status_code == 403
    assert client.post("/admin/product-aliases", json={"text": "اسم", "model": "iPhone 17"},
                       headers=mina).status_code == 403
    assert client.post("/auto-quotes", headers=h("site"), json={
        "platform": "bale", "chat_id": "1", "row_key": "x"}).status_code == 403


def test_teaching_through_the_api(client, db):
    boss = staff(db, "super_admin", "boss")
    models = client.get("/admin/product-aliases/models", headers=boss).json()
    assert "iPhone 17 Pro Max" in models
    assert client.post("/admin/product-aliases", headers=boss,
                       json={"text": "نام تازه", "model": "نه مدل"}).status_code == 422
    r = client.post("/admin/product-aliases", headers=boss,
                    json={"text": "نام تازه", "model": "iPhone 17 Pro Max"})
    assert r.status_code == 200 and r.json()["alias"] == "نام تازه"
