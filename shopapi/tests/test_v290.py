"""v2.9.0: the Telegram reader fills the proxy pool with tested links only, the pool
status on «سرور فروشگاه», and the new price-list download alert."""
from __future__ import annotations

import json

import pytest

from app import monitor
from app.proxypool import ACTIVE_CAP, ProxyPool, parse_proxy_link

from .test_phase3 import events, staff
from .test_staff_auth import bearer, owner_token

SECRET = "dd" + "0123456789abcdef0123456789abcdef"


def link(i: int) -> str:
    return f"tg://proxy?server=10.0.{i // 250}.{i % 250 + 1}&port=443&secret={SECRET}"


@pytest.fixture
def worker(settings):
    settings.worker_api_key = "worker-key"
    return {"X-API-Key": "worker-key"}


def test_unknown_lists_only_links_never_seen(client, db, worker):
    ProxyPool(db).add(parse_proxy_link(link(1)), "manual")
    r = client.post("/worker/proxies/unknown", headers=worker,
                    json={"links": [link(1), link(2), link(2), "junk"]})
    assert r.json() == {"unknown": [link(2)]}
    assert client.post("/worker/proxies/unknown", headers={"X-API-Key": "nope"},
                       json={"links": []}).status_code in (401, 403)


def test_tested_links_join_the_pool_and_failed_ones_are_remembered(client, db, worker):
    r = client.post("/worker/proxies/candidates", headers=worker, json={
        "source": "channel:ProxyMTProto",
        "tested": [{"link": link(3), "latency_ms": 420}],
        "failed": [link(4)]})
    assert r.json() == {"added": 1, "invalid": 0, "skipped": 0}
    ranked = client.get("/worker/proxies", headers=worker).json()
    assert [p["host"] for p in ranked] == ["10.0.0.4"]
    assert ranked[0]["last_latency_ms"] == 420 and ranked[0]["last_ok_at"]
    assert ranked[0]["state"] == "probation"
    every = {p["host"]: p["state"] for p in ProxyPool(db).list_all()}
    assert every["10.0.0.5"] == "retired"                 # never tested again:
    assert client.post("/worker/proxies/unknown", headers=worker,
                       json={"links": [link(3), link(4)]}).json() == {"unknown": []}


def test_pool_never_grows_beyond_the_cap(client, db, worker):
    pool = ProxyPool(db)
    for i in range(ACTIVE_CAP):
        pool.add(parse_proxy_link(link(100 + i)), "channel:x")
    r = client.post("/worker/proxies/candidates", headers=worker, json={
        "tested": [{"link": link(1), "latency_ms": 10}]})
    assert r.json()["skipped"] == 1
    assert pool.active_count() == ACTIVE_CAP


def test_pricelist_download_alert_once_and_only_for_server_staff(client, db, worker):
    body = {"kind": "telegram_pricelist_error"}
    assert client.post("/worker/alerts", json=body, headers=worker).json() == {"sent": True}
    assert client.post("/worker/alerts", json=body, headers=worker).json() == {"sent": False}
    assert events(db).count("telegram_pricelist_error") == 1
    from app import ownership
    from app.security import Identity

    seller = Identity(kind="staff", role="operator", username="s", user_id=99,
                      permissions=frozenset())
    event = {"kind": "telegram_pricelist_error", "ref_id": None}
    assert not ownership.event_visible(db, seller, event)


def test_server_status_shows_the_pool_and_reader_without_secrets(client, db, worker):
    owner = owner_token(client)
    pool = ProxyPool(db)
    good, _ = pool.add(parse_proxy_link(link(1)), "manual", state="main")
    pool.record(good["id"], True, 300)
    pool.add(parse_proxy_link(link(2)), "channel:ProxyMTProto")
    pool.add(parse_proxy_link(link(3)), "channel:ProxyMTProto", state="retired")
    db.set_state(monitor.TG_STATUS_KEY, json.dumps({
        "connected": True, "proxy": "10.0.0.2:443 (dd)", "login_required": False,
        "at": "2026-10-21T08:00:00+00:00", "api_preset": "tdesktop",
        "price_channel": "AbrishamiiPhoneMashhad", "pool_size": 5,
        "price": {"checked_at": "2026-10-21T08:00:00", "ref": "t.me/x/5", "outcome": "active",
                  "session": "MUST-NOT-LEAK"},
        "collect": {"at": "2026-10-21T07:00:00", "found": 30, "tested": 12, "added": 4,
                    "via": "account"},
        "secret_thing": "MUST-NOT-LEAK"}), "worker")
    body = client.get("/admin/server/status", headers=bearer(owner)).json()
    assert body["proxy_pool"] == {
        "target": 5, "working": 1, "active": 2, "main": 1, "probation": 1, "manual": 1,
        "retired": 1, "disabled": 0, "all_failing": False}
    tg = body["telegram_worker"]
    assert tg["api_preset"] == "tdesktop" and tg["price"]["ref"] == "t.me/x/5"
    assert tg["collect"]["added"] == 4
    text = json.dumps(body)
    assert "MUST-NOT-LEAK" not in text and SECRET not in text


def test_seller_cannot_see_the_proxy_pool(client, db):
    assert client.get("/admin/proxies", headers=staff(db, "operator")).status_code == 403
