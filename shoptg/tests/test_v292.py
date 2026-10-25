"""v2.9.2: the last collection survives a restart, a short pool is refilled right
after a start, and «جمع‌آوری اکنون» from ShopAdmin runs a collection once."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fakes import fake_message

LINK = f"tg://proxy?server=new.example&port=443&secret=dd{'ab' * 16}"


def run(coro):
    return asyncio.run(coro)


def test_short_pool_is_refilled_right_after_a_start(env):
    worker, tg, shop, _ = env
    now = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
    worker._now = lambda: now
    # the previous run (another start) 30 minutes ago: hourly would wait 30 more
    shop.state["tg_proxy_collected_at"] = (now - timedelta(minutes=30)).isoformat()
    tg.channels["ProxyChan"] = [fake_message(5, text=LINK)]
    run(worker.ensure_connected())
    assert run(worker.collect_tick()) == 1
    # later checks keep the hourly rule
    shop.state["tg_proxy_collected_at"] = (now - timedelta(minutes=30)).isoformat()
    assert run(worker.collect_tick()) == 0
    assert worker.collect_due((now - timedelta(minutes=11)).isoformat(), healthy=1, first=True)
    assert not worker.collect_due((now - timedelta(minutes=5)).isoformat(), healthy=1,
                                  first=True)
    assert not worker.collect_due((now - timedelta(minutes=30)).isoformat(), healthy=10,
                                  first=True)


def test_last_collection_is_kept_for_the_status_after_a_restart(env):
    worker, tg, shop, _ = env
    tg.channels["ProxyChan"] = [fake_message(5, text=LINK)]
    run(worker.ensure_connected())
    run(worker.collect_tick())
    stored = json.loads(shop.state["tg_collect_info"])
    assert stored["found"] == 1 and stored["added"] == 1 and stored["via"] == "account"
    # a new worker (service restart): the status shows the stored collection
    worker.collect_info = {}
    worker._first_collect = False
    shop.state["tg_proxy_collected_at"] = worker._now().isoformat()
    run(worker.collect_tick())                       # not due
    assert worker.collect_info["found"] == 1
    run(worker.publish_status())
    assert json.loads(shop.state["tg_status"])["collect"]["added"] == 1


def test_collect_now_runs_once_per_request(env):
    worker, tg, shop, _ = env
    tg.channels["ProxyChan"] = [fake_message(5, text=LINK)]
    run(worker.ensure_connected())
    shop.state["tg_proxy_collected_at"] = worker._now().isoformat()   # not due by itself
    worker._first_collect = False
    assert run(worker.request_tick()) is False                        # nothing asked
    shop.state["tg_collect_request"] = "2026-10-25T09:00:00+00:00"
    assert run(worker.request_tick()) is True
    assert shop.state["tg_collect_done"] == "2026-10-25T09:00:00+00:00"
    assert len(shop.candidates) == 1
    assert run(worker.request_tick()) is False                        # handled already
    assert len(shop.candidates) == 1
