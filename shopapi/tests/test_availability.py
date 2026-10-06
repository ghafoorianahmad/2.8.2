"""Availability and product listing behavior against the fake reader."""
from .conftest import h, seed_products


def test_products_hides_out_of_stock_and_zero_price(client, reader):
    seed_products(reader)
    r = client.get("/products", headers=h("bot"))
    assert r.status_code == 200
    items = {p["code"]: p for p in r.json()["items"]}
    # Widget A: stock 10 - open 2 = 8 available (no reservations yet)
    assert 101 in items
    assert items[101]["available_qty"] == 8.0
    # Widget B: stock 0 -> hidden (in_stock default true)
    assert 102 not in items
    # Widget C: price 0 -> not for sale (filtered in reader via unit_price)
    assert 103 not in items


def test_products_in_stock_false_shows_zero_stock(client, reader):
    seed_products(reader)
    r = client.get("/products", params={"in_stock": "false"}, headers=h("bot"))
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()["items"]}
    assert 102 in codes  # zero stock now visible


def test_products_respect_group_filter(client, reader):
    seed_products(reader)
    r = client.get("/products", params={"group": 2, "in_stock": "false"}, headers=h("bot"))
    codes = {p["code"] for p in r.json()["items"]}
    assert codes == {104}  # 103 has price 0 -> not for sale, filtered


def test_products_require_api_key(client, reader):
    seed_products(reader)
    assert client.get("/products").status_code == 401
