from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import secure_store
from fakes import fake_message, pool_entry

PDF = b"%PDF-1.4 fake price list"


def run(coro):
    return asyncio.run(coro)


# ---- connection / failover ----------------------------------------------------------
def test_connects_through_best_pool_proxy_and_reports(env):
    worker, tg, shop, _ = env
    shop.pool = [pool_entry(1, "a.example"), pool_entry(2, "b.example")]
    assert run(worker.ensure_connected())
    assert worker.tg.proxy.id == 1
    assert shop.reports == [{"id": 1, "ok": True, "latency_ms": 0}]
    assert shop.keys_seen == {"worker-key"}


def test_dead_proxy_is_skipped_and_reported(env):
    worker, tg, shop, _ = env
    shop.pool = [pool_entry(1, "a.example"), pool_entry(2, "b.example")]
    tg.dead_proxies.add(("a.example", 443))
    assert run(worker.ensure_connected())
    assert worker.tg.proxy.id == 2
    assert [r["ok"] for r in shop.reports] == [False, True]


def test_local_tg_proxy_is_the_fallback(env, settings):
    worker, tg, shop, _ = env
    shop.down = True                       # no pool at all
    settings.local_proxies = [f"tg://proxy?server=local.example&port=443&secret=dd{'ab' * 16}"]
    assert run(worker.ensure_connected())
    assert worker.tg.proxy.host == "local.example" and worker.tg.proxy.id is None


def test_direct_connection_is_the_last_resort(env, settings):
    worker, tg, shop, _ = env
    shop.pool = [pool_entry(1, "a.example")]
    tg.dead_proxies.add(("a.example", 443))
    assert run(worker.ensure_connected())
    assert worker.tg.proxy is None
    assert tg.calls[-1] == "connect:direct:True"
    assert shop.reports == [{"id": 1, "ok": False}]     # direct is not a pool entry
    run(worker.tg.disconnect())
    settings.allow_direct = False
    assert not run(worker.ensure_connected())


def test_health_failure_switches_to_next_proxy(env):
    worker, tg, shop, _ = env
    shop.pool = [pool_entry(1, "a.example"), pool_entry(2, "b.example")]
    run(worker.ensure_connected())
    tg.dead_proxies.add(("a.example", 443))
    tg.ping_fails = True
    shop.reports.clear()

    async def scenario():
        # the ping on the old connection fails; reconnect succeeds via b
        orig = worker.tg.connect

        async def connect(session, link):
            tg.ping_fails = False
            return await orig(session, link)
        worker.tg.connect = connect
        await worker.health_tick()
    run(scenario())
    assert worker.tg.proxy.id == 2
    assert shop.reports[0] == {"id": 1, "ok": False}
    assert shop.reports[-1]["id"] == 2 and shop.reports[-1]["ok"]


def test_healthy_ping_reports_ok(env):
    worker, tg, shop, _ = env
    shop.pool = [pool_entry(7, "a.example")]
    run(worker.ensure_connected())
    shop.reports.clear()
    run(worker.health_tick())
    assert shop.reports == [{"id": 7, "ok": True, "latency_ms": 0}]
    assert "GetNearestDcRequest" in tg.calls


def test_unreachable_alert_only_after_the_grace_period(env, settings):
    worker, tg, shop, clock = env
    shop.pool = [pool_entry(1, "a.example")]
    tg.dead_proxies.add(("a.example", 443))
    tg.direct_ok = False
    assert not run(worker.ensure_connected())
    assert shop.alerts == []
    clock.t += settings.unreachable_alert_sec
    assert not run(worker.ensure_connected())
    assert shop.alerts == ["telegram_unreachable"]


def test_missing_session_raises_login_alert(env):
    worker, tg, shop, _ = env

    def missing():
        raise secure_store.SecureStoreError("no Telegram session yet")
    worker._load_session = missing
    assert not run(worker.ensure_connected())
    assert shop.alerts == ["telegram_login_required"]
    assert tg.clients == []


def test_revoked_session_raises_login_alert(env):
    worker, tg, shop, _ = env
    shop.pool = [pool_entry(1, "a.example")]
    tg.authorized = False
    assert not run(worker.ensure_connected())
    assert shop.alerts == ["telegram_login_required"]
    assert not worker.tg.connected


def test_probe_uses_anonymous_clients_and_rotates(env, settings):
    worker, tg, shop, _ = env
    settings.probe_max = 2
    shop.pool = [pool_entry(i, f"p{i}.example", state="probation") for i in range(1, 5)]
    run(worker.ensure_connected())          # connected via p1
    tg.dead_proxies.add(("p3.example", 443))
    shop.reports.clear()
    run(worker.probe_tick())
    assert [(r["id"], r["ok"]) for r in shop.reports] == [(2, True), (3, False)]
    shop.reports.clear()
    run(worker.probe_tick())
    assert [r["id"] for r in shop.reports] == [4, 2]
    probes = [c for c in tg.clients[1:]]
    assert probes and all(c.session_str == "" for c in probes)


# ---- price channel ----------------------------------------------------------------------
def _channel(tg, msgs):
    tg.channels["AbrishamiiPhoneMashhad"] = msgs


def test_first_run_sends_only_the_newest_pdf(env):
    worker, tg, shop, _ = env
    _channel(tg, [fake_message(10, pdf=PDF), fake_message(11, image=True),
                  fake_message(12, pdf=PDF + b"2"), fake_message(13, text="hello")])
    run(worker.ensure_connected())
    assert run(worker.price_tick()) == 1
    assert len(shop.pricelists) == 1
    sent = shop.pricelists[0]
    assert sent["source_ref"] == "t.me/AbrishamiiPhoneMashhad/12"
    assert sent["posted_at"].startswith("2026-10-12T08:12")
    assert shop.state["tg_price_last_id"] == "13"      # past the text post too


def test_later_runs_send_every_new_pdf_in_order(env):
    worker, tg, shop, _ = env
    shop.state["tg_price_last_id"] = "12"
    _channel(tg, [fake_message(12, pdf=PDF), fake_message(14, pdf=PDF + b"a"),
                  fake_message(15, image=True), fake_message(16, pdf=PDF + b"b")])
    run(worker.ensure_connected())
    assert run(worker.price_tick()) == 2
    assert [p["source_ref"].rsplit("/", 1)[1] for p in shop.pricelists] == ["14", "16"]
    assert shop.state["tg_price_last_id"] == "16"
    assert "iter:AbrishamiiPhoneMashhad:12:100" in tg.calls
    # nothing new -> nothing sent, no download
    tg.calls.clear()
    assert run(worker.price_tick()) == 0
    assert not [c for c in tg.calls if c.startswith("download")]


def test_shopapi_down_keeps_the_cursor(env):
    worker, tg, shop, _ = env
    shop.state["tg_price_last_id"] = "1"
    _channel(tg, [fake_message(5, pdf=PDF)])
    run(worker.ensure_connected())

    async def scenario():
        orig = worker.api.post_pricelist

        async def failing(*a, **k):
            shop.down = True
            try:
                return await orig(*a, **k)
            finally:
                shop.down = False
        worker.api.post_pricelist = failing
        return await worker.price_tick()
    assert run(scenario()) == 0
    assert shop.state["tg_price_last_id"] == "1"


def test_oversized_and_fake_pdfs_are_skipped(env, settings):
    worker, tg, shop, _ = env
    settings.pdf_max_bytes = 50
    shop.state["tg_price_last_id"] = "1"
    _channel(tg, [fake_message(2, pdf=b"%PDF" + b"x" * 100), fake_message(3, pdf=b"MZ not a pdf")])
    run(worker.ensure_connected())
    run(worker.price_tick())
    assert shop.pricelists == []
    assert shop.state["tg_price_last_id"] == "3"


# ---- proxy channels ----------------------------------------------------------------------
LINK1 = f"tg://proxy?server=one.example&port=443&secret=dd{'ab' * 16}"
LINK2 = f"https://t.me/proxy?server=two.example&port=8443&secret={'cd' * 16}"


def test_weekly_collection_sends_links_from_text_entities_and_buttons(env):
    worker, tg, shop, _ = env
    tg.channels["ProxyChan"] = [
        fake_message(5, text=f"fast proxy {LINK1} enjoy"),
        fake_message(6, text="connect", urls=[LINK2]),
        fake_message(7, text="x", button_urls=[LINK1, "https://example.com"]),
        fake_message(8, text="tg://proxy?server=bad&port=x&secret=zz"),
    ]
    run(worker.ensure_connected())
    assert run(worker.collect_tick()) == 2
    assert shop.candidates == [{"links": [LINK1, LINK2], "source": "channel:ProxyChan"}]
    assert json.loads(shop.state["tg_proxy_last_ids"]) == {"ProxyChan": 8}
    # not due again for a week
    assert run(worker.collect_tick()) == 0
    assert len(shop.candidates) == 1


def test_collection_due_after_the_interval(env, settings):
    worker, _, _, _ = env
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    worker._now = lambda: now
    assert worker.collect_due("")
    assert not worker.collect_due((now - timedelta(days=6)).isoformat())
    assert worker.collect_due((now - timedelta(days=7)).isoformat())
    settings.proxy_channels = []
    assert not worker.collect_due("")


# ---- loop ---------------------------------------------------------------------------------
def test_step_runs_due_jobs_and_publishes_status(env):
    worker, tg, shop, clock = env
    shop.pool = [pool_entry(1, "a.example")]
    _channel(tg, [fake_message(3, pdf=PDF)])
    run(worker.step())
    assert len(shop.pricelists) == 1
    status = json.loads(shop.state["tg_status"])
    assert status["connected"] and status["proxy"] == "a.example:443 (dd)"
    assert "secret" not in shop.state["tg_status"]
    # 10 minutes later: health is due again, price is not
    clock.t += 600
    run(worker.step())
    assert len(shop.pricelists) == 1


def test_step_while_down_retries_within_a_minute(env):
    worker, tg, shop, clock = env
    shop.pool = [pool_entry(1, "a.example")]
    tg.dead_proxies.add(("a.example", 443))
    tg.direct_ok = False
    run(worker.step())
    assert worker._next["health"] <= clock.t + 60
    assert json.loads(shop.state["tg_status"])["connected"] is False


def test_run_stops_on_event(env):
    worker, tg, shop, _ = env
    shop.pool = [pool_entry(1, "a.example")]

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run(stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, 2)
    run(scenario())
    assert not worker.tg.connected
