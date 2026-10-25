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
    assert sent["latest"] is True
    assert shop.state["tg_price_last_id"] == "12"
    # v2.9.1: the text post after the list goes to shopapi (a correction / «فروش بسته»?)
    assert [n["source_ref"] for n in shop.notes] == ["t.me/AbrishamiiPhoneMashhad/13"]


def test_newest_list_only_and_again_when_edited_or_deleted(env):
    """v2.9.1: always the newest list post that exists; an edit (new file in the
    same post) or a deleted newest post sends the list again."""
    worker, tg, shop, _ = env
    msgs = [fake_message(12, pdf=PDF), fake_message(14, pdf=PDF + b"a"),
            fake_message(15, image=True), fake_message(16, pdf=PDF + b"b")]
    _channel(tg, msgs)
    run(worker.ensure_connected())
    assert run(worker.price_tick()) == 1
    assert [p["source_ref"].rsplit("/", 1)[1] for p in shop.pricelists] == ["16"]
    assert "iter:AbrishamiiPhoneMashhad:0:30" in tg.calls
    # nothing changed -> nothing sent, no download
    tg.calls.clear()
    assert run(worker.price_tick()) == 0
    assert not [c for c in tg.calls if c.startswith("download")]
    # the post is edited: a new file in the same post
    edited = fake_message(16, pdf=PDF + b"c", edit_date=datetime(2026, 10, 12, 9, 30,
                                                                 tzinfo=timezone.utc))
    _channel(tg, msgs[:3] + [edited])
    assert run(worker.price_tick()) == 1
    assert shop.pricelists[-1]["posted_at"].startswith("2026-10-12T09:30")
    # the newest post is deleted: the one before it is the list again
    _channel(tg, msgs[:3])
    assert run(worker.price_tick()) == 1
    assert shop.pricelists[-1]["source_ref"].endswith("/14")


def test_text_posts_after_the_list_are_sent_once_per_version(env):
    worker, tg, shop, _ = env
    msgs = [fake_message(9, text="old note"), fake_message(10, pdf=PDF),
            fake_message(11, text="اصلاحیه\nA17 128-6 72.000")]
    _channel(tg, msgs)
    run(worker.ensure_connected())
    run(worker.price_tick())
    assert [n["text"] for n in shop.notes] == ["اصلاحیه\nA17 128-6 72.000"]
    run(worker.price_tick())
    assert len(shop.notes) == 1
    msgs[2] = fake_message(11, text="اصلاحیه\nA17 128-6 71.000",
                           edit_date=datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc))
    run(worker.price_tick())
    assert shop.notes[-1]["text"].endswith("71.000")


def test_channel_roles_choose_the_price_and_proxy_channels(env, settings):
    worker, tg, shop, _ = env
    shop.roles = [{"ref": "OtherPrices", "role": "pricelist"},
                  {"ref": "ProxyMTProto", "role": "ignore"},
                  {"ref": "MoreProxies", "role": "proxy"}]
    settings.proxy_channels = ["ProxyMTProto", "ProxyChan"]
    assert run(worker.price_channel()) == "OtherPrices"
    assert run(worker.proxy_channels()) == ["MoreProxies", "ProxyChan"]


def test_joined_channels_are_reported(env):
    from types import SimpleNamespace

    worker, tg, shop, _ = env
    tg.dialogs = [
        SimpleNamespace(is_channel=True, name="لیست قیمت",
                        entity=SimpleNamespace(id=11, username="AbrishamiiPhoneMashhad",
                                               broadcast=True)),
        SimpleNamespace(is_channel=False, name="a person", entity=SimpleNamespace(id=5)),
        SimpleNamespace(is_channel=True, name="private", entity=SimpleNamespace(
            id=12, username=None, broadcast=True)),
    ]
    run(worker.ensure_connected())
    assert run(worker.channels_tick()) == 2
    assert [(c["id"], c["username"]) for c in shop.channels] == [
        (11, "AbrishamiiPhoneMashhad"), (12, "")]


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
    assert "tg_price_version" not in shop.state


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
#: v2.9.1: every link travels on in the canonical tg:// form
LINK2_TG = f"tg://proxy?server=two.example&port=8443&secret={'cd' * 16}"


def test_daily_collection_tests_new_links_and_adds_only_working_ones(env):
    worker, tg, shop, _ = env
    tg.channels["ProxyChan"] = [
        fake_message(5, text=f"fast proxy {LINK1} enjoy"),
        fake_message(6, text="connect", urls=[LINK2]),
        fake_message(7, text="x", button_urls=[LINK1, "https://example.com"]),
        fake_message(8, text="tg://proxy?server=bad&port=x&secret=zz"),
    ]
    tg.dead_proxies.add(("one.example", 443))
    run(worker.ensure_connected())
    assert run(worker.collect_tick()) == 1
    body = shop.candidates[-1]
    assert body["source"] == "channel:ProxyChan" and body["links"] == []
    assert [t["link"] for t in body["tested"]] == [LINK2_TG]
    assert body["failed"] == [LINK1]
    assert json.loads(shop.state["tg_proxy_last_ids"]) == {"ProxyChan": 8}
    assert worker.collect_info["tested"] == 2 and worker.collect_info["via"] == "account"
    # tests used throw-away anonymous clients, never the shop's session
    assert all(c.session_str == "" for c in tg.clients[1:])
    # not due again for a day (the pool counts as full here)
    shop.pool = [dict(pool_entry(i, f"p{i}.example"), last_ok_at="2026-10-12T08:00:00")
                 for i in range(1, 6)]
    assert run(worker.collect_tick()) == 0
    assert len(shop.candidates) == 1


def test_known_links_are_never_tested_again(env):
    worker, tg, shop, _ = env
    shop.known.add(LINK1)
    tg.channels["ProxyChan"] = [fake_message(5, text=f"{LINK1} {LINK2}")]
    run(worker.ensure_connected())
    before = len(tg.clients)
    assert run(worker.collect_tick()) == 1
    assert len(tg.clients) == before + 1          # only LINK2 was tested
    assert [t["link"] for t in shop.candidates[-1]["tested"]] == [LINK2_TG]


def test_testing_stops_when_the_pool_is_full(env, settings):
    worker, tg, shop, _ = env
    settings.pool_size = 1                       # 1 + 2 spare working proxies wanted
    links = [f"tg://proxy?server=n{i}.example&port=443&secret=dd{'ab' * 16}" for i in range(6)]
    tg.channels["ProxyChan"] = [fake_message(9, text=" ".join(links))]
    run(worker.ensure_connected())
    assert run(worker.collect_tick()) == 3
    assert len(shop.candidates[-1]["tested"]) == 3


def test_collection_without_login_uses_the_web_preview(env, settings, monkeypatch):
    worker, tg, shop, _ = env
    from app import webpreview

    settings.web_preview = True
    async def fake_fetch(channel, **_):
        assert channel == "ProxyChan"
        return [LINK2]
    monkeypatch.setattr(webpreview, "fetch_links", fake_fetch)
    assert not worker.tg.connected
    assert run(worker.collect_tick()) == 1
    assert worker.collect_info["via"] == "web"
    assert worker._next["health"] == 0.0         # try to connect right away


def test_web_preview_page_parsing():
    from app.webpreview import links_in_page

    post = '<div class="tgme_widget_message_wrap">'
    page = (post + '<a href="tg://proxy?server=a.example&amp;port=443&amp;secret=dd' + "ab" * 16
            + '">x</a></div>' + post + '<a href="https://t.me/proxy?server=b.example&amp;port=1&amp;'
            'secret=' + "cd" * 16 + '">y</a> <a href="https://t.me/ProxyMTProto">z</a>'
            '<a href="https://t.me/webproxy?server=c.example.&amp;secret=' + "ef" * 16 + '">w</a>'
            '</div>' + post + 'Server: <code>d.example</code><br/>Port: <code>8443</code><br/>'
            'Secret: <code>' + "12" * 16 + '</code></div>')
    links = links_in_page(page)
    assert links == [   # newest post first, canonical links, every format
        "tg://proxy?server=d.example&port=8443&secret=" + "12" * 16,
        "tg://proxy?server=b.example&port=1&secret=" + "cd" * 16,
        "tg://proxy?server=c.example&port=443&secret=" + "ef" * 16,
        "tg://proxy?server=a.example&port=443&secret=dd" + "ab" * 16,
    ]


def test_web_preview_fetch_errors_are_preview_errors():
    import httpx
    import pytest

    from app import webpreview

    def factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(webpreview.PreviewError):
        run(webpreview.fetch_links("ProxyMTProto", client_factory=factory))

    def ok_factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="<div class='tgme_widget_message_wrap'>"
                                               f"<a href='{LINK1}'>p</a></div>")))
    assert run(webpreview.fetch_links("ProxyMTProto", client_factory=ok_factory)) == [LINK1]

    def filtered_factory():   # v2.9.1: a filter page answers 200 too
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="<html>blocked</html>")))
    with pytest.raises(webpreview.PreviewError):
        run(webpreview.fetch_links("ProxyMTProto", client_factory=filtered_factory))


def test_collection_due_daily_and_hourly_while_short(env, settings):
    worker, _, _, _ = env
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    worker._now = lambda: now
    assert worker.collect_due("")
    assert not worker.collect_due((now - timedelta(hours=23)).isoformat(), healthy=10)
    assert worker.collect_due((now - timedelta(hours=24)).isoformat(), healthy=10)
    assert worker.collect_due((now - timedelta(minutes=61)).isoformat(), healthy=2)
    assert not worker.collect_due((now - timedelta(minutes=30)).isoformat(), healthy=2)
    settings.proxy_channels = []
    assert run(worker.collect_tick(force=True)) == 0


def test_flood_wait_pauses_every_job(env):
    worker, tg, shop, clock = env
    shop.pool = [pool_entry(1, "a.example")]
    run(worker.ensure_connected())

    class FloodWaitError(Exception):
        seconds = 120

    async def flooding(*a, **k):
        raise FloodWaitError()
    worker.price_tick = flooding
    worker._next["health"] = clock.t + 999
    run(worker.step())
    assert worker._paused_until == clock.t + 125
    assert "120" in worker.last_error
    calls = len(tg.calls)
    clock.t += 60
    run(worker.step())                      # still paused: nothing at all
    assert len(tg.calls) == calls


def test_price_download_failures_alert_the_owner(env):
    worker, tg, shop, _ = env
    shop.state["tg_price_last_id"] = "1"
    _channel(tg, [fake_message(2, pdf=PDF)])
    run(worker.ensure_connected())

    async def broken(*a, **k):
        raise ConnectionError("dropped")
    worker.tg.download = broken
    for _ in range(3):
        try:
            run(worker.price_tick())
        except ConnectionError:
            pass
    assert shop.alerts == ["telegram_pricelist_error"]
    assert worker.price_info["outcome"] == "download_failed"
    assert shop.state["tg_price_last_id"] == "1"      # tried again next time


def test_oversized_pdf_alerts_once(env, settings):
    worker, tg, shop, _ = env
    settings.pdf_max_bytes = 10
    shop.state["tg_price_last_id"] = "1"
    _channel(tg, [fake_message(2, pdf=b"%PDF" + b"x" * 50)])
    run(worker.ensure_connected())
    run(worker.price_tick())
    assert shop.alerts == ["telegram_pricelist_error"]
    assert worker.price_info["outcome"] == "too_large"


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
    assert status["price"]["ref"].endswith("/3") and status["pool_size"] == 10
    assert "h" * 32 not in shop.state["tg_status"]
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
