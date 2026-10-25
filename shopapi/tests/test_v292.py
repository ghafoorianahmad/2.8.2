"""v2.9.2: a price held by the price guard is never sold at the old price (only
«درخواست خرید - استعلام قیمت»); staff offer a price and the customer answers in
the bot («تأیید و خرید» -> order, «نمی‌خواهم» -> closed); «جمع‌آوری اکنون»."""
from __future__ import annotations

from app.pricelist import notes
from app.pricelist.repo import PriceListRepo

from .conftest import h
from .test_phase3 import staff
from .test_v260 import events
from .test_v280 import A55, PRO, _list, _map, _request, _shop  # noqa: F401 - fixtures
from .test_v280 import shop  # noqa: F401 - fixture


def _hold(db, row_key: str, new_price: int) -> int:
    repo = PriceListRepo(db)
    active = repo.active_list()
    row = repo.rows_by_key(active["id"])[row_key]
    notes.hold_row_price(db, active["id"], row, new_price // 10_000, None, new_price,
                         source="list")
    return int(active["id"])


# ---- price guard: never the old price -------------------------------------------------------
def test_held_price_is_not_sold_and_only_requested(shop, db):
    variant = _map(db, "i17p-zaa-silver", PRO)
    _hold(db, "i17p-zaa-silver", 12_000_000_000)         # an extra zero
    product = shop.get(f"/products/{PRO}", headers=h("bot")).json()
    color = next(v for v in product["variants"] if v["id"] == variant)
    assert color["unit_price"] is None and not color["available"] and color["price_held"]
    r = shop.post("/orders", json={"platform": "bale", "chat_id": "111", "items": [
        {"kala_code": PRO, "qty": 1, "variant_id": variant}]}, headers=h("bot"))
    assert r.status_code == 422 and "price waits for approval" in r.json()["detail"]
    found = shop.get("/phones/search", params={"q": "آیفون ۱۷ پرو"}, headers=h("bot")).json()
    row = next(i for i in found["items"] if i["row_key"] == "i17p-zaa-silver")
    assert row["price"] is None and row["action"] == "purchase" and row["price_held"]
    req = _request(shop, kala_code=PRO, variant_id=variant)
    assert req["price_rial"] is None and req["kind"] == "purchase"


def test_approved_price_is_sold_at_the_new_price(shop, db):
    variant = _map(db, "i17p-zaa-silver", PRO)
    list_id = _hold(db, "i17p-zaa-silver", 1_320_000_000)
    boss = staff(db, "super_admin", "boss")
    r = shop.post("/admin/pricelists/rows/approve",
                  json={"list_id": list_id, "row_key": "i17p-zaa-silver"}, headers=boss)
    assert r.status_code == 200
    product = shop.get(f"/products/{PRO}", headers=h("bot")).json()
    color = next(v for v in product["variants"] if v["id"] == variant)
    assert color["unit_price"] == 1_320_000_000 and color["available"]
    assert not color["price_held"]


# ---- offer -> the customer's answer --------------------------------------------------------
def test_offer_needs_a_price_while_the_list_price_is_held(shop, db):
    variant = _map(db, "i17p-zaa-silver", PRO)
    _hold(db, "i17p-zaa-silver", 12_000_000_000)
    req = _request(shop, kala_code=PRO, variant_id=variant)
    mina = staff(db, "operator", "mina")
    url = f"/admin/item-requests/{req['id']}/offer"
    r = shop.post(url, json={}, headers=mina)
    assert r.status_code == 422 and "price" in r.json()["detail"].lower()
    offered = shop.post(url, json={"price_rial": 1_210_000_000}, headers=mina).json()
    assert offered["outcome"] == "offered" and offered["offer_price_rial"] == 1_210_000_000
    messages = shop.get(f"/admin/item-requests/{req['id']}/messages", headers=mina).json()
    assert messages[-1]["purpose"] == "offer" and "1,210,000,000" in messages[-1]["text"]
    delivery = shop.get(f"/admin/item-request-messages/{messages[-1]['id']}",
                        headers=h("admin")).json()
    assert delivery["purpose"] == "offer" and delivery["offer_price_rial"] == 1_210_000_000
    assert delivery["chat_id"] == "111" and delivery["color"] == "Silver"
    # staff may not answer for the customer
    assert shop.post(f"/admin/item-requests/{req['id']}/customer-answer",
                     json={"accept": True}, headers=mina).status_code == 403
    answer = shop.post(f"/admin/item-requests/{req['id']}/customer-answer",
                       json={"accept": True}, headers=h("admin")).json()
    assert answer["order"]["total"] == 1_210_000_000
    assert answer["order"]["items"][0]["unit_price"] == 1_210_000_000
    # the history shows every step
    actions = [e["action"] for e in shop.get(f"/admin/item-requests/{req['id']}/timeline",
                                             headers=mina).json()]
    assert "price_offer" in actions and "offer_accept" in actions
    # answered once only
    again = shop.post(f"/admin/item-requests/{req['id']}/customer-answer",
                      json={"accept": True}, headers=h("admin"))
    assert again.status_code == 409


def test_offer_list_price_and_decline(shop, db):
    req = _request(shop, row_key="i17p-cha-silver")
    mina = staff(db, "operator", "mina")
    offered = shop.post(f"/admin/item-requests/{req['id']}/confirm-stock",
                        json={"kala_code": PRO}, headers=mina).json()
    assert offered["offer_price_rial"] == 1_150_000_000          # the list price
    answer = shop.post(f"/admin/item-requests/{req['id']}/customer-answer",
                       json={"accept": False}, headers=h("admin")).json()
    assert answer["order"] is None
    assert answer["request"]["status"] == "done" and answer["request"]["outcome"] == "declined"
    assert "purchase_offer_declined" in events(db)
    assert db.list_orders() == []


def test_offer_for_a_price_inquiry(shop, db, reader):
    reader.products[700] = {"name": "قاب ویژه", "group": 1, "stock": 3.0, "open": 0.0,
                            "unit_price": 0.0, "image": None}
    user = db.get_user_by_platform("bale", "111") if hasattr(db, "get_user_by_platform") \
        else None
    user_id = int(user["id"]) if user else 1
    created = db.add_item_request(user_id, 700, "قاب ویژه", "", "inquiry")
    boss = staff(db, "super_admin", "boss")
    offered = shop.post(f"/admin/item-requests/{created['id']}/offer",
                        json={"price_rial": 5_000_000}, headers=boss).json()
    assert offered["outcome"] == "offered"
    answer = shop.post(f"/admin/item-requests/{created['id']}/customer-answer",
                       json={"accept": True}, headers=h("admin")).json()
    assert answer["order"]["total"] == 5_000_000
    assert answer["order"]["items"][0]["kala_code"] == 700


# ---- «جمع‌آوری اکنون» and the last collection after a restart ------------------------------
def test_collect_now_request_and_stored_collection(client, db, settings):
    import json

    settings.worker_api_key = "worker-key"
    boss = staff(db, "super_admin", "boss")
    assert client.post("/admin/proxies/collect", headers=staff(db, "operator", "op")) \
        .status_code == 403
    asked = client.post("/admin/proxies/collect", headers=boss).json()["requested_at"]
    worker = {"X-API-Key": "worker-key"}
    state = client.get("/worker/state", headers=worker).json()
    assert state["tg_collect_request"] == asked
    # the reader restarted: its status has no collection yet, the stored one is shown
    client.put("/worker/state", headers=worker, json={
        "key": "tg_status", "value": json.dumps({"connected": True, "collect": {}})})
    client.put("/worker/state", headers=worker, json={
        "key": "tg_collect_info", "value": json.dumps({"at": "2026-10-25T09:58:48+00:00",
                                                       "found": 54, "tested": 9, "added": 4,
                                                       "via": "account", "error": ""})})
    status = client.get("/admin/server/status", headers=boss).json()
    collect = status["telegram_worker"]["collect"]
    assert collect["found"] == 54 and collect["added"] == 4 and collect["requested"]
    client.put("/worker/state", headers=worker, json={"key": "tg_collect_done", "value": asked})
    status = client.get("/admin/server/status", headers=boss).json()
    assert not status["telegram_worker"]["collect"]["requested"]
